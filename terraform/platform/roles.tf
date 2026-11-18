# Account roles (REQ-01). Replaces 00_account_bootstrap.sql and
# create_readonly_role.sql. Each custom role is granted to SYSADMIN, Snowflake's
# recommended hierarchy, so SYSADMIN can manage objects these roles create
# (e.g. connector-created Bronze tables). TERRAFORM_PLAN_ROLE is created by
# scripts/00_terraform_bootstrap.sql and only receives grants here.

locals {
  account_roles = {
    (var.role_name)            = "Pipeline write role: Dagster, dbt and the Kafka sink."
    (var.readonly_role_name)   = "Read-only on CDC_POC. Exploration surface (Cursor MCP). No DDL/DML."
    (var.governance_role_name) = "ACCOUNT_USAGE reader for cost attribution. Owner's personal user only."
    (var.budget_role_name)     = "Owns the CDC_POC custom budget; runs scripts/budget.sql in CI (exception 2)."
  }
}

resource "snowflake_account_role" "cdc" {
  provider = snowflake.securityadmin
  for_each = local.account_roles
  name     = each.key
  comment  = each.value
}

resource "snowflake_grant_account_role" "cdc_to_sysadmin" {
  provider         = snowflake.securityadmin
  for_each         = snowflake_account_role.cdc
  role_name        = each.value.name
  parent_role_name = "SYSADMIN"
}

# CI runs scripts/budget.sql as TERRAFORM_SVC with USE ROLE CDC_BUDGET_ADMIN.
resource "snowflake_grant_account_role" "budget_role_to_terraform" {
  provider  = snowflake.securityadmin
  role_name = snowflake_account_role.cdc[var.budget_role_name].name
  user_name = var.terraform_user_name
}
