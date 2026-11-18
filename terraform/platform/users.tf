# Service users (REQ-01): key-pair only, TYPE = SERVICE (no password, no MFA).
# Public keys come from TF_VAR_* in CI; private keys never enter Terraform
# (DESIGN, Security considerations).

locals {
  service_users = {
    DAGSTER_SERVICE_USER = {
      role    = var.role_name
      key     = var.dagster_rsa_public_key
      comment = "Dagster, dbt and the Kafka Connect Snowflake sink."
    }
    DATA_AGENTS_MCP_USER = {
      role    = var.role_name
      key     = var.data_agents_rsa_public_key
      comment = "Data agents with write access."
    }
    CURSOR_MCP_USER = {
      role    = var.readonly_role_name
      key     = var.cursor_rsa_public_key
      comment = "Read-only exploration (Cursor MCP)."
    }
  }
}

resource "snowflake_service_user" "cdc" {
  provider          = snowflake.securityadmin
  for_each          = local.service_users
  name              = each.key
  default_role      = snowflake_account_role.cdc[each.value.role].name
  default_warehouse = snowflake_warehouse.cdc.name
  rsa_public_key    = each.value.key
  comment           = each.value.comment
}

resource "snowflake_grant_account_role" "service_users" {
  provider  = snowflake.securityadmin
  for_each  = local.service_users
  role_name = snowflake_account_role.cdc[each.value.role].name
  user_name = snowflake_service_user.cdc[each.key].name
}

resource "snowflake_grant_account_role" "governance_to_owner" {
  provider  = snowflake.securityadmin
  role_name = snowflake_account_role.cdc[var.governance_role_name].name
  user_name = var.owner_user_name
}
