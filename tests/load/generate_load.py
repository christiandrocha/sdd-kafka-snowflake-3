#!/usr/bin/env python3
"""
generate_load.py — seeded, fixed-schedule CDC load for the A/B measurement.

COST_GOVERNANCE manifest item 14; REQ-06 / AT-007. DESIGN_COST_GOVERNANCE 1.4:
Measurement plan, Decision 5 (task-state check), Configuration.

SCHEDULE (pure, see ``schedule``)
  One cluster every LOAD_CLUSTER_MINUTES (120), starting at :30 UTC
  (00:30, 02:30, …), so no cluster crosses a 00:00 UTC profile switch. Each
  cluster has bursts at LOAD_BURST_OFFSETS minutes (0, 2, 4, 10, 12). Each burst
  holds LOAD_ROWS_PER_BURST (200) row operations across the 10 Tier-1 tables.

CONTENT (pure, see ``plan_burst``)
  Each burst has its own RNG seeded by (LOAD_SEED, burst_id), so the same
  seed always gives the same operations, even after a restart. Fact tables are
  insert-only (append-only at the source). Entity tables get about half
  updates, only against rows inserted by an EARLIER burst of the same run
  (keys are deterministic UUIDs). All values are synthetic (Constitution D1):
  CPF/CNPJ-shaped random digits with no valid check digit, @example.com
  e-mails, names from fixed lists.

EXECUTION
  One Postgres transaction per burst. After COMMIT, a line
  ``burst_id, committed_at_utc, rows, source`` is appended to
  <out>/commits.csv. ``rows`` = rows actually affected. If that is below the
  planned count (an update whose target row does not exist, e.g. its burst was
  skipped), a warning goes to stderr and the count stays honest.

  Late bursts: a burst more than LATE_TOLERANCE (60 s) past its time is NOT run
  late — it is written to <out>/skipped.csv and to stderr. A skipped burst is a
  gap: DESIGN validity rules decide whether the window is void.

  Restart / resume: bursts already in commits.csv are not run again. A crash
  BETWEEN the Postgres COMMIT and the CSV append leaves a committed burst
  without its line; on restart, every past burst missing from commits.csv is
  probed by the deterministic key of its first ``orders`` insert. If the row
  exists, the burst is logged with ``source=recovered`` and committed_at_utc =
  that row's dt_current_timestamp (Postgres NOW() = transaction start, a few
  ms before the commit). It is never re-executed: replaying its updates would
  emit duplicate CDC events. Inserts use ON CONFLICT DO NOTHING as a second
  guard.

TASK-STATE CHECK (Decision 5)
  At start-up and 20 min after each cluster starts, ``SHOW TASKS LIKE
  '%_GATE_TASK' IN SCHEMA CDC_POC.BRONZE`` runs as CDC_ROLE_RO (key-pair user,
  default CURSOR_MCP_USER) with no USE WAREHOUSE — SHOW is metadata-only and
  never resumes a warehouse. Results go to <out>/task_states.csv with a
  cumulative ``window_valid`` column: it turns false at the first check that
  sees any gate task not 'started', and stays false. A task not 'started' is a
  stderr warning; the load continues. If the check does not see EXACTLY the ten
  gate tasks, the generator stops with an error: zero rows from SHOW means "this
  role cannot see them", never "all is well" (v2's verify_governance trap).

USAGE
  python tests/load/generate_load.py --window A \\
      --start 2026-11-25T00:00Z --end 2026-11-27T00:00Z --out docs/measurement/runs/A
  python tests/load/generate_load.py --window A --start … --end … --out … --plan-only

  Environment: LOAD_SEED, LOAD_CLUSTER_MINUTES, LOAD_BURST_OFFSETS,
  LOAD_ROWS_PER_BURST; POSTGRES_HOST/PORT/DB/USER/PASSWORD; SNOWFLAKE_ACCOUNT,
  LOAD_SNOWFLAKE_USER, LOAD_SNOWFLAKE_PRIVATE_KEY_PATH. Never prints secrets.

  Requirements (host or VM, not CI): psycopg2-binary, snowflake-connector-python,
  cryptography. They are imported lazily, so the unit tests need none of them.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
import time
import uuid
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

LATE_TOLERANCE = timedelta(seconds=60)
TASK_CHECK_DELAY = timedelta(minutes=20)
ANCHOR_MINUTE = 30
NAMESPACE = uuid.UUID("6f1d0c3e-5b8a-4c1e-9a77-cdc0000000a3")  # fixed: keys are reproducible

GATE_TASKS = frozenset(
    f"{d}_GATE_TASK"
    for d in (
        "ORDERS",
        "ORDER_ITEMS",
        "DRIVERS",
        "DRIVER_SHIFTS",
        "RESTAURANTS",
        "USERS_MONGO",
        "USERS_MSSQL",
        "PAYMENT_EVENTS",
        "RECOMMENDATIONS",
        "SEARCH_EVENTS",
    )
)

# Rows per 200-row burst. Facts are insert-only at the source; entities get updates.
TABLE_WEIGHTS: dict[str, int] = {
    "orders": 30,
    "order_items": 60,
    "payment_events": 30,
    "search_events": 20,
    "recommendations": 20,
    "driver_shifts": 10,
    "users_mongo": 8,
    "users_mssql": 8,
    "restaurants": 7,
    "drivers": 7,
}
ENTITY_TABLES = frozenset(
    {"orders", "driver_shifts", "users_mongo", "users_mssql", "restaurants", "drivers"}
)
PRIMARY_KEYS = {
    "orders": "order_id",
    "order_items": "order_item_id",
    "payment_events": "event_id",
    "search_events": "search_id",
    "recommendations": "event_id",
    "driver_shifts": "shift_id",
    "users_mongo": "uuid",
    "users_mssql": "uuid",
    "restaurants": "uuid",
    "drivers": "uuid",
}

CITIES = ["São Paulo", "Rio de Janeiro", "Belo Horizonte", "Curitiba", "Recife", "Vitória"]
FIRST = ["Ana", "Bruno", "Carla", "Diego", "Elisa", "Fábio", "Gabi", "Hugo", "Iris", "João"]
LAST = ["Silva", "Souza", "Lima", "Costa", "Rocha", "Alves", "Pereira", "Gomes"]
CUISINES = ["Brazilian", "Japanese", "Italian", "Arabic", "Vegan", "Burgers"]
PRODUCTS = ["Feijoada", "Sushi Combo", "Margherita", "Esfiha", "Bowl", "Smash Burger"]
VEHICLES = [("motorcycle", "Honda", "CG 160"), ("bike", "Caloi", "Urbam"), ("car", "Fiat", "Mobi")]


# ── Schedule ─────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Burst:
    burst_id: str
    cluster_id: str
    at: datetime  # UTC
    index: int  # position in the cluster


def schedule(
    start: datetime,
    end: datetime,
    cluster_minutes: int = 120,
    offsets: Iterable[int] = (0, 2, 4, 10, 12),
) -> list[Burst]:
    """Every burst with start <= at < end. Clusters start at :30 UTC, every cluster_minutes."""
    offsets = tuple(sorted(offsets))
    if not offsets or offsets[0] < 0:
        raise ValueError("offsets must be non-negative")
    if offsets[-1] >= cluster_minutes:
        raise ValueError("every burst must fall inside its cluster")
    if (24 * 60) % cluster_minutes:
        raise ValueError("cluster_minutes must divide a day, so clusters align on UTC days")
    if ANCHOR_MINUTE + offsets[-1] >= cluster_minutes:
        raise ValueError("a cluster would cross the next cluster's start")
    start, end = start.astimezone(UTC), end.astimezone(UTC)
    day = datetime(start.year, start.month, start.day, tzinfo=UTC)
    cluster = day + timedelta(minutes=ANCHOR_MINUTE)
    while cluster + timedelta(minutes=offsets[-1]) < start:
        cluster += timedelta(minutes=cluster_minutes)
    bursts = []
    while cluster < end:
        cluster_id = f"c{cluster:%Y%m%dT%H%M}"
        for i, off in enumerate(offsets):
            at = cluster + timedelta(minutes=off)
            if start <= at < end:
                bursts.append(Burst(f"{cluster_id}-b{i}", cluster_id, at, i))
        cluster += timedelta(minutes=cluster_minutes)
    return bursts


def allocate(rows: int) -> dict[str, int]:
    """Split ``rows`` over the tables by TABLE_WEIGHTS (largest remainder, deterministic)."""
    total = sum(TABLE_WEIGHTS.values())
    exact = {t: rows * w / total for t, w in TABLE_WEIGHTS.items()}
    counts = {t: int(v) for t, v in exact.items()}
    for t in sorted(exact, key=lambda t: (-(exact[t] - counts[t]), t))[
        : rows - sum(counts.values())
    ]:
        counts[t] += 1
    return counts


# ── Burst content ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class Op:
    table: str
    kind: str  # "insert" | "update"
    key: str
    values: dict = field(default_factory=dict, compare=True, hash=False)


def row_key(seed: int, table: str, burst_id: str, i: int) -> str:
    return str(uuid.uuid5(NAMESPACE, f"{seed}/{table}/{burst_id}/{i}"))


def probe_key(seed: int, burst_id: str) -> str:
    """Key of the burst's first orders insert — orders always gets >= 1 insert."""
    return row_key(seed, "orders", burst_id, 0)


