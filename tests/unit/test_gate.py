"""tests/unit/test_gate.py — evidence for DESIGN_COST_GOVERNANCE 1.4, Decisions 6 and 7.

Runs without Dagster or Snowflake: gate.py is loaded straight from its file, and
PENDING_RUNS is an in-memory SQLite table behind a pyformat adapter.

The DESIGN (1.0-1.3) claimed results from an ad-hoc simulation that was never in
the repository; this file reproduces them, and keeps the simulation that found
the 1.4 bug as a regression test (test_regression_*).
"""

from __future__ import annotations

import importlib.util
import json
import random
import re
import sqlite3
import sys
from dataclasses import replace
from datetime import datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("gate", ROOT / "dagster" / "pipeline" / "gate.py")
gate = importlib.util.module_from_spec(_spec)
sys.modules["gate"] = gate  # dataclasses resolve the module by name
_spec.loader.exec_module(gate)

T0 = datetime(2026, 11, 27, 0, 0)
N = timedelta(minutes=10)
ZERO = timedelta(0)


def minute(m: int) -> datetime:
    return T0 + timedelta(minutes=m)


# ── A world: Kafka activity per minute, gate-task rows landing in PENDING_RUNS ──


def run_world(activity, window, *, row_prob=1.0, lag=lambda m: 1, rng=None, after=None):
    """Simulate the sensor once per minute. Returns a trace.

    activity[m]  Kafka activity seen by Prometheus at minute m.
    A row for minute m lands in PENDING_RUNS at m + lag(m) with probability
    row_prob (row_prob < 1 models suspended/failing gate tasks). At each minute,
    rows land first, then the sensor ticks; a query consumes every landed row.
    """
    rng = rng or random.Random(0)
    after = after or gate.after_query
    landing: dict[int, int] = {}
    for m, active in enumerate(activity):
        if active and rng.random() < row_prob:
            landing[m + lag(m)] = landing.get(m + lag(m), 0) + 1
    state = gate.GateState(initialized=True)
    pending_rows: list[int] = []  # landing minutes of unconsumed rows
    trace = {"queries": [], "found": [], "waits": [], "empty_guard": [], "states": []}
    horizon = len(activity) + 3 * 60  # trailing quiet hours: everything must drain
    for m in range(horizon):
        pending_rows += [m] * landing.get(m, 0)
        active = activity[m] if m < len(activity) else False
        decision, state = gate.decide(state, minute(m), active, window)
        if decision == "query":
            found = bool(pending_rows)
            trace["queries"].append(m)
            if found:
                trace["found"].append(m)
                trace["waits"] += [m - landed for landed in pending_rows]
                pending_rows = []
            elif window > ZERO and state.quiet < gate.QUIET_CYCLES:
                trace["empty_guard"].append(m)
            state = after(state, minute(m), found, window)
        trace["states"].append(state)
    trace["stranded"] = pending_rows
    return trace


def bursts(*spans, length=None):
    """Activity list from (start, end_inclusive) spans."""
    end = length or max(e for _, e in spans) + 1
    activity = [False] * end
    for s, e in spans:
        for m in range(s, e + 1):
            activity[m] = True
    return activity


# ── Profile A: exact parity with v2 (window = 0) ──────────────────────────────


def v2_reference(activity):
    """v5 sensors.py logic, verbatim in behaviour: query on activity and 3 hot cycles."""
    hot, initialized, out = 0, False, []
    for active in activity:
        active = active or not initialized
        initialized = True
        if active:
            hot = 3
            out.append(True)
        elif hot > 0:
            hot -= 1
            out.append(True)
        else:
            out.append(False)
    return out


def gate_decisions(activity, window, found=lambda m: True, state=None):
    state = state or gate.GateState()
    out = []
    for m, active in enumerate(activity):
        decision, state = gate.decide(state, minute(m), active, window)
        out.append(decision == "query")
        if decision == "query":
            state = gate.after_query(state, minute(m), found(m), window)
    return out, state


