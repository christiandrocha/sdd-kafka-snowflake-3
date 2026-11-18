"""
gate.py — when bronze_new_data_sensor may touch Snowflake (COST_GOVERNANCE, REQ-05).

DESIGN_COST_GOVERNANCE 1.4, Decision 6 (Pattern 4) and Decision 7.

Two halves, neither imports Dagster, so tests/unit/test_gate.py runs without it:

1. The decision. ``decide`` / ``after_query`` are pure functions over ``GateState``;
   the sensor calls them once per 60-second cycle.
   * Profile A (``window == 0``) reproduces v2 exactly: query on the cycle with
     Kafka activity and on the next ``LEGACY_HOT_CYCLES`` cycles.
   * Profile B (``window = N``) queries only when a burst is pending, at least N
     since the last run that found rows, and either the burst has settled
     (``QUIET_CYCLES`` quiet cycles) or it has been pending for N (starvation
     guard). An empty settled query gets one more settled check; an empty
     starvation-guard query restarts the starvation clock (1.4 fix: without it,
     continuous traffic with an empty PENDING_RUNS made the sensor query every
     minute and CDC_WH never suspended).

2. PENDING_RUNS consumption (DB-API, Snowflake connector paramstyle ``pyformat``).
   ``consume_pending`` marks rows FIRST, under a fresh run key, inside one
   transaction, and then reads exactly the rows it marked. A row a gate task
   inserts meanwhile is not marked and stays pending for the next query.
   ``release_pending`` returns a failed run's rows to pending (Decision 7:
   reprocess, never accept the loss; no automatic retry).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timedelta
from typing import Any

LEGACY_HOT_CYCLES = 3  # v2 behaviour, used when the window is 0 (profile A)
QUIET_CYCLES = 3  # profile B: quiet cycles before a burst counts as settled (Decision 6)

RUN_KEY_PREFIX = "bronze-"


# ── 1. The decision ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class GateState:
    quiet: int = 0  # cycles since the last Kafka activity
    last_run_at: datetime | None = None  # last query that found rows
    pending: bool = False  # a burst was seen and not yet confirmed consumed
    pending_since: datetime | None = None  # starts the starvation clock
    retries: int = 0  # empty settled queries for the current burst
    initialized: bool = False  # False on a fresh cursor: fail-open once


def decide(
    state: GateState, now: datetime, kafka_activity: bool, window: timedelta
) -> tuple[str, GateState]:
    """Return ("query" | "skip", new_state). Never queries Snowflake while idle."""
    if kafka_activity or not state.initialized:
        since = state.pending_since if state.pending and state.pending_since else now
        state = replace(
            state, quiet=0, pending=True, pending_since=since, retries=0, initialized=True
        )
    else:
        state = replace(state, quiet=state.quiet + 1)

    if not state.pending:
        return "skip", state
    if window == timedelta(0):  # profile A: v2 semantics
        return ("query" if state.quiet <= LEGACY_HOT_CYCLES else "skip"), state

    pending_since = state.pending_since or now
    settled = state.quiet >= QUIET_CYCLES * (1 + state.retries)
    waited_enough = now - pending_since >= window  # starvation guard
    window_open = state.last_run_at is None or now - state.last_run_at >= window
    return ("query" if (settled or waited_enough) and window_open else "skip"), state


def after_query(
    state: GateState, now: datetime, found_rows: bool, window: timedelta
) -> GateState:
    """Update the state after a query of PENDING_RUNS (found_rows = it marked any row)."""
    if found_rows:
        state = replace(state, last_run_at=now)
    if window == timedelta(0):
        return replace(state, pending=state.quiet < LEGACY_HOT_CYCLES)

    settled = state.quiet >= QUIET_CYCLES
    if found_rows or (settled and state.retries >= 1):
        still_arriving = state.quiet < QUIET_CYCLES  # ran on the starvation guard mid-burst
        return replace(
            state,
            pending=still_arriving,
            pending_since=now if still_arriving else None,
            retries=0,
        )
    if not settled:  # 1.4: empty starvation-guard query -> restart the clock, wait another N
        return replace(state, pending_since=now)
    return replace(state, retries=state.retries + 1)  # one more settled check, then give up


# ── Cursor (Dagster sensor cursor is a string) ───────────────────────────────


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def to_cursor(state: GateState, totals: dict[str, float]) -> str:
    gate = asdict(state)
    for key in ("last_run_at", "pending_since"):
        gate[key] = gate[key].isoformat() if gate[key] else None
    return json.dumps({"v": 3, "totals": totals, "gate": gate}, sort_keys=True)


def from_cursor(raw: str | None, now: datetime) -> tuple[GateState, dict[str, float]]:
    """Parse the sensor cursor, migrating v2's {"totals", "hot", "initialized"}.

    v2's ``hot`` = cycles left to query after the last activity, so hot h > 0 means
    the burst is still pending and ``quiet = LEGACY_HOT_CYCLES - h``. The starvation
    clock of a migrated burst starts now (v2 had none).
    """
    data: dict[str, Any] = json.loads(raw) if raw else {}
    totals = data.get("totals", {})
    if "gate" in data:
        g = data["gate"]
        return (
            GateState(
                quiet=int(g["quiet"]),
                last_run_at=_dt(g["last_run_at"]),
                pending=bool(g["pending"]),
                pending_since=_dt(g["pending_since"]),
                retries=int(g["retries"]),
                initialized=bool(g["initialized"]),
            ),
            totals,
        )
    hot = int(data.get("hot", 0))
    initialized = bool(data.get("initialized", False))
    if hot > 0:
        return (
            GateState(
                quiet=max(0, LEGACY_HOT_CYCLES - hot),
                pending=True,
                pending_since=now,
                initialized=initialized,
            ),
            totals,
        )
    return GateState(initialized=initialized), totals


# ── 2. PENDING_RUNS consumption ──────────────────────────────────────────────

MARK_SQL = """
    UPDATE CONFIG.PENDING_RUNS
       SET consumed = TRUE, consumed_run_key = %(run_key)s
     WHERE consumed = FALSE
