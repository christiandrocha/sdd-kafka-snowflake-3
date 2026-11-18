# One append-only stream and one gate task per Tier-1 domain (Decision 5,
# Pattern 3; REQ-04). The compute is the A/B switch:
#   baseline  (profile A): task on CDC_WH, Snowflake defaults for timeout and
#                          failure limit — identical to v2.
#   optimized (profile B): serverless, XSMALL cap, timeout var.gate_task_timeout_ms,
#                          suspended after 3 consecutive failures.
# Streams need the connector-created Bronze tables (F5): until they exist, CI
# skips this root's plan with a notice (Decision 11).

locals {
  serverless = local.profile.task_compute == "serverless"
  stream_fqn = { for d in var.gate_domains : d => "${var.database_name}.BRONZE.${d}_STREAM" }
}

resource "snowflake_stream_on_table" "bronze" {
  provider    = snowflake.sysadmin
  for_each    = var.gate_domains
  database    = var.database_name
  schema      = "BRONZE"
  name        = "${each.key}_STREAM"
  table       = "\"${var.database_name}\".\"BRONZE\".\"${each.key}\""
  append_only = "true" # Bronze is append-only (ADR-0025)
  comment     = "Gate stream for ${each.key} (ADR-0019)."
}

resource "snowflake_task" "gate" {
  provider = snowflake.sysadmin
  for_each = var.gate_domains
  database = var.database_name
  schema   = "BRONZE"
  name     = "${each.key}_GATE_TASK"
  started  = true
  comment  = "Gate for ${each.key}: PENDING_RUNS row when the stream has data (ADR-0019)."

  warehouse                                = local.serverless ? null : var.warehouse_name
  user_task_managed_initial_warehouse_size = local.serverless ? "XSMALL" : null
  serverless_task_max_statement_size       = local.serverless ? "XSMALL" : null
  user_task_timeout_ms                     = local.serverless ? var.gate_task_timeout_ms : null
  suspend_task_after_num_failures          = local.serverless ? 3 : null

  schedule {
    minutes = 1
  }

  when          = "SYSTEM$STREAM_HAS_DATA('${local.stream_fqn[each.key]}')"
  sql_statement = "CALL ${var.database_name}.CONFIG.SP_GATE_DOMAIN('${local.stream_fqn[each.key]}', '${each.key}')"

  depends_on = [snowflake_stream_on_table.bronze, snowflake_procedure_sql.gate_domain]
}

# verify_governance.sql runs as TERRAFORM_PLAN_ROLE and must see every gate
# task in SHOW TASKS (MONITOR, OPERATE or OWNERSHIP). terraform/platform grants
# MONITOR on FUTURE tasks; this per-task grant also covers tasks that already
# existed before that future grant. Granted by SYSADMIN as the tasks' owner.
resource "snowflake_grant_privileges_to_account_role" "plan_task_monitor" {
  provider          = snowflake.sysadmin
  for_each          = snowflake_task.gate
  account_role_name = var.plan_role_name
  privileges        = ["MONITOR"]
  on_schema_object {
    object_type = "TASK"
    object_name = each.value.fully_qualified_name
  }
}
