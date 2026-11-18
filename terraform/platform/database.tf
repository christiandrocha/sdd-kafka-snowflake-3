# Database and the four schemas (REQ-01). Bronze tables inside BRONZE are
# created by the Kafka connector, not here (Decision 1, F5).

resource "snowflake_database" "cdc" {
  provider                       = snowflake.sysadmin
  name                           = var.database_name
  data_retention_time_in_days    = 1
  drop_public_schema_on_creation = true
  comment                        = "CDC pipeline PostgreSQL -> Kafka -> Snowflake. Managed by terraform/platform."
}

locals {
  schemas = {
    BRONZE = "Kafka connector landing + Bronze models. Append-only (ADR-0025)."
    SILVER = "CDC resolution. One row per entity."
    GOLD   = "Analytical aggregates."
    CONFIG = "TABLE_METADATA, PENDING_RUNS, logs, gate procedures."
  }
}

resource "snowflake_schema" "cdc" {
  provider = snowflake.sysadmin
  for_each = local.schemas
  database = snowflake_database.cdc.name
  name     = each.key
  comment  = each.value
}
