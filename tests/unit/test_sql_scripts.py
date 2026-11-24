"""Static guards for the CI SQL steps (COST_GOVERNANCE items 5-6, DESIGN 1.2).

seed_config.sql, account_monitor.sql and budget.sql run on every push to
`main` (Decision 11), so they must be idempotent, never destructive, never touch
CDC_WH, and agree with the names terraform/platform creates. Runs without
Snowflake.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
PLATFORM = ROOT / "terraform" / "platform"

CI_SCRIPTS = ["seed_config.sql", "account_monitor.sql", "budget.sql", "verify_governance.sql"]

# DESIGN Pattern 3 / ADR-0022: the ten Tier-1 domains.
TIER1 = {
    "orders",
    "order_items",
    "drivers",
    "driver_shifts",
    "restaurants",
    "users_mongo",
    "users_mssql",
    "payment_events",
    "recommendations",
    "search_events",
}


def _sql(name: str) -> str:
    """Script text without -- comments."""
    return re.sub(r"--[^\n]*", "", (SCRIPTS / name).read_text())


def _tf() -> str:
    return "\n".join(p.read_text() for p in sorted(PLATFORM.glob("*.tf")))


def _tf_default(variable: str) -> str:
    match = re.search(rf'variable "{variable}" \{{[^}}]*?default\s*=\s*"([^"]+)"', _tf(), re.S)
    assert match, variable
    return match.group(1)


def test_bootstrap_config_was_renamed():
    assert not (SCRIPTS / "bootstrap_config.sql").exists()


@pytest.mark.parametrize("name", CI_SCRIPTS)
def test_never_destructive(name):
    sql = _sql(name).upper()
    for pattern in [
        r"\bDROP\b",
        r"\bTRUNCATE\b",
        r"\bDELETE\b",
        r"CREATE\s+OR\s+REPLACE",
        r"\bUPDATE\s+\w",
        r"\bRESUME\b",
    ]:
        assert not re.search(pattern, sql), f"{name}: {pattern}"


@pytest.mark.parametrize("name", CI_SCRIPTS)
def test_never_uses_the_pipeline_warehouse(name):
    warehouses = re.findall(r"USE\s+WAREHOUSE\s+(\w+)", _sql(name), re.I)
    assert all(w.upper() == _tf_default("ci_warehouse_name") for w in warehouses), warehouses


@pytest.mark.parametrize("name", CI_SCRIPTS)
def test_no_email_address_in_the_repo(name):
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", (SCRIPTS / name).read_text())


@pytest.mark.parametrize("name", CI_SCRIPTS)
def test_no_legacy_snowsql_variables(name):
    # Snowflake CLI also substitutes &var / &{var}: a stray & would be templated.
    assert "&" not in _sql(name)


def test_only_account_monitor_uses_accountadmin():
    for name in CI_SCRIPTS:
        uses = bool(re.search(r"USE\s+ROLE\s+ACCOUNTADMIN", _sql(name), re.I))
        assert uses == (name == "account_monitor.sql"), name


def test_account_monitor_matches_terraform():
    monitor = re.search(
        r'resource "snowflake_resource_monitor" "account" \{[^}]*name\s*=\s*"(\w+)"', _tf(), re.S
    ).group(1)
    assert re.search(
        rf"ALTER\s+ACCOUNT\s+SET\s+RESOURCE_MONITOR\s*=\s*{monitor}\s*;",
        _sql("account_monitor.sql"),
    )


def test_seed_is_insert_only_and_covers_tier1():
    sql = _sql("seed_config.sql")
    assert "WHEN NOT MATCHED THEN INSERT" in sql
    assert "WHEN MATCHED" not in sql
    seeded = set(re.findall(r"\(\s*'(\w+)',\s*'pg\.public\.\1'", sql))
    assert seeded == TIER1


def test_budget_role_and_names_match_terraform():
    sql = _sql("budget.sql")
    assert f"USE ROLE {_tf_default('budget_role_name')};" in sql
    assert "SP_SUSPEND_GATE_TASKS" in _tf()
    assert "CDC_POC.CONFIG.SP_SUSPEND_GATE_TASKS()" in sql
    assert _tf_default("database_name") == "CDC_POC"


def test_budget_is_idempotent_and_matches_design():
    sql = _sql("budget.sql")
    assert "CREATE SNOWFLAKE.CORE.BUDGET IF NOT EXISTS" in sql
    assert sql.index("REMOVE_CUSTOM_ACTIONS()") < sql.index("ADD_CUSTOM_ACTION(")
    assert re.search(r"'ACTUAL',\s*100\)", sql)  # Decision 5
    assert "SET_SPENDING_LIMIT(5)" in sql  # Decision 8 (DESIGN 1.5)
    assert "SET_REFRESH_TIER('TIER_1H')" in sql  # F8, owner decision
    assert "REMOVE_CYCLE_START_ACTION()" in sql  # no cycle-start action
    assert "SET_CYCLE_START_ACTION" not in sql
    assert "GET_BUDGET_SCOPE" in sql and "ADD_RESOURCE" in sql  # add only if missing


def test_budget_email_comes_only_from_the_cli_variable():
    sql = _sql("budget.sql")
    assert re.findall(r"<%\s*(\w+)\s*%>", sql) == ["notify_email"]
    assert "SET_EMAIL_NOTIFICATIONS('<% notify_email %>')" in sql


def test_snowflake_application_grants_precede_the_action():
    sql = _sql("budget.sql")
    grant = sql.index("GRANT USAGE ON PROCEDURE CDC_POC.CONFIG.SP_SUSPEND_GATE_TASKS()")
    assert grant < sql.index("ADD_CUSTOM_ACTION(")
    assert "TO APPLICATION SNOWFLAKE" in sql[grant : grant + 200]


def test_verify_runs_read_only_as_the_plan_role():
    sql = _sql("verify_governance.sql")
    assert re.findall(r"USE\s+ROLE\s+(\w+)", sql, re.I) == [_tf_default("plan_role_name")]
    assert set(re.findall(r"<%\s*(\w+)\s*%>", sql)) == {
        "cost_profile",
        "gate_task_timeout_ms",
        "check_pipeline",
    }
    for statement in ["GRANT", "ALTER", "CREATE", "INSERT", "MERGE", "CALL CDC_POC.CONFIG.SP_"]:
        assert statement not in sql.upper().replace("CALL CDC_POC.CONFIG.CDC_BUDGET!", ""), (
            statement
        )


def test_verify_raises_on_every_acceptance_check():
    sql = _sql("verify_governance.sql")
    for code in ["-20002", "-20003", "-20004", "-20005"]:
        assert f"EXCEPTION ({code}," in sql, code
    assert sql.count("RAISE ") >= 5
    # B4: AT-002 in the F6 read-back format.
    assert "\"resource_constraint\" = 'STANDARD_GEN_' || :gen" in sql
    assert 'TO_VARCHAR("generation") = :gen' in sql


def test_budget_grants_viewer_to_the_plan_role():
    assert (
        "GRANT SNOWFLAKE.CORE.BUDGET ROLE CDC_POC.CONFIG.CDC_BUDGET!VIEWER"
        " TO ROLE TERRAFORM_PLAN_ROLE;"
        in _sql("budget.sql")
    )
