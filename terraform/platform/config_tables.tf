# CONFIG tables (Decision 9: our schema, static — unlike Bronze, so Terraform
# owns them). Moved from scripts/bootstrap_config.sql and
# scripts/streams_and_tasks.sql; the TABLE_METADATA seed stays in SQL
# (scripts/seed_config.sql, manifest item 5) because it is data, not objects.
#
# Types are written in Snowflake's canonical read-back form (VARCHAR(n),
# NUMBER(38,0), TIMESTAMP_NTZ(9)) so the second plan stays clean (AT-001).
# New in v3 (Decision 7): PENDING_RUNS.consumed_run_key and
# PROCESSING_LOG.run_key tie freshness to the run that consumed the burst.
#
# snowflake_table is a preview resource (F11).

locals {
  ts = "TIMESTAMP_NTZ(9)"

  config_tables = {
    TABLE_METADATA = {
      comment     = "Per-domain CDC metadata. Seeded by scripts/seed_config.sql; read by dbt."
      primary_key = ["TABLE_NAME"]
      columns = [
        { name = "TABLE_NAME", type = "VARCHAR(100)", nullable = false },
        { name = "TOPIC", type = "VARCHAR(200)", nullable = false },
        { name = "TABLE_TYPE", type = "VARCHAR(20)", nullable = false },
        { name = "CDC_STRATEGY", type = "VARCHAR(20)", nullable = false },
        { name = "UNIQUE_KEY", type = "VARCHAR(100)" },
        { name = "ACTIVE", type = "BOOLEAN", nullable = false, default = "TRUE" },
        { name = "REGISTERED_AT", type = local.ts, nullable = false, default = "CURRENT_TIMESTAMP()" },
        { name = "UPDATED_AT", type = local.ts, nullable = false, default = "CURRENT_TIMESTAMP()" },
        { name = "SOURCE", type = "VARCHAR(50)", nullable = false },
        { name = "PREVIOUS_STRATEGY", type = "VARCHAR(20)" },
        { name = "CHANGED_BY", type = "VARCHAR(100)" },
        { name = "NOTES", type = "VARCHAR(500)" },
      ]
    }

    METADATA_HISTORY = {
      comment     = "Audit trail of TABLE_METADATA changes (scripts/sync_metadata.py)."
      primary_key = ["HISTORY_ID"]
      columns = [
        { name = "HISTORY_ID", type = "NUMBER(38,0)", nullable = false, identity = true },
        { name = "TABLE_NAME", type = "VARCHAR(100)", nullable = false },
        { name = "CHANGED_AT", type = local.ts, nullable = false, default = "CURRENT_TIMESTAMP()" },
        { name = "CHANGED_BY", type = "VARCHAR(100)", nullable = false },
        { name = "CHANGE_TYPE", type = "VARCHAR(20)", nullable = false },
        { name = "FIELD_CHANGED", type = "VARCHAR(100)" },
        { name = "OLD_VALUE", type = "VARCHAR(500)" },
        { name = "NEW_VALUE", type = "VARCHAR(500)" },
        { name = "SOURCE", type = "VARCHAR(50)", nullable = false },
      ]
    }

    PROCESSING_LOG = {
      comment     = "One row per dbt model per run (dagster/pipeline/assets.py)."
      primary_key = ["LOG_ID"]
      columns = [
        { name = "LOG_ID", type = "NUMBER(38,0)", nullable = false, identity = true },
        { name = "TABLE_NAME", type = "VARCHAR(100)", nullable = false },
        { name = "LAYER", type = "VARCHAR(20)", nullable = false },
        { name = "DBT_MODEL", type = "VARCHAR(200)", nullable = false },
        { name = "DBT_INVOCATION_ID", type = "VARCHAR(100)" },
        { name = "RUN_ID", type = "VARCHAR(100)" },
        { name = "STATUS", type = "VARCHAR(20)", nullable = false },
        { name = "ROWS_PROCESSED", type = "NUMBER(38,0)", default = "0" },
        { name = "STARTED_AT", type = local.ts },
        { name = "FINISHED_AT", type = local.ts },
        { name = "DURATION_SECONDS", type = "NUMBER(10,3)" },
        { name = "ERROR_MESSAGE", type = "VARCHAR(2000)" },
        { name = "TRIGGERED_BY", type = "VARCHAR(100)" },
        { name = "LOGGED_AT", type = local.ts, nullable = false, default = "CURRENT_TIMESTAMP()" },
        { name = "RUN_KEY", type = "VARCHAR(200)", comment = "Sensor run_key that consumed the PENDING_RUNS rows (Decision 7)." },
      ]
    }

    PENDING_RUNS = {
      comment     = "Written by the gate tasks (SP_GATE_DOMAIN), consumed by the Dagster sensor."
      primary_key = null
      columns = [
        { name = "DOMAIN", type = "VARCHAR(100)" },
        { name = "DETECTED_AT", type = local.ts },
        { name = "CONSUMED", type = "BOOLEAN", default = "FALSE" },
        { name = "CONSUMED_RUN_KEY", type = "VARCHAR(200)", comment = "run_key of the run that consumed this row (Decision 7)." },
      ]
    }

    STREAM_CONSUMPTION_LOG = {
      comment     = "Rows seen per gate-task run (SP_GATE_DOMAIN)."
      primary_key = null
      columns = [
        { name = "DOMAIN", type = "VARCHAR(100)" },
        { name = "ROWS_SEEN", type = "NUMBER(38,0)" },
        { name = "CONSUMED_AT", type = local.ts },
      ]
    }
  }
}

resource "snowflake_table" "config" {
  provider = snowflake.sysadmin
  for_each = local.config_tables
  database = snowflake_database.cdc.name
  schema   = snowflake_schema.cdc["CONFIG"].name
  name     = each.key
  comment  = each.value.comment

  dynamic "column" {
    for_each = each.value.columns
    content {
      name     = column.value.name
      type     = column.value.type
      nullable = try(column.value.nullable, true)
      comment  = try(column.value.comment, null)

      dynamic "default" {
        for_each = try(column.value.default, null) == null ? [] : [column.value.default]
        content {
          expression = default.value
        }
      }

      dynamic "identity" {
        for_each = try(column.value.identity, false) ? [1] : []
        content {
          start_num = 1
          step_num  = 1
        }
      }
    }
  }

  dynamic "primary_key" {
    for_each = each.value.primary_key == null ? [] : [each.value.primary_key]
    content {
      keys = primary_key.value
    }
  }
}