def test_legacy_parity_with_v2_on_500_random_sequences():
    rng = random.Random(20261118)
    for _ in range(500):
        activity = [
            rng.random() < rng.choice([0.05, 0.2, 0.5, 0.9]) for _ in range(rng.randint(1, 200))
        ]
        found = {m: rng.random() < 0.5 for m in range(len(activity))}
        ours, _ = gate_decisions(activity, ZERO, found=found.__getitem__)
        assert ours == v2_reference(activity)


def test_legacy_queries_on_activity_and_three_hot_cycles():
    ours, _ = gate_decisions(bursts((0, 0), length=8), ZERO)
    assert [m for m, q in enumerate(ours) if q] == [0, 1, 2, 3]


# ── Profile B: settle, window, starvation guard ───────────────────────────────


def test_settled_burst_runs_once():
    trace = run_world(bursts((0, 4)), N)
    assert trace["queries"] == [7] and trace["found"] == [7]  # quiet 3 after the last activity


def test_window_holds_the_second_group_of_a_cluster():
    # DESIGN measurement plan: bursts at 0, 2, 4, 10, 12 -> runs ~:07 and ~:17.
    activity = bursts((0, 0), (2, 2), (4, 4), (10, 10), (12, 12))
    trace = run_world(activity, N)
    assert trace["found"] == [7, 17]


def test_starvation_guard_runs_at_most_once_per_window_under_continuous_traffic():
    trace = run_world(bursts((0, 59)), N)
    assert [q for q in trace["queries"] if q < 60] == [10, 20, 30, 40, 50]
    # Traffic stops at 59: the guard at 60 consumes the last rows (still arriving),
    # the settled check waits for the window (70), finds nothing, and its one retry
    # follows at once (71) because quiet is already >= 2 x QUIET_CYCLES. Those are
    # the "at most two consecutive queries" of Decision 6; then the burst clears.
    assert trace["queries"][5:] == [60, 70, 71]
    assert trace["found"] == [10, 20, 30, 40, 50, 60]
    assert trace["states"][-1].pending is False


def test_empty_settled_query_gets_one_more_settled_check_then_clears():
    trace = run_world(bursts((0, 4)), N, row_prob=0.0)
    assert trace["queries"] == [7, 10]  # quiet 3, then quiet 6 (retries=1)
    assert trace["states"][-1].pending is False


def test_empty_starvation_guard_query_followed_by_immediate_retry_is_at_most_two():
    # Continuous traffic, rows never arrive: no two queries closer than the window,
    # so at most two consecutive queries (the guard and the settled check) ever happen.
    trace = run_world(bursts((0, 120)), N, row_prob=0.0)
    gaps = [b - a for a, b in zip(trace["queries"], trace["queries"][1:], strict=False)]
    consecutive = max(
        (len(run) for run in re.findall(r"1+", "".join("1" if g == 1 else "0" for g in gaps))),
        default=0,
    )
    assert consecutive + 1 <= 2


# ── 1.4 regression: the simulation that found the bug, kept verbatim ─────────


def _after_query_design_1_3(state, now, found_rows, window):
    """Pattern 4 after_query as written in DESIGN 1.0-1.3 (before the 1.4 fix)."""
    if found_rows:
        state = replace(state, last_run_at=now)
    if window == ZERO:
        return replace(state, pending=state.quiet < gate.LEGACY_HOT_CYCLES)
    if found_rows or state.retries >= 1:
        still_arriving = state.quiet < gate.QUIET_CYCLES
        return replace(
            state, pending=still_arriving, pending_since=now if still_arriving else None, retries=0
        )
    return replace(state, retries=state.retries + 1)


def _continuous_traffic_empty_pending(after):
    state, queries = gate.GateState(initialized=True), []
    for m in range(60):
        decision, state = gate.decide(state, minute(m), True, N)
        if decision == "query":
            queries.append(m)
            state = after(state, minute(m), False, N)
    return queries


def test_regression_design_1_3_queried_every_minute():
    # Documents the defect: 50 Snowflake queries in 60 min, CDC_WH never suspends.
    assert len(_continuous_traffic_empty_pending(_after_query_design_1_3)) == 50


