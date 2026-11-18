"""tests/unit/test_generate_load.py — AT-007 and the generator's failure behaviour.

No Postgres, no Snowflake: the run loop gets a fake DB-API connection, a fake
clock and a fake SHOW TASKS. COST_GOVERNANCE item 14 (DESIGN 1.4).
"""

from __future__ import annotations

import importlib.util
import io
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "generate_load", ROOT / "tests" / "load" / "generate_load.py"
)
gl = importlib.util.module_from_spec(_spec)
sys.modules["generate_load"] = gl
_spec.loader.exec_module(gl)

A_START = datetime(2026, 11, 25, 0, 0, tzinfo=UTC)
A_END = datetime(2026, 11, 27, 0, 0, tzinfo=UTC)


def window(start=A_START, end=A_END, seed=42, rows=200):
    bursts = gl.schedule(start, end)
    return bursts, gl.plan_window(seed, bursts, rows)


# ── Schedule ──────────────────────────────────────────────────────────────────


def test_window_a_has_24_clusters_of_5_bursts_at_30_past_even_hours():
    bursts = gl.schedule(A_START, A_END)
    assert len(bursts) == 24 * 5
    starts = sorted({b.at for b in bursts if b.index == 0})
    assert starts[0] == datetime(2026, 11, 25, 0, 30, tzinfo=UTC)
    assert all(s.minute == 30 and s.hour % 2 == 0 for s in starts)
    offsets = [int((b.at - starts[0]).total_seconds() // 60) for b in bursts[:5]]
    assert offsets == [0, 2, 4, 10, 12]


def test_no_cluster_crosses_a_utc_day_boundary():
    for b in gl.schedule(A_START, A_END):
        first = b.at - timedelta(minutes=[0, 2, 4, 10, 12][b.index])
        assert b.at.date() == first.date()


def test_schedule_rejects_bursts_outside_their_cluster():
    with pytest.raises(ValueError):
        gl.schedule(A_START, A_END, cluster_minutes=120, offsets=[0, 95])


def test_allocate_sums_to_the_burst_size():
    for rows in (1, 7, 199, 200, 201, 1000):
        assert sum(gl.allocate(rows).values()) == rows
    assert gl.allocate(200) == gl.TABLE_WEIGHTS


# ── AT-007: same seed, same load ─────────────────────────────────────────────


def test_same_seed_gives_identical_schedule_and_operations():
    b1, p1 = window()
    b2, p2 = window()
    assert b1 == b2
    assert p1 == p2  # every table, kind, key and value


def test_different_seed_same_schedule_different_operations():
    b1, p1 = window(seed=42)
    b2, p2 = window(seed=43)
    assert b1 == b2
    assert p1 != p2
    assert [len(p1[k]) for k in p1] == [len(p2[k]) for k in p2]


def test_every_burst_plans_exactly_rows_per_burst():
    _, plans = window()
    assert {len(ops) for ops in plans.values()} == {200}


def test_restart_reproduces_a_burst_without_history():
    bursts, plans = window()
    b = bursts[7]
    earlier = [x.burst_id for x in bursts[:7]]
    assert gl.plan_burst(42, b, earlier, 200) == plans[b.burst_id]


def test_facts_are_insert_only_and_updates_target_earlier_bursts():
    bursts, plans = window()
    inserted = {}
    for b in bursts:
        for op in plans[b.burst_id]:
            if op.kind == "update":
                assert op.table in gl.ENTITY_TABLES
                assert op.key in inserted, "update targets a row no earlier burst inserted"
        for op in plans[b.burst_id]:
            if op.kind == "insert":
                inserted[op.key] = b.burst_id
    first = plans[bursts[0].burst_id]
    assert all(op.kind == "insert" for op in first)


def test_probe_key_is_the_first_orders_insert_of_every_burst():
    bursts, plans = window()
    for b in bursts:
        orders = [op for op in plans[b.burst_id] if op.table == "orders" and op.kind == "insert"]
        assert orders[0].key == gl.probe_key(42, b.burst_id)


def test_data_is_synthetic():
    _, plans = window(end=A_START + timedelta(hours=6))
    for ops in plans.values():
        for op in ops:
            for value in op.values.values():
                if isinstance(value, str) and "@" in value:
                    assert value.endswith("@example.com")
            if "cpf" in op.values:
                assert re.fullmatch(r"\d{3}\.\d{3}\.\d{3}-\d{2}", op.values["cpf"])


def test_sql_is_parameterised_and_inserts_never_overwrite():
    _, plans = window(end=A_START + timedelta(hours=3))
    for ops in plans.values():
        for op in ops:
            sql, params = gl.sql_for(op)
            assert sql.count("%s") == len(params)
            if op.kind == "insert":
                assert "ON CONFLICT" in sql and "DO NOTHING" in sql
            else:
                assert (
                    sql.startswith(f"UPDATE {op.table} SET")
                    and "dt_current_timestamp = NOW()" in sql
                )


# ── Time policy ──────────────────────────────────────────────────────────────


def test_due_action_waits_runs_or_skips():
    at = A_START + timedelta(minutes=30)
    assert gl.due_action(at - timedelta(seconds=1), at) == "wait"
    assert gl.due_action(at + timedelta(seconds=60), at) == "run"
    assert gl.due_action(at + timedelta(seconds=61), at) == "skip"


def test_plan_report_counts_bursts_that_would_be_skipped():
    bursts, plans = window(end=A_START + timedelta(hours=4))  # 2 clusters, 10 bursts
    # 02:33:30: all 5 bursts of the 00:30 cluster, plus 02:30 (210 s) and 02:32 (90 s)
    # are more than 60 s in the past; 02:34 and later are still ahead.
    now = datetime(2026, 11, 25, 2, 33, 30, tzinfo=UTC)
    report = gl.plan_report(bursts, plans, now)
    assert "would skip 7 burst(s)" in report


# ── Task-state check ─────────────────────────────────────────────────────────


def ten(state="started", **overrides):
    rows = [{"name": t, "state": state} for t in sorted(gl.GATE_TASKS)]
    for r in rows:
        if r["name"] in overrides:
            r["state"] = overrides[r["name"]]
    return rows


def test_task_check_accepts_exactly_the_ten():
    assert gl.parse_task_states(ten()) == {t: "started" for t in gl.GATE_TASKS}


@pytest.mark.parametrize(
    "rows",
    [[], ten()[:9], ten() + [{"name": "EXTRA_GATE_TASK", "state": "started"}]],
    ids=["empty", "nine", "eleven"],
)
def test_task_check_fails_instead_of_returning_empty(rows):
    with pytest.raises(gl.TaskVisibilityError):
        gl.parse_task_states(rows)


def test_window_valid_turns_false_and_stays_false(tmp_path):
    log = gl.TaskStateLog(tmp_path / "task_states.csv")
    t = A_START
    assert log.record(t, "c1", gl.parse_task_states(ten())) == []
    assert log.record(t, "c2", gl.parse_task_states(ten(ORDERS_GATE_TASK="suspended"))) == [
        "ORDERS_GATE_TASK"
    ]
    log.record(t, "c3", gl.parse_task_states(ten()))
    rows = log.log.rows()
    by_cluster = {
        c: {r["window_valid"] for r in rows if r["cluster_id"] == c} for c in ("c1", "c2", "c3")
    }
    assert by_cluster == {"c1": {"true"}, "c2": {"false"}, "c3": {"false"}}
    assert gl.TaskStateLog(tmp_path / "task_states.csv").window_valid is False  # survives restart


# ── The run loop with fakes ──────────────────────────────────────────────────


class FakeCursor:
    def __init__(self, conn):
        self.conn, self.rowcount, self._fetch = conn, 0, None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, sql, params):
        self.conn.statements.append((sql, params))
        if sql.startswith("SELECT dt_current_timestamp FROM orders"):
            self._fetch = self.conn.committed_probe.get(params[0])
            self.rowcount = 1 if self._fetch else 0
            return
        if self.conn.fail_on and self.conn.fail_on in sql:
            raise RuntimeError("db down")
        self.rowcount = self.conn.rowcount_for(sql)

    def fetchone(self):
        return (self._fetch,) if self._fetch else None


class FakeConn:
    def __init__(self, rowcount_for=lambda sql: 1, committed_probe=None, fail_on=None):
        self.statements, self.commits, self.rollbacks = [], 0, 0
        self.rowcount_for, self.committed_probe, self.fail_on = (
            rowcount_for,
            committed_probe or {},
            fail_on,
        )

    def cursor(self):
        return FakeCursor(self)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1


class Clock:
    """Fake time: sleep advances it; each read can be shifted by `lag` to simulate slowness."""

    def __init__(self, now):
        self.now = now

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += timedelta(seconds=seconds)


def one_cluster():
    bursts, plans = window(end=A_START + timedelta(hours=1))  # cluster 00:30, 5 bursts
    assert len(bursts) == 5
    return bursts, plans


def test_run_executes_each_burst_in_one_transaction_and_logs_commit_time(tmp_path):
    bursts, plans = one_cluster()
    conn, clock, err = FakeConn(), Clock(A_START), io.StringIO()
    summary = gl.run(
        bursts,
        plans,
        tmp_path,
        seed=42,
        rows_per_burst=200,
        conn=conn,
        task_rows=ten,
        clock=clock,
        sleep=clock.sleep,
        err=err,
    )
    assert summary.ran == 5 and summary.skipped == 0 and summary.window_valid
    assert conn.commits == 5
    rows = gl.CsvLog(tmp_path / "commits.csv", gl.COMMITS_HEADER).rows()
    assert [r["burst_id"] for r in rows] == [b.burst_id for b in bursts]
    assert all(r["source"] == "live" and r["rows"] == "200" for r in rows)
    assert all(gl._utc(r["committed_at_utc"]) >= b.at for r, b in zip(rows, bursts, strict=True))
    assert summary.task_checks == 2  # start-up + 20 min after the cluster


def test_update_that_affects_zero_rows_warns_and_logs_the_real_count(tmp_path):
    bursts, plans = one_cluster()
    conn = FakeConn(rowcount_for=lambda sql: 0 if sql.startswith("UPDATE") else 1)
    clock, err = Clock(A_START), io.StringIO()
    summary = gl.run(
        bursts,
        plans,
        tmp_path,
        seed=42,
        rows_per_burst=200,
        conn=conn,
        task_rows=ten,
        clock=clock,
        sleep=clock.sleep,
        err=err,
    )
    rows = gl.CsvLog(tmp_path / "commits.csv", gl.COMMITS_HEADER).rows()
    updates = {b.burst_id: sum(op.kind == "update" for op in plans[b.burst_id]) for b in bursts}
    assert [int(r["rows"]) for r in rows] == [200 - updates[b.burst_id] for b in bursts]
    assert summary.underfilled == sum(1 for n in updates.values() if n) == 4  # burst 0 has none
    assert err.getvalue().count("< 200 planned rows") == 4


def test_late_bursts_are_skipped_not_run_late_and_counted(tmp_path):
    bursts, plans = one_cluster()
    conn, err = FakeConn(), io.StringIO()
    # Woke up at 00:35:30: b0 (00:30), b1 (00:32) and b2 (00:34, 90 s) are > 60 s late.
    clock = Clock(datetime(2026, 11, 25, 0, 35, 30, tzinfo=UTC))
    summary = gl.run(
        bursts,
        plans,
        tmp_path,
        seed=42,
        rows_per_burst=200,
        conn=conn,
        task_rows=ten,
        clock=clock,
        sleep=clock.sleep,
        err=err,
    )
    assert summary.skipped == 3 and summary.ran == 2
    skipped = gl.CsvLog(tmp_path / "skipped.csv", gl.SKIPPED_HEADER).rows()
    assert [r["burst_id"] for r in skipped] == [b.burst_id for b in bursts[:3]]
    assert "skipped=3" in summary.text()


def test_resume_after_crash_between_commit_and_csv_recovers_without_rerunning(tmp_path):
    """Burst b1 committed in Postgres, the process died before its CSV line."""
    bursts, plans = one_cluster()
    log = gl.CsvLog(tmp_path / "commits.csv", gl.COMMITS_HEADER)
    log.append(
        {
            "burst_id": bursts[0].burst_id,
            "committed_at_utc": bursts[0].at.isoformat(),
            "rows": 200,
            "source": "live",
        }
    )
    pg_now = bursts[1].at + timedelta(milliseconds=40)
    conn = FakeConn(committed_probe={gl.probe_key(42, bursts[1].burst_id): pg_now})
    clock = Clock(bursts[1].at + timedelta(seconds=30))  # restarted 30 s after b1
    summary = gl.run(
        bursts,
        plans,
        tmp_path,
        seed=42,
        rows_per_burst=200,
        conn=conn,
        task_rows=ten,
        clock=clock,
        sleep=clock.sleep,
        err=io.StringIO(),
    )
    rows = log.rows()
    assert [r["burst_id"] for r in rows] == [b.burst_id for b in bursts]
    assert rows[1]["source"] == "recovered" and gl._utc(rows[1]["committed_at_utc"]) == pg_now
    assert summary.already_logged == 1 and summary.recovered == 1 and summary.ran == 3
    executed = [s for s, _ in conn.statements if not s.startswith("SELECT")]
    assert len(executed) == 3 * 200  # b1 was never re-executed


def test_resume_runs_a_burst_that_never_committed(tmp_path):
    bursts, plans = one_cluster()
    conn = FakeConn()  # the probe finds nothing: b0 never committed
    clock = Clock(bursts[0].at + timedelta(seconds=20))
    summary = gl.run(
        bursts,
        plans,
        tmp_path,
        seed=42,
        rows_per_burst=200,
        conn=conn,
        task_rows=ten,
        clock=clock,
        sleep=clock.sleep,
        err=io.StringIO(),
    )
    assert summary.recovered == 0 and summary.ran == 5


def test_failed_burst_rolls_back_and_writes_no_csv_line(tmp_path):
    bursts, plans = one_cluster()
    conn = FakeConn(fail_on="INSERT INTO orders")
    clock = Clock(A_START)
    with pytest.raises(RuntimeError):
        gl.run(
            bursts,
            plans,
            tmp_path,
            seed=42,
            rows_per_burst=200,
            conn=conn,
            task_rows=ten,
            clock=clock,
            sleep=clock.sleep,
            err=io.StringIO(),
        )
    assert conn.rollbacks >= 1 and conn.commits == 0
    assert gl.CsvLog(tmp_path / "commits.csv", gl.COMMITS_HEADER).rows() == []


def test_generator_stops_if_it_cannot_see_the_ten_tasks(tmp_path):
    bursts, plans = one_cluster()
    clock = Clock(A_START)
    with pytest.raises(gl.TaskVisibilityError):
        gl.run(
            bursts,
            plans,
            tmp_path,
            seed=42,
            rows_per_burst=200,
            conn=FakeConn(),
            task_rows=lambda: [],
            clock=clock,
            sleep=clock.sleep,
            err=io.StringIO(),
        )
    assert (
        gl.CsvLog(tmp_path / "commits.csv", gl.COMMITS_HEADER).rows() == []
    )  # stopped at start-up


def test_task_not_started_warns_continues_and_voids_the_window(tmp_path):
    bursts, plans = one_cluster()
    calls = iter([ten(), ten(SEARCH_EVENTS_GATE_TASK="suspended")])
    clock, err = Clock(A_START), io.StringIO()
    summary = gl.run(
        bursts,
        plans,
        tmp_path,
        seed=42,
        rows_per_burst=200,
        conn=FakeConn(),
        task_rows=lambda: next(calls),
        clock=clock,
        sleep=clock.sleep,
        err=err,
    )
    assert summary.ran == 5 and summary.window_valid is False
    assert "SEARCH_EVENTS_GATE_TASK" in err.getvalue() and "window_valid=false" in summary.text()


def test_cli_plan_only_touches_no_database(capsys, monkeypatch):
    def boom():
        raise AssertionError("plan-only must not connect")

    monkeypatch.setattr(gl, "postgres_connection", boom)
    monkeypatch.setattr(gl, "snowflake_task_rows", boom)
    assert (
        gl.main(
            [
                "--window",
                "dry-run",
                "--start",
                "2026-11-24T12:00Z",
                "--end",
                "2026-11-24T18:00Z",
                "--out",
                "/nonexistent",
                "--plan-only",
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert "clusters=3 bursts=15 rows=3000" in out and "would skip" in out