def _digits(rng: random.Random, n: int) -> str:
    return "".join(str(rng.randrange(10)) for _ in range(n))


def _cpf(rng):  # synthetic: random digits, no valid check digit (D1)
    d = _digits(rng, 11)
    return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"


def _cnpj(rng):
    d = _digits(rng, 14)
    return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"


def _phone(rng):
    return f"+55 11 9{_digits(rng, 4)}-{_digits(rng, 4)}"


def _insert_values(table: str, rng: random.Random, at: datetime) -> dict:
    ts = at.isoformat()
    if table == "orders":
        return {
            "order_date": ts,
            "total_amount": round(rng.uniform(15, 250), 2),
            "user_key": _cpf(rng),
            "restaurant_key": _cnpj(rng),
            "driver_key": f"DRV-{rng.randrange(1, 400):05d}",
            "payment_key": str(uuid.UUID(int=rng.getrandbits(128))),
        }
    if table == "order_items":
        price, qty = round(rng.uniform(5, 90), 2), rng.randint(1, 4)
        return {
            "order_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "product_id": f"PRD-{rng.randrange(99999):05d}",
            "restaurant_id": rng.randint(1, 500),
            "product_name": rng.choice(PRODUCTS),
            "product_type": rng.choice(["main", "side", "drink"]),
            "cuisine_type": rng.choice(CUISINES),
            "unit_price": price,
            "quantity": qty,
            "subtotal": round(price * qty, 2),
            "discount_applied": round(rng.choice([0, 0, 0, 2.5, 5]), 2),
            "modifiers": rng.choice(["", "no ice", "extra sauce"]),
            "is_combo": rng.random() < 0.2,
            "is_vegetarian": rng.random() < 0.3,
        }
    if table == "payment_events":
        return {
            "payment_id": str(uuid.UUID(int=rng.getrandbits(128))),
            "event": json.dumps(
                {
                    "event_name": rng.choice(["created", "authorized", "captured", "refunded"]),
                    "timestamp": int(at.timestamp() * 1000),
                }
            ),
        }
    if table == "search_events":
        return {
            "user_id": rng.randint(1, 5000),
            "query_text": rng.choice(PRODUCTS).lower(),
            "filters": rng.choice(["", "price<50", "rating>4"]),
            "result_count": rng.randint(0, 60),
            "clicked_product_id": f"PRD-{rng.randrange(99999):05d}",
            "timestamp": ts,
        }
    if table == "recommendations":
        return {
            "user_id": rng.randint(1, 5000),
            "product_id": f"PRD-{rng.randrange(99999):05d}",
            "event_type": rng.choice(["view", "click", "purchase", "dismiss"]),
            "timestamp": ts,
        }
    if table == "driver_shifts":
        minutes = rng.randint(60, 600)
        return {
            "driver_id": f"DRV-{rng.randrange(1, 400):05d}",
            "city": rng.choice(CITIES),
            "region": "BR-SE",
            "shift_type": rng.choice(["full-time", "part-time"]),
            "login_method": rng.choice(["app", "sso"]),
            "device_os": rng.choice(["android", "ios"]),
            "start_time": ts,
            "end_time": (at + timedelta(minutes=minutes)).isoformat(),
            "shift_duration_min": minutes,
            "num_orders": rng.randint(0, 30),
            "distance_covered_km": round(rng.uniform(5, 180), 2),
            "earnings_brl": round(rng.uniform(40, 600), 2),
            "shift_rating": round(rng.uniform(3, 5), 2),
            "issues_reported": rng.choice(["None", "Late Start", "App Crash"]),
            "available": rng.random() < 0.8,
        }
    if table == "users_mongo":
        n = rng.randrange(10**6)
        return {
            "user_id": n,
            "cpf": _cpf(rng),
            "email": f"user{n}@example.com",
            "phone_number": _phone(rng),
            "city": rng.choice(CITIES),
            "country": "BR",
            "delivery_address": f"Rua Sintética {rng.randint(1, 999)}",
        }
    if table == "users_mssql":
        return {
            "user_id": rng.randrange(10**6),
            "cpf": _cpf(rng),
            "first_name": rng.choice(FIRST),
            "last_name": rng.choice(LAST),
            "phone_number": _phone(rng),
            "birthday": date(
                rng.randint(1960, 2005), rng.randint(1, 12), rng.randint(1, 28)
            ).isoformat(),
            "job": rng.choice(["analyst", "teacher", "nurse", "engineer"]),
            "company_name": "Example Ltda",
            "country": "BR",
        }
    if table == "restaurants":
        return {
            "restaurant_id": rng.randint(2, 10**5),
            "cnpj": _cnpj(rng),
            "name": f"Restaurante {rng.choice(LAST)} {rng.randint(1, 99)}",
            "address": f"Av. Sintética {rng.randint(1, 999)}",
            "city": rng.choice(CITIES),
            "country": "BR",
            "phone_number": _phone(rng),
            "cuisine_type": rng.choice(CUISINES),
            "opening_time": "10:00",
            "closing_time": "23:00",
            "average_rating": round(rng.uniform(3, 5), 2),
            "num_reviews": rng.randint(0, 900),
        }
    if table == "drivers":
        kind, make, model = rng.choice(VEHICLES)
        return {
            "driver_id": f"DRV-{rng.randrange(10**5, 10**6)}",
            "first_name": rng.choice(FIRST),
            "last_name": rng.choice(LAST),
            "phone_number": _phone(rng),
            "city": rng.choice(CITIES),
            "country": "BR",
            "date_birth": date(
                rng.randint(1965, 2004), rng.randint(1, 12), rng.randint(1, 28)
            ).isoformat(),
            "license_number": _digits(rng, 11),
            "vehicle_type": kind,
            "vehicle_make": make,
            "vehicle_model": model,
            "vehicle_year": rng.randint(2008, 2025),
        }
    raise KeyError(table)