def test_regression_fixed_queries_once_per_window():
    assert _continuous_traffic_empty_pending(gate.after_query) == [10, 20, 30, 40, 50]


def test_explicit_empty_guard_mid_burst_restarts_the_clock_then_finds_rows():
    """Burst arriving, the guard query finds nothing (rows not landed yet), the clock restarts."""
    window = N
    state = gate.GateState(initialized=True)
    for m in range(10):  # continuous activity, no rows yet
        decision, state = gate.decide(state, minute(m), True, window)
        assert decision == "skip"
    decision, state = gate.decide(state, minute(10), True, window)
    assert decision == "query" and state.quiet < gate.QUIET_CYCLES  # a starvation-guard query
    state = gate.after_query(state, minute(10), False, window)  # empty: rows still in flight
    assert state.pending and state.pending_since == minute(10) and state.retries == 0
    for m in range(11, 20):  # rows land at 11, but the next guard waits a full window
        decision, state = gate.decide(state, minute(m), True, window)
        assert decision == "skip", m
    decision, state = gate.decide(state, minute(20), True, window)
    assert decision == "query"
    state = gate.after_query(state, minute(20), True, window)
    assert state.last_run_at == minute(20) and state.pending  # still arriving


# ── Property: no stranded row, worst wait <= N, on 2,000 random worlds ────────


def _random_world(rng):
    activity, m = [], 0
    while m < rng.randint(60, 300):
        gap = rng.choice([0, 1, 2, rng.randint(3, 60)])
        length = rng.choice([1, 2, 5, rng.randint(1, 40)])
        activity += [False] * gap + [True] * length
        m = len(activity)
    return activity


def _longest_adjacent_run(queries):
    longest = run = 1 if queries else 0
    for a, b in zip(queries, queries[1:], strict=False):
        run = run + 1 if b - a == 1 else 1
        longest = max(longest, run)
    return longest


def test_no_stranded_row_and_worst_wait_within_window_on_2000_sequences():
    rng = random.Random(42)
    worst, empty_guards, empty_guard_then_found = 0, 0, 0
    for _ in range(2000):
        activity = _random_world(rng)
        row_prob = rng.choice([1.0, 1.0, 0.7, 0.3, 0.05])
        trace = run_world(activity, N, row_prob=row_prob, lag=lambda m: rng.randint(0, 2), rng=rng)
        assert trace["stranded"] == []
        # Query rate: never more than two queries in consecutive minutes (Decision 6).
        # This is the property the 1.0-1.3 Pattern 4 broke; the wait bound alone
        # does not see it (extra queries do not lengthen waits).
        assert _longest_adjacent_run(trace["queries"]) <= 2
        if trace["waits"]:
            worst = max(worst, max(trace["waits"]))
        empty_guards += len(trace["empty_guard"])
        empty_guard_then_found += sum(
            1 for g in trace["empty_guard"] if any(f > g for f in trace["found"])
        )
    assert worst <= 10, f"worst wait {worst} min > N"
    # Owner condition: the corpus must exercise empty guard queries in the middle
    # of a burst (and a later run that finds rows), or the bound above proves little.
    assert empty_guards > 100
    assert empty_guard_then_found > 50


# ── Cursor: round trip and migration from the v5 format ──────────────────────


def test_cursor_round_trip():
    state = gate.GateState(
        quiet=2,
        last_run_at=minute(5),
        pending=True,
        pending_since=minute(3),
        retries=1,
        initialized=True,
    )
    totals = {"pg.public.orders": 12.0}
    again, totals_again = gate.from_cursor(gate.to_cursor(state, totals), minute(9))
    assert again == state and totals_again == totals


def test_empty_cursor_is_uninitialized_and_fails_open():
    state, totals = gate.from_cursor(None, minute(0))
    assert state == gate.GateState() and totals == {}
    # Profile A (v2): the first tick queries at once.
    assert gate.decide(state, minute(0), False, ZERO)[0] == "query"
    # Profile B: the first tick opens a pending burst; it queries once it settles,
    # so rows written before the sensor started are still picked up (3 min later).
    trace_states, decisions = state, []
    for m in range(5):
        decision, trace_states = gate.decide(trace_states, minute(m), False, N)
        decisions.append(decision)
    assert decisions[:4] == ["skip", "skip", "skip", "query"]


