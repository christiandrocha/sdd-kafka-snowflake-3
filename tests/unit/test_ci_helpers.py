"""Unit tests for .github/scripts (COST_GOVERNANCE item 16)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))

import bronze_ready  # noqa: E402
import plan_summary  # noqa: E402


def _rc(address, *actions):
    return {"address": address, "change": {"actions": list(actions)}}


# --- plan_summary ---------------------------------------------------------------


def test_summarize_keeps_only_changes_and_drops_values():
    plan = {
        "resource_changes": [
            _rc("snowflake_warehouse.cdc", "update"),
            _rc("snowflake_database.cdc", "no-op"),
            _rc("data.x.y", "read"),
            _rc('snowflake_task.gate["ORDERS"]', "delete", "create"),
        ]
    }
    assert plan_summary.summarize(plan) == [
        {"address": 'snowflake_task.gate["ORDERS"]', "actions": ["delete", "create"]},
        {"address": "snowflake_warehouse.cdc", "actions": ["update"]},
    ]


def test_summarize_empty_plan():
    assert plan_summary.summarize({}) == []


def test_compare_equal_plans_has_no_diff():
    a = [{"address": "x", "actions": ["update"]}]
    assert plan_summary.compare(a, list(a)) == []


def test_compare_reports_every_kind_of_divergence():
    pr = [{"address": "a", "actions": ["update"]}, {"address": "b", "actions": ["create"]}]
    main = [
        {"address": "a", "actions": ["delete", "create"]},
        {"address": "c", "actions": ["update"]},
    ]
    diffs = plan_summary.compare(pr, main)
    assert len(diffs) == 3
    assert any("different actions for a" in d for d in diffs)
    assert any("only in the PR plan: b" in d for d in diffs)
    assert any("only in the apply re-plan: c" in d for d in diffs)


def test_compare_cli_never_fails_even_when_plans_diverge(tmp_path):
    pr, main = tmp_path / "pr.json", tmp_path / "main.json"
    pr.write_text(json.dumps([{"address": "a", "actions": ["update"]}]))
    main.write_text(json.dumps([]))
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "plan_summary.py"), "compare", str(pr), str(main)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert out.returncode == 0  # warn, never block (owner decision)
    assert "only in the PR plan: a" in out.stdout


def test_summarize_cli_reads_terraform_show_json():
    plan = {"resource_changes": [_rc("r.x", "create")]}
    out = subprocess.run(
        [sys.executable, str(SCRIPTS / "plan_summary.py"), "summarize"],
        input=json.dumps(plan),
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(out.stdout) == [{"address": "r.x", "actions": ["create"]}]


# --- bronze_ready -----------------------------------------------------------------

TEN = [
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
]


def test_ready_when_all_tables_exist_in_any_nesting():
    output = [[{"name": t, "kind": "TABLE"} for t in TEN[:5]], [{"NAME": t} for t in TEN[5:]]]
    assert bronze_ready.missing(output, TEN) == []


def test_missing_lists_absent_tables_sorted():
    output = [{"name": "ORDERS"}, {"name": "drivers"}]
    assert bronze_ready.missing(output, ["ORDERS", "DRIVERS", "RESTAURANTS", "ORDER_ITEMS"]) == [
        "ORDER_ITEMS",
        "RESTAURANTS",
    ]


def test_empty_schema_means_all_missing():
    assert bronze_ready.missing([], TEN) == sorted(TEN)


def test_cli_prints_ready_or_missing_and_rejects_garbage():
    def run(stdin, *tables):
        return subprocess.run(
            [sys.executable, str(SCRIPTS / "bronze_ready.py"), *tables],
            input=stdin,
            capture_output=True,
            text=True,
            check=False,
        )

    ok = run(json.dumps([{"name": "ORDERS"}]), "ORDERS")
    assert (ok.returncode, ok.stdout.strip()) == (0, "ready")
    miss = run("[]", "ORDERS")
    assert (miss.returncode, miss.stdout.strip()) == (0, "missing: ORDERS")
    assert run("not json", "ORDERS").returncode == 2
