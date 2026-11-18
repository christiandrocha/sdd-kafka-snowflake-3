"""Static guards for terraform/pipeline (COST_GOVERNANCE item 7, DESIGN 1.2).

Covers Build checklist B1 (both roots share one cost profile), the
"platform before pipeline" prerequisites of the gate tasks (Decision 1), and
Pattern 3 / Decision 5 as built. Runs without Snowflake or Terraform.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from tfparse import blocks, provider_alias

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "terraform" / "platform"
PIPELINE = ROOT / "terraform" / "pipeline"
DEV_TFVARS = ROOT / "terraform" / "env" / "dev.tfvars"

RESOURCES = blocks(PIPELINE, "resource")
PLATFORM_RESOURCES = blocks(PLATFORM, "resource")

TIER1 = {
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
}


def _variable_default_list(name: str) -> set[str]:
    body = blocks(PIPELINE, "variable")[name]
    return set(re.findall(r'"([A-Z_]+)"', body.split("default", 1)[1]))


# --- B1: one cost profile for both roots --------------------------------------


def test_profiles_tf_is_identical_in_both_roots():
    assert (PLATFORM / "profiles.tf").read_text() == (PIPELINE / "profiles.tf").read_text()


def test_both_roots_pin_the_same_provider_range():
    assert (PLATFORM / "versions.tf").read_text() == (PIPELINE / "versions.tf").read_text()


def test_pipeline_has_its_own_state_key():
    backend = (PIPELINE / "backend.tf").read_text()
    assert 'key          = "sdd-kafka-snowflake-3/pipeline.tfstate"' in backend
    assert "use_lockfile = true" in backend


# --- Aliases -------------------------------------------------------------------


def test_pipeline_defines_only_the_sysadmin_alias():
    providers = blocks(PIPELINE, "provider")
    assert set(providers) == {"sysadmin"}
    assert 'coalesce(var.plan_role, "SYSADMIN")' in providers["sysadmin"]


@pytest.mark.parametrize("address", sorted(RESOURCES))
def test_every_pipeline_resource_uses_sysadmin(address):
    assert provider_alias(RESOURCES[address]) == "sysadmin", address


# --- Prerequisites live in platform, applied first (Decision 1) ---------------


def _platform_grant_to_sysadmin(predicate) -> list[str]:
    return [
        address
        for address, body in PLATFORM_RESOURCES.items()
        if address.startswith("snowflake_grant_privileges_to_account_role.")
        and re.search(r'account_role_name\s*=\s*"SYSADMIN"', body)
        and predicate(body)
    ]


def test_sysadmin_usage_on_cdc_wh_is_granted_by_platform_before_the_tasks():
    # Profile baseline runs the gate tasks on CDC_WH, owned by ACCOUNTADMIN (F14):
    # SYSADMIN (task owner) needs USAGE on it, from the root applied first.
    found = _platform_grant_to_sysadmin(
        lambda b: (
            '"USAGE"' in b
            and re.search(r'object_type\s*=\s*"WAREHOUSE"', b)
            and "snowflake_warehouse.cdc.name" in b
        )
    )
    assert found == ["snowflake_grant_privileges_to_account_role.sysadmin_cdc_wh"]
    task = RESOURCES["snowflake_task.gate"]
    assert "var.warehouse_name" in task  # the baseline tasks do use that warehouse
    assert not any(
        a.startswith("snowflake_grant") and "WAREHOUSE" in b for a, b in RESOURCES.items()
    )


def test_execute_task_privileges_are_granted_by_platform():
    found = _platform_grant_to_sysadmin(
        lambda b: (
            re.search(r"on_account\s*=\s*true", b)
            and '"EXECUTE TASK"' in b
            and '"EXECUTE MANAGED TASK"' in b
        )
    )
    assert found == ["snowflake_grant_privileges_to_account_role.sysadmin_execute_task"]
    # Hypothesis to validate on Day 3: SECURITYADMIN can grant them (BUILD_REPORT run 3).
    assert provider_alias(PLATFORM_RESOURCES[found[0]]) == "securityadmin"


# --- Pattern 3 / Decision 5 as built --------------------------------------------


def test_gate_domains_are_the_tier1_ten():
    assert _variable_default_list("gate_domains") == TIER1


def test_streams_are_append_only_over_connector_tables():
    body = RESOURCES["snowflake_stream_on_table.bronze"]
    assert re.search(r'append_only\s*=\s*"true"', body)
    assert 'name        = "${each.key}_STREAM"' in body
    assert '"BRONZE"' in body and "each.key" in body


def test_tasks_switch_compute_with_the_profile():
    body = RESOURCES["snowflake_task.gate"]
    assert 'local.profile.task_compute == "serverless"' in (PIPELINE / "gate.tf").read_text()
    for line in [
        "warehouse                                = local.serverless ? null : var.warehouse_name",
        'user_task_managed_initial_warehouse_size = local.serverless ? "XSMALL" : null',
        'serverless_task_max_statement_size       = local.serverless ? "XSMALL" : null',
        "user_task_timeout_ms                     = local.serverless"
        " ? var.gate_task_timeout_ms : null",
        "suspend_task_after_num_failures          = local.serverless ? 3 : null",
    ]:
        assert line in body, line
    assert re.search(r"started\s*=\s*true", body)
    assert re.search(r"minutes\s*=\s*1\b", body)
    assert "SYSTEM$STREAM_HAS_DATA(" in body
    assert "CONFIG.SP_GATE_DOMAIN(" in body


def test_gate_task_timeout_is_a_variable_with_the_provisional_default():
    body = blocks(PIPELINE, "variable")["gate_task_timeout_ms"]
    assert re.search(r"default\s*=\s*10000\b", body)
    assert "PROVISIONAL" in body


def test_every_gate_task_is_visible_to_the_plan_role():
    body = RESOURCES["snowflake_grant_privileges_to_account_role.plan_task_monitor"]
    assert "for_each          = snowflake_task.gate" in body
    assert '"MONITOR"' in body and 'object_type = "TASK"' in body
    future = PLATFORM_RESOURCES["snowflake_grant_privileges_to_account_role.plan_tasks_future"]
    assert '"MONITOR"' in future and '"TASKS"' in future


def test_gate_procedure_keeps_adr_0019_semantics():
    body = RESOURCES["snowflake_procedure_sql.gate_domain"]
    assert re.search(r'execute_as\s*=\s*"OWNER"', body)
    assert "CONFIG.PENDING_RUNS" in body
    assert "CONFIG.STREAM_CONSUMPTION_LOG" in body
    assert "FROM ' || :STREAM_FQN" in body  # DML over the stream advances its offset


def test_old_scripts_are_gone():
    for name in [
        "streams_and_tasks.sql",
        "snowflake_setup.sql",
        "00_account_bootstrap.sql",
        "create_readonly_role.sql",
    ]:
        assert not (ROOT / "scripts" / name).exists(), name