@pytest.mark.parametrize("hot", [0, 1, 2, 3])
def test_v2_cursor_migrates_and_keeps_v2_behaviour(hot):
    v2_cursor = json.dumps({"totals": {"pg.public.orders": 7.0}, "hot": hot, "initialized": True})
    state, totals = gate.from_cursor(v2_cursor, minute(0))
    assert totals == {"pg.public.orders": 7.0} and state.initialized
    assert state.pending == (hot > 0)
    # Continue with no activity in profile A: v2 would query exactly `hot` more cycles.
    ours, _ = gate_decisions([False] * 6, ZERO, state=state)
    assert sum(ours) == hot


def test_v2_cursor_migrates_into_profile_b_without_crashing():
    state, _ = gate.from_cursor(
        json.dumps({"totals": {}, "hot": 3, "initialized": True}), minute(0)
    )
    decision, state = gate.decide(state, minute(1), False, N)
    assert decision in {"query", "skip"} and state.pending_since == minute(0)


# ── PENDING_RUNS: UPDATE-first consumption, the race, failed-run release ──────


class _Cursor:
    """DB-API cursor over SQLite that accepts Snowflake's pyformat and fires hooks."""

    def __init__(self, conn, hooks):
        self._cur, self._hooks = conn.cursor(), hooks

    def execute(self, sql, params=None):
        sqlite_sql = re.sub(r"%\((\w+)\)s", r":\1", sql)
        self._cur.execute(sqlite_sql, params or {})
        for pattern, hook in self._hooks:
            if re.search(pattern, sql):
                hook()
        return self

    def fetchall(self):
        return self._cur.fetchall()

    @property
    def rowcount(self):
        return self._cur.rowcount


class _Conn:
    def __init__(self, hooks=()):
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.db.execute("ATTACH ':memory:' AS CONFIG")
        self.db.execute(
            "CREATE TABLE CONFIG.PENDING_RUNS (domain TEXT, detected_at TEXT, "
            "consumed BOOLEAN DEFAULT FALSE, consumed_run_key TEXT)"
        )
        self.hooks = list(hooks)

    def cursor(self):
        return _Cursor(self.db, self.hooks)

    def commit(self):
        if self.db.in_transaction:
            self.db.execute("COMMIT")

    def insert(self, domain, at="2026-11-27 00:00:00"):
        self.db.execute(
            "INSERT INTO CONFIG.PENDING_RUNS (domain, detected_at, consumed) VALUES (?, ?, FALSE)",
            (domain, at),
        )

    def rows(self):
        return self.db.execute(
            "SELECT domain, consumed, consumed_run_key FROM CONFIG.PENDING_RUNS ORDER BY rowid"
        ).fetchall()


def test_consume_marks_then_reads_exactly_the_marked_rows():
    conn = _Conn()
    conn.insert("ORDERS")
    conn.insert("DRIVERS")
    rows = gate.consume_pending(conn, "bronze-k1")
    assert sorted(r[0] for r in rows) == ["DRIVERS", "ORDERS"]
    assert conn.rows() == [("ORDERS", 1, "bronze-k1"), ("DRIVERS", 1, "bronze-k1")]
    assert gate.consume_pending(conn, "bronze-k2") == []  # nothing left


def test_race_a_row_inserted_after_the_update_stays_pending():
    conn = _Conn()
    conn.insert("ORDERS")
    conn.hooks.append(
        (r"SET consumed = TRUE", lambda: conn.insert("RESTAURANTS"))
    )  # gate task fires
    rows = gate.consume_pending(conn, "bronze-k1")
    assert [r[0] for r in rows] == ["ORDERS"]
    assert ("RESTAURANTS", 0, None) in conn.rows()  # not marked, not lost
    conn.hooks.clear()
    assert [r[0] for r in gate.consume_pending(conn, "bronze-k2")] == ["RESTAURANTS"]


