"""Static guards for terraform/platform (DESIGN_COST_GOVERNANCE 1.1).

These checks run without Snowflake, AWS or the Terraform binary. They turn two
review conditions into tests:

* Decision 9 named exception: the ``snowflake.accountadmin`` alias is used only
  by the resources listed there, and every resource names its alias explicitly.
* Decisions 9/11: every alias falls back to ``var.plan_role`` so a PR plan never
  runs with ACCOUNTADMIN.

Plus a few invariants the A/B depends on (Decisions 2 and 4, F6).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PLATFORM = ROOT / "terraform" / "platform"
DEV_TFVARS = ROOT / "terraform" / "env" / "dev.tfvars"

# Decision 9, "Named exception — the accountadmin provider alias".
ACCOUNTADMIN_ALLOWED = {
    "snowflake_resource_monitor.cdc_wh",
    "snowflake_resource_monitor.account",
    "snowflake_warehouse.cdc",
    "snowflake_grant_privileges_to_account_role.plan_monitors",
    "snowflake_grant_database_role.governance",
    "snowflake_grant_database_role.budget_creator",
}

ALIASES = {"sysadmin", "securityadmin", "accountadmin"}

_BLOCK_START = re.compile(r'^(resource|provider|variable)\s+"([^"]+)"(?:\s+"([^"]+)")?\s*\{', re.M)


def _strip_comments(text: str) -> str:
    return re.sub(r"(?m)#.*$", "", text)


def _blocks(kind: str) -> dict[str, str]:
    """Return {"type.name": body} (or {"name": body}) for top-level blocks of ``kind``."""
    found: dict[str, str] = {}
    for path in sorted(PLATFORM.glob("*.tf")):
        text = _strip_comments(path.read_text())
        for match in _BLOCK_START.finditer(text):
            if match.group(1) != kind:
                continue
            depth, i = 0, match.end() - 1
            while True:
                ch = text[i]
                depth += ch == "{"
                depth -= ch == "}"
                i += 1
                if depth == 0:
                    break
            body = text[match.end() : i - 1]
            if kind == "resource":
                key = f"{match.group(2)}.{match.group(3)}"
            elif kind == "provider":
                alias = re.search(r'alias\s*=\s*"([^"]+)"', body)
                key = alias.group(1) if alias else "<default>"
            else:
                key = match.group(2)
            assert key not in found, f"duplicate {kind} {key}"
            found[key] = body
    return found


def _provider_alias(body: str) -> str | None:
    match = re.search(r"^\s*provider\s*=\s*snowflake\.(\w+)", body, re.M)
    return match.group(1) if match else None


RESOURCES = _blocks("resource")


def test_platform_root_has_resources():
    assert len(RESOURCES) > 10


@pytest.mark.parametrize("address", sorted(RESOURCES))
def test_every_resource_names_its_alias(address):
    alias = _provider_alias(RESOURCES[address])
    expected = "|".join(sorted(ALIASES))
    assert alias in ALIASES, f"{address} must set provider = snowflake.<{expected}>"


def test_accountadmin_only_on_named_exceptions():
    used = {a for a, body in RESOURCES.items() if _provider_alias(body) == "accountadmin"}
    assert used == ACCOUNTADMIN_ALLOWED, (
        f"not in Decision 9: {sorted(used - ACCOUNTADMIN_ALLOWED)}; "
        f"listed but unused: {sorted(ACCOUNTADMIN_ALLOWED - used)}"
    )


def test_accountadmin_resources_carry_the_exception_comment():
    for path in sorted(PLATFORM.glob("*.tf")):
        for line in path.read_text().splitlines():
            if re.match(r"\s*provider\s*=\s*snowflake\.accountadmin", line):
                assert "Decision 9" in line, f"{path.name}: {line.strip()}"


def test_no_default_provider_and_all_aliases_defined():
    providers = _blocks("provider")
    assert set(providers) == ALIASES


@pytest.mark.parametrize("alias", sorted(ALIASES))
def test_every_alias_falls_back_to_plan_role(alias):
    providers_tf = (PLATFORM / "providers.tf").read_text()
    fallback = rf"{alias}\s*=\s*coalesce\(var\.plan_role,\s*\"{alias.upper()}\"\)"
    assert re.search(fallback, providers_tf)
    assert f"local.provider_role.{alias}" in _blocks("provider")[alias]


def test_plan_role_defaults_to_null():
    assert re.search(r"default\s*=\s*null", _blocks("variable")["plan_role"])


def test_cost_profile_has_no_default_and_is_set_in_dev_tfvars():
    assert not re.search(r"^\s*default\s*=", _blocks("variable")["cost_profile"], re.M)
    tfvars = _strip_comments(DEV_TFVARS.read_text())
    assert re.search(r'^cost_profile\s*=\s*"(baseline|optimized)"\s*$', tfvars, re.M)


def test_warehouse_sets_generation_never_resource_constraint():
    body = RESOURCES["snowflake_warehouse.cdc"]
    assert "generation" in body and "local.profile.generation" in body
    assert "resource_constraint" not in body
    assert re.search(r"enable_query_acceleration\s*=\s*false", body)
    assert re.search(r"auto_suspend\s*=\s*60\b", body)
    assert "snowflake_resource_monitor.cdc_wh.name" in body


@pytest.mark.parametrize("name", ["cdc_wh", "account"])
def test_monitors_never_reset(name):
    assert re.search(r'frequency\s*=\s*"NEVER"', RESOURCES[f"snowflake_resource_monitor.{name}"])


def test_secrets_never_in_terraform():
    for path in [*PLATFORM.glob("*.tf"), DEV_TFVARS]:
        text = _strip_comments(path.read_text())
        assert "private_key" not in text, path.name
        assert "-----BEGIN" not in text, path.name


def test_ci_warehouse_is_gen1_and_off_the_pipeline_monitor():
    body = RESOURCES["snowflake_warehouse.ci"]
    assert re.search(r'generation\s*=\s*"1"', body)
    assert "resource_monitor" not in body
    assert re.search(r"auto_suspend\s*=\s*60\b", body)