def _update_values(table: str, rng: random.Random) -> dict:
    return {
        "orders": lambda: {"total_amount": round(rng.uniform(15, 250), 2)},
        "driver_shifts": lambda: {
            "num_orders": rng.randint(0, 30),
            "available": rng.random() < 0.8,
        },
        "users_mongo": lambda: {"phone_number": _phone(rng), "city": rng.choice(CITIES)},
        "users_mssql": lambda: {"job": rng.choice(["analyst", "teacher", "nurse", "engineer"])},
        "restaurants": lambda: {
            "average_rating": round(rng.uniform(3, 5), 2),
            "num_reviews": rng.randint(0, 900),
        },
        "drivers": lambda: {"vehicle_year": rng.randint(2008, 2025)},
    }[table]()


def plan_burst(seed: int, burst: Burst, earlier: list[str], rows: int) -> list[Op]:
    """Deterministic operations of one burst. ``earlier`` = burst_ids run before it."""
    rng = random.Random(f"{seed}:{burst.burst_id}")
    ops: list[Op] = []
    for table, n in allocate(rows).items():
        updates = n // 2 if table in ENTITY_TABLES and earlier else 0
        inserts = n - updates
        for i in range(inserts):
            ops.append(
                Op(
                    table,
                    "insert",
                    row_key(seed, table, burst.burst_id, i),
                    _insert_values(table, rng, burst.at),
                )
            )
        # Every burst inserts at least n - n//2 rows of each entity table, so any
        # index below that exists in every earlier burst (if that burst ran).
        for _ in range(updates):
            target = rng.choice(earlier)
            i = rng.randrange(n - n // 2)
            ops.append(
                Op(table, "update", row_key(seed, table, target, i), _update_values(table, rng))
            )
    return ops


def plan_window(seed: int, bursts: list[Burst], rows: int) -> dict[str, list[Op]]:
    plans, earlier = {}, []
    for b in bursts:
        plans[b.burst_id] = plan_burst(seed, b, list(earlier), rows)
        earlier.append(b.burst_id)
    return plans


def sql_for(op: Op) -> tuple[str, list]:
    pk = PRIMARY_KEYS[op.table]
    if op.kind == "insert":
        cols = [pk, *op.values]
        marks = ["%s::jsonb" if c == "event" else "%s" for c in cols]
        sql = (
            f"INSERT INTO {op.table} ({', '.join(cols)}) VALUES ({', '.join(marks)}) "
            f"ON CONFLICT ({pk}) DO NOTHING"
        )
        return sql, [op.key, *op.values.values()]
    sets = ", ".join(f"{c} = %s" for c in op.values) + ", dt_current_timestamp = NOW()"
    return f"UPDATE {op.table} SET {sets} WHERE {pk} = %s", [*op.values.values(), op.key]


# ── Time policy ──────────────────────────────────────────────────────────────


def due_action(now: datetime, at: datetime) -> str:
    """'wait' before the burst time, 'run' up to LATE_TOLERANCE after it, 'skip' later."""
    if now < at:
        return "wait"
    return "run" if now - at <= LATE_TOLERANCE else "skip"


# ── Logs (CSV, append-only) ──────────────────────────────────────────────────


class CsvLog:
    def __init__(self, path: Path, header: list[str]):
        self.path, self.header = path, header
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("w", newline="") as f:
                csv.writer(f).writerow(header)

    def rows(self) -> list[dict]:
        with self.path.open(newline="") as f:
            return list(csv.DictReader(f))

    def append(self, row: dict) -> None:
        with self.path.open("a", newline="") as f:
            csv.DictWriter(f, fieldnames=self.header).writerow(row)
            f.flush()
            os.fsync(f.fileno())


COMMITS_HEADER = ["burst_id", "committed_at_utc", "rows", "source"]
SKIPPED_HEADER = ["burst_id", "scheduled_at_utc", "noticed_at_utc", "reason"]
TASKS_HEADER = ["checked_at_utc", "cluster_id", "task", "state", "window_valid"]


# ── Task-state check (Decision 5) ────────────────────────────────────────────


class TaskVisibilityError(RuntimeError):
    """The check role does not see exactly the ten gate tasks: stop, never assume."""


def parse_task_states(rows: list[dict]) -> dict[str, str]:
    states = {
        str(r.get("name") or r.get("NAME")).upper(): str(r.get("state") or r.get("STATE")).lower()
        for r in rows
    }
    states = {k: v for k, v in states.items() if k.endswith("_GATE_TASK")}
    if set(states) != GATE_TASKS:
        missing, extra = sorted(GATE_TASKS - set(states)), sorted(set(states) - GATE_TASKS)
        raise TaskVisibilityError(
            f"saw {len(states)} gate task(s), expected the 10 Tier-1 tasks; missing={missing} "
            f"unexpected={extra}. Check that CDC_ROLE_RO has MONITOR on the tasks "
            f"(terraform/platform ro_tasks_future) and that terraform/pipeline is applied."
        )
    return states


class TaskStateLog:
    """task_states.csv with a cumulative window_valid column."""

    def __init__(self, path: Path):
        self.log = CsvLog(path, TASKS_HEADER)
        previous = self.log.rows()
        self.window_valid = all(r["window_valid"] == "true" for r in previous)

    def record(self, checked_at: datetime, cluster_id: str, states: dict[str, str]) -> list[str]:
        not_started = sorted(t for t, s in states.items() if s != "started")
        if not_started:
            self.window_valid = False
        for task in sorted(states):
            self.log.append(
                {
                    "checked_at_utc": checked_at.isoformat(),
                    "cluster_id": cluster_id,
                    "task": task,
                    "state": states[task],
                    "window_valid": "true" if self.window_valid else "false",
                }
            )
        return not_started


def snowflake_task_rows() -> list[dict]:  # pragma: no cover - needs the account
    """SHOW TASKS as CDC_ROLE_RO, key-pair, no USE WAREHOUSE (metadata only)."""
    import snowflake.connector
    from cryptography.hazmat.primitives import serialization

    with open(os.environ["LOAD_SNOWFLAKE_PRIVATE_KEY_PATH"], "rb") as f:
        key = serialization.load_pem_private_key(
            f.read(),
            password=os.environ.get("LOAD_SNOWFLAKE_PRIVATE_KEY_PASSPHRASE", "").encode() or None,
        )
    der = key.private_bytes(
        serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    )
    conn = snowflake.connector.connect(
        account=os.environ["SNOWFLAKE_ACCOUNT"],
        user=os.environ.get("LOAD_SNOWFLAKE_USER", "CURSOR_MCP_USER"),
        private_key=der,
        role="CDC_ROLE_RO",
    )
    try:
        cur = conn.cursor(snowflake.connector.DictCursor)
        cur.execute("SHOW TASKS LIKE '%_GATE_TASK' IN SCHEMA CDC_POC.BRONZE")
        return cur.fetchall()
    finally:
        conn.close()


# ── Postgres ─────────────────────────────────────────────────────────────────


def postgres_connection():  # pragma: no cover - needs the stack
    import psycopg2

    return psycopg2.connect(
        host=os.getenv("POSTGRES_HOST", "localhost"),
        port=int(os.getenv("POSTGRES_PORT", "5432")),
        dbname=os.environ["POSTGRES_DB"],
        user=os.environ["POSTGRES_USER"],
        password=os.environ["POSTGRES_PASSWORD"],
    )


def run_burst(conn, ops: list[Op]) -> int:
    """One transaction per burst; returns rows actually affected."""
    affected = 0
    try:
        with conn.cursor() as cur:
            for op in ops:
                sql, params = sql_for(op)
                cur.execute(sql, params)
                affected += max(cur.rowcount, 0)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return affected


def committed_at_of(conn, seed: int, burst_id: str) -> datetime | None:
    """Recovery probe: dt_current_timestamp of the burst's first orders insert, if it exists."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT dt_current_timestamp FROM orders WHERE order_id = %s",
            [probe_key(seed, burst_id)],
        )
        row = cur.fetchone()
    conn.rollback()  # read-only; end the implicit transaction
    return row[0].astimezone(UTC) if row else None


# ── The run loop ─────────────────────────────────────────────────────────────


@dataclass
class Summary:
    ran: int = 0
    already_logged: int = 0
    recovered: int = 0
    skipped: int = 0
    underfilled: int = 0
    task_checks: int = 0
    tasks_not_started_checks: int = 0
    window_valid: bool = True

    def text(self) -> str:
        return (
            f"bursts ran={self.ran} already_logged={self.already_logged} "
            f"recovered={self.recovered} skipped={self.skipped} underfilled={self.underfilled} "
            f"| task checks={self.task_checks} with_not_started={self.tasks_not_started_checks} "
            f"window_valid={str(self.window_valid).lower()}"
        )


def run(
    bursts: list[Burst],
    plans: dict[str, list[Op]],
    out: Path,
    *,
    seed: int,
    rows_per_burst: int,
    conn,
    task_rows: Callable[[], list[dict]] | None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    sleep: Callable[[float], None] = time.sleep,
    err=sys.stderr,
) -> Summary:
    summary = Summary()
    commits = CsvLog(out / "commits.csv", COMMITS_HEADER)
    skipped = CsvLog(out / "skipped.csv", SKIPPED_HEADER)
    tasks = TaskStateLog(out / "task_states.csv") if task_rows else None
    logged = {r["burst_id"] for r in commits.rows()}
    summary.already_logged = len(logged & {b.burst_id for b in bursts})

    def check_tasks(cluster_id: str) -> None:
        states = parse_task_states(task_rows())  # raises TaskVisibilityError
        not_started = tasks.record(clock(), cluster_id, states)
        summary.task_checks += 1
        if not_started:
            summary.tasks_not_started_checks += 1
            print(
                f"WARNING {cluster_id}: gate task(s) not started: {', '.join(not_started)} "
                f"— the window is void (DESIGN validity rules)",
                file=err,
            )

    # Recovery: a committed burst whose CSV line was lost (crash between COMMIT and append).
    now = clock()
    for b in bursts:
        if b.burst_id in logged or b.at > now:
            continue
        when = committed_at_of(conn, seed, b.burst_id)
        if when is not None:
            commits.append(
                {
                    "burst_id": b.burst_id,
                    "committed_at_utc": when.isoformat(),
                    "rows": len(plans[b.burst_id]),
                    "source": "recovered",
                }
            )
            logged.add(b.burst_id)
            summary.recovered += 1

    if tasks:
        check_tasks("startup")

    events: list[tuple[datetime, int, object]] = [
        (b.at, 0, b) for b in bursts if b.burst_id not in logged
    ]
    if tasks:  # one check TASK_CHECK_DELAY after each cluster's first burst
        events += [(b.at + TASK_CHECK_DELAY, 1, b.cluster_id) for b in bursts if b.index == 0]
    for at, _, item in sorted(events, key=lambda e: (e[0], e[1])):
        while (now := clock()) < at:
            sleep(min((at - now).total_seconds(), 30))
        if isinstance(item, str):
            check_tasks(item)
            continue
        burst: Burst = item
        if due_action(clock(), burst.at) == "skip":
            skipped.append(
                {
                    "burst_id": burst.burst_id,
                    "scheduled_at_utc": burst.at.isoformat(),
                    "noticed_at_utc": clock().isoformat(),
                    "reason": "late > 60 s",
                }
            )
            summary.skipped += 1
            print(
                f"WARNING {burst.burst_id}: {clock() - burst.at} late — skipped, not run late",
                file=err,
            )
            continue
        affected = run_burst(conn, plans[burst.burst_id])
        committed = clock()
        commits.append(
            {
                "burst_id": burst.burst_id,
                "committed_at_utc": committed.isoformat(),
                "rows": affected,
                "source": "live",
            }
        )
        summary.ran += 1
        if affected < rows_per_burst:
            summary.underfilled += 1
            print(
                f"WARNING {burst.burst_id}: affected {affected} < {rows_per_burst} planned rows "
                f"(updates whose target row does not exist, e.g. its burst was skipped)",
                file=err,
            )
    if tasks:
        summary.window_valid = tasks.window_valid
    return summary


# ── CLI ──────────────────────────────────────────────────────────────────────


def _utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def plan_report(bursts: list[Burst], plans: dict[str, list[Op]], now: datetime) -> str:
    kinds = Counter((op.table, op.kind) for ops in plans.values() for op in ops)
    would_skip = sum(1 for b in bursts if due_action(now, b.at) == "skip")
    lines = [
        f"clusters={len({b.cluster_id for b in bursts})} bursts={len(bursts)} "
        f"rows={sum(len(o) for o in plans.values())}",
        f"would skip {would_skip} burst(s) already more than "
        f"{int(LATE_TOLERANCE.total_seconds())} s "
        f"in the past at {now.isoformat()}",
    ]
    for table in TABLE_WEIGHTS:
        lines.append(
            f"  {table:16} insert={kinds[(table, 'insert')]:6} update={kinds[(table, 'update')]:6}"
        )
    if bursts:
        lines.append(f"first={bursts[0].at.isoformat()} last={bursts[-1].at.isoformat()}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--window", required=True, help="label, e.g. dry-run, A, B")
    p.add_argument("--start", required=True, type=_utc)
    p.add_argument("--end", required=True, type=_utc)
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--plan-only", action="store_true", help="print the plan; touch no database")
    p.add_argument(
        "--no-task-check", action="store_true", help="local testing only; voids validity"
    )
    args = p.parse_args(argv)

    seed = int(os.getenv("LOAD_SEED", "42"))
    cluster_minutes = int(os.getenv("LOAD_CLUSTER_MINUTES", "120"))
    offsets = [int(x) for x in os.getenv("LOAD_BURST_OFFSETS", "0,2,4,10,12").split(",")]
    rows = int(os.getenv("LOAD_ROWS_PER_BURST", "200"))

    bursts = schedule(args.start, args.end, cluster_minutes, offsets)
    plans = plan_window(seed, bursts, rows)
    print(
        f"window={args.window} seed={seed} cluster_minutes={cluster_minutes} "
        f"offsets={offsets} rows={rows}"
    )
    print(plan_report(bursts, plans, datetime.now(UTC)))
    if args.plan_only:
        return 0

    conn = postgres_connection()
    try:
        summary = run(
            bursts,
            plans,
            args.out,
            seed=seed,
            rows_per_burst=rows,
            conn=conn,
            task_rows=None if args.no_task_check else snowflake_task_rows,
        )
    except TaskVisibilityError as exc:
        print(f"ERROR task-state check: {exc}", file=sys.stderr)
        return 3
    finally:
        conn.close()
    print(f"SUMMARY window={args.window} {summary.text()}")
    return 0 if summary.window_valid and not summary.skipped else 1


if __name__ == "__main__":
    sys.exit(main())