"""

READ_MARKED_SQL = """
    SELECT domain, detected_at
      FROM CONFIG.PENDING_RUNS
     WHERE consumed_run_key = %(run_key)s
"""

RELEASE_SQL = """
    UPDATE CONFIG.PENDING_RUNS
       SET consumed = FALSE, consumed_run_key = NULL
     WHERE consumed_run_key = %(run_key)s
"""


def new_run_key(now: datetime) -> str:
    """Unique per query: also the Dagster run_key and PROCESSING_LOG.RUN_KEY (Decision 7)."""
    return f"{RUN_KEY_PREFIX}{now:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:8]}"


def consume_pending(conn, run_key: str) -> list[tuple]:
    """Mark every pending row with run_key, then return exactly those rows.

    One transaction: if the read fails, nothing stays marked. A gate task's INSERT
    that lands after the UPDATE is not marked and waits for the next query — the
    v2 order (SELECT, then UPDATE ... WHERE consumed = FALSE) marked it consumed
    without reading it.
    """
    cur = conn.cursor()
    cur.execute("BEGIN")
    try:
        cur.execute(MARK_SQL, {"run_key": run_key})
        cur.execute(READ_MARKED_SQL, {"run_key": run_key})
        rows = cur.fetchall()
        cur.execute("COMMIT")
    except Exception:
        cur.execute("ROLLBACK")
        raise
    return rows


def release_pending(conn, run_key: str) -> int:
    """Return a failed run's rows to pending (Decision 7). Returns the rows released."""
    cur = conn.cursor()
    cur.execute(RELEASE_SQL, {"run_key": run_key})
    released = cur.rowcount
    conn.commit()
    return released if released is not None and released >= 0 else 0