def test_race_documented_v5_order_marked_an_unread_row():
    """v5: SELECT pending, then UPDATE ... WHERE consumed = FALSE — the defect 1.4 removes."""
    conn = _Conn()
    conn.insert("ORDERS")
    cur = conn.cursor()
    read = cur.execute("SELECT domain FROM CONFIG.PENDING_RUNS WHERE consumed = FALSE").fetchall()
    conn.insert("RESTAURANTS")  # gate task fires between the two statements
    cur.execute("UPDATE CONFIG.PENDING_RUNS SET consumed = TRUE WHERE consumed = FALSE")
    assert [r[0] for r in read] == ["ORDERS"]
    assert ("RESTAURANTS", 1, None) in conn.rows()  # consumed, never read: a lost trigger


def test_failed_read_rolls_back_the_marks():
    conn = _Conn()
    conn.insert("ORDERS")

    def boom():
        raise RuntimeError("network")

    conn.hooks.append((r"SELECT domain, detected_at", boom))
    with pytest.raises(RuntimeError):
        gate.consume_pending(conn, "bronze-k1")
    assert conn.rows() == [("ORDERS", 0, None)]


def test_failed_run_rows_are_released_and_reprocessed_by_the_next_query():
    """Decision 7 (1.4): reprocess, never accept the loss; no automatic retry."""
    conn = _Conn()
    conn.insert("ORDERS")
    conn.insert("DRIVERS")
    gate.consume_pending(conn, "bronze-failed")
    conn.insert("RESTAURANTS")
    gate.consume_pending(conn, "bronze-other")  # a later, healthy run
    assert gate.release_pending(conn, "bronze-failed") == 2
    assert conn.rows() == [
        ("ORDERS", 0, None),
        ("DRIVERS", 0, None),
        ("RESTAURANTS", 1, "bronze-other"),
    ]
    again = gate.consume_pending(conn, "bronze-next")
    assert sorted(r[0] for r in again) == [
        "DRIVERS",
        "ORDERS",
    ]  # attributed to the run that consumed them
    assert gate.release_pending(conn, "bronze-unknown") == 0


def test_run_keys_are_unique_and_prefixed():
    keys = {gate.new_run_key(minute(0)) for _ in range(1000)}
    assert len(keys) == 1000 and all(k.startswith(gate.RUN_KEY_PREFIX) for k in keys)


# ── Static checks on the Dagster wiring (Dagster is not installed in CI) ──────

SENSORS = (ROOT / "dagster" / "pipeline" / "sensors.py").read_text()
ASSETS = (ROOT / "dagster" / "pipeline" / "assets.py").read_text()
INIT = (ROOT / "dagster" / "pipeline" / "__init__.py").read_text()


def test_sensor_uses_the_gate_and_the_update_first_consumption():
    assert "gate.decide(" in SENSORS and "gate.after_query(" in SENSORS
    assert "gate.consume_pending(conn, run_key)" in SENSORS
    assert "run_key=run_key" in SENSORS
    assert 'BATCH_WINDOW_MINUTES = int(os.getenv("BATCH_WINDOW_MINUTES", "0"))' in SENSORS
    assert "PRIMARY KEY" not in SENSORS  # the false v5 comment is gone
    assert 'WHERE consumed = FALSE\n            """' not in SENSORS  # no v5 read-then-mark


def test_release_sensor_monitors_the_pipeline_job_without_retrying():
    block = SENSORS.split("@run_failure_sensor(", 1)[1].split("\ndef registry", 1)[0]
    assert "monitored_jobs=[cdc_pipeline_job]" in block
    assert "gate.release_pending(conn, run_key)" in block
    assert "request_job" not in block and "RunRequest" not in block
    assert "pending_run_release_sensor" in INIT


def test_processing_log_gets_the_run_key():
    assert 'run_key = context.run_tags.get("dagster/run_key")' in ASSETS
    assert "error_message, triggered_by, logged_at, run_key" in ASSETS
    insert = ASSETS.split("INSERT INTO", 1)[1].split('"""', 1)[0]
    assert insert.count("%s") == 14
