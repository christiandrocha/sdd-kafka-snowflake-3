# Privileges (REQ-01). Ports the v2 grants from 00_account_bootstrap.sql,
# bootstrap_config.sql and create_readonly_role.sql, with one fix: future grants
# are database-level only. v2 also had schema-level future grants on CONFIG,
# and in Snowflake schema-level future grants take precedence, which silently
# dropped CDC_ROLE_RO's future SELECT in CONFIG.
#
# Granted by SECURITYADMIN (MANAGE GRANTS) except the ones named in Decision 9.

locals {
  db = snowflake_database.cdc.name

  # Schema-level privileges for CDC_ROLE (v2 parity).
  cdc_role_schema_privileges = {
    BRONZE = ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE STREAM", "CREATE TASK", "CREATE STAGE", "CREATE PROCEDURE", "CREATE FILE FORMAT", "CREATE PIPE"]
    SILVER = ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE STREAM", "CREATE TASK", "CREATE STAGE", "CREATE PROCEDURE", "CREATE FILE FORMAT"]
    GOLD   = ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE STREAM", "CREATE TASK", "CREATE STAGE", "CREATE PROCEDURE", "CREATE FILE FORMAT"]
    CONFIG = ["USAGE", "CREATE TABLE", "CREATE VIEW", "CREATE PROCEDURE"]
  }

  # Object-type grants in the whole database: { key = [role, plural type, privileges] }.
  database_object_grants = {
    cdc_tables    = { role = var.role_name, type = "TABLES", privileges = ["SELECT", "INSERT", "UPDATE", "DELETE"] }
    cdc_views     = { role = var.role_name, type = "VIEWS", privileges = ["SELECT"] }
    ro_tables     = { role = var.readonly_role_name, type = "TABLES", privileges = ["SELECT"] }
    ro_views      = { role = var.readonly_role_name, type = "VIEWS", privileges = ["SELECT"] }
    ro_dyn_tables = { role = var.readonly_role_name, type = "DYNAMIC TABLES", privileges = ["SELECT"] }
  }
}

# --- Warehouse and database -------------------------------------------------

resource "snowflake_grant_privileges_to_account_role" "warehouse" {
  provider = snowflake.securityadmin
  for_each = {
    (var.role_name)            = ["USAGE", "OPERATE"]
    (var.readonly_role_name)   = ["USAGE"]
    (var.governance_role_name) = ["USAGE"]
  }
  account_role_name = snowflake_account_role.cdc[each.key].name
  privileges        = each.value
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.cdc.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "database_usage" {
  provider          = snowflake.securityadmin
  for_each          = toset([var.role_name, var.readonly_role_name])
  account_role_name = snowflake_account_role.cdc[each.key].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "DATABASE"
    object_name = local.db
  }
}

# --- SYSADMIN: prerequisites of the gate tasks in terraform/pipeline ---------
# SYSADMIN owns the gate tasks (terraform/pipeline). These grants live here
# because they are account-level and do not depend on Bronze, and platform is
# applied before pipeline (Decision 1) — tests/unit/test_pipeline_root.py
# checks that pipeline does not need them itself.

# Profile baseline runs the tasks on CDC_WH, which ACCOUNTADMIN owns (F14).
resource "snowflake_grant_privileges_to_account_role" "sysadmin_cdc_wh" {
  provider          = snowflake.securityadmin
  account_role_name = "SYSADMIN"
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.cdc.name
  }
}

# EXECUTE TASK: run tasks the role owns. EXECUTE MANAGED TASK: only for
# serverless tasks (profile optimized); granted in both profiles so a switch
# changes nothing but the tasks (Decision 2).
# HYPOTHESIS, to validate at the Day 3 apply: SECURITYADMIN's MANAGE GRANTS is
# enough for these global privileges. The Snowflake docs do not say who can
# grant them; their task examples use ACCOUNTADMIN. If the apply fails here,
# move this resource to snowflake.accountadmin per the prepared DESIGN 1.3 text
# (BUILD_REPORT, run 3).
resource "snowflake_grant_privileges_to_account_role" "sysadmin_execute_task" {
  provider          = snowflake.securityadmin
  account_role_name = "SYSADMIN"
  privileges        = ["EXECUTE MANAGED TASK", "EXECUTE TASK"]
  on_account        = true
}

# --- CDC_ROLE ---------------------------------------------------------------

resource "snowflake_grant_privileges_to_account_role" "cdc_role_schemas" {
  provider          = snowflake.securityadmin
  for_each          = local.cdc_role_schema_privileges
  account_role_name = snowflake_account_role.cdc[var.role_name].name
  privileges        = each.value
  on_schema {
    schema_name = snowflake_schema.cdc[each.key].fully_qualified_name
  }
}

# --- CDC_ROLE_RO ------------------------------------------------------------

resource "snowflake_grant_privileges_to_account_role" "ro_schemas_all" {
  provider          = snowflake.securityadmin
  account_role_name = snowflake_account_role.cdc[var.readonly_role_name].name
  privileges        = ["USAGE"]
  on_schema {
    all_schemas_in_database = local.db
  }
  depends_on = [snowflake_schema.cdc]
}

resource "snowflake_grant_privileges_to_account_role" "ro_schemas_future" {
  provider          = snowflake.securityadmin
  account_role_name = snowflake_account_role.cdc[var.readonly_role_name].name
  privileges        = ["USAGE"]
  on_schema {
    future_schemas_in_database = local.db
  }
}

resource "snowflake_grant_privileges_to_account_role" "ro_tasks_future" {
  provider          = snowflake.securityadmin
  account_role_name = snowflake_account_role.cdc[var.readonly_role_name].name
  privileges        = ["MONITOR"]
  on_schema_object {
    future {
      object_type_plural = "TASKS"
      in_database        = local.db
    }
  }
}

# --- Object grants in the database (both roles) -----------------------------

resource "snowflake_grant_privileges_to_account_role" "database_objects_all" {
  provider          = snowflake.securityadmin
  for_each          = local.database_object_grants
  account_role_name = snowflake_account_role.cdc[each.value.role].name
  privileges        = each.value.privileges
  on_schema_object {
    all {
      object_type_plural = each.value.type
      in_database        = local.db
    }
  }
  # ALL is evaluated once, at apply: the CONFIG tables must exist first.
  depends_on = [snowflake_table.config]
}

resource "snowflake_grant_privileges_to_account_role" "database_objects_future" {
  provider          = snowflake.securityadmin
  for_each          = local.database_object_grants
  account_role_name = snowflake_account_role.cdc[each.value.role].name
  privileges        = each.value.privileges
  on_schema_object {
    future {
      object_type_plural = each.value.type
      in_database        = local.db
    }
  }
}

# --- CDC_GOVERNANCE_RO: SNOWFLAKE database roles ----------------------------
# Named exception (Decision 9): "Only users with the OWNERSHIP role can grant
# SNOWFLAKE database roles" (Snowflake docs, SNOWFLAKE database roles) —
# ACCOUNTADMIN on this account. Confirmed at Build 2026-11-18.

resource "snowflake_grant_database_role" "governance" {
  provider           = snowflake.accountadmin # Decision 9 named exception
  for_each           = toset(["USAGE_VIEWER", "GOVERNANCE_VIEWER", "SECURITY_VIEWER", "MONITORING_VIEWER"])
  database_role_name = "\"SNOWFLAKE\".\"${each.key}\""
  parent_role_name   = snowflake_account_role.cdc[var.governance_role_name].name
}

# --- CDC_BUDGET_ADMIN: what scripts/budget.sql needs (Decision 9, exception 2) -
# CREATE BUDGET: CREATE SNOWFLAKE.CORE.BUDGET on the schema + SNOWFLAKE.BUDGET_CREATOR.
# ADD_RESOURCE: APPLYBUDGET on the database. ADD_CUSTOM_ACTION: USAGE on the
# procedure (SYSTEM$REFERENCE). Snowflake docs: CREATE BUDGET, ADD_RESOURCE,
# Custom actions for budgets (read 2026-11-18).

resource "snowflake_grant_privileges_to_account_role" "budget_ci_warehouse" {
  provider          = snowflake.securityadmin
  account_role_name = snowflake_account_role.cdc[var.budget_role_name].name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.ci.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "budget_database" {
  provider          = snowflake.securityadmin
  account_role_name = snowflake_account_role.cdc[var.budget_role_name].name
  privileges        = ["APPLYBUDGET", "USAGE"]
  on_account_object {
    object_type = "DATABASE"
    object_name = local.db
  }
}

resource "snowflake_grant_privileges_to_account_role" "budget_schema" {
  provider          = snowflake.securityadmin
  account_role_name = snowflake_account_role.cdc[var.budget_role_name].name
  privileges        = ["CREATE SNOWFLAKE.CORE.BUDGET", "USAGE"]
  on_schema {
    schema_name = snowflake_schema.cdc["CONFIG"].fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "budget_procedure" {
  provider          = snowflake.securityadmin
  account_role_name = snowflake_account_role.cdc[var.budget_role_name].name
  privileges        = ["USAGE"]
  on_schema_object {
    object_type = "PROCEDURE"
    object_name = snowflake_procedure_sql.suspend_gate_tasks.fully_qualified_name
  }
}

# Named exception (Decision 9): only the owner grants SNOWFLAKE database roles.
resource "snowflake_grant_database_role" "budget_creator" {
  provider           = snowflake.accountadmin # Decision 9 named exception
  database_role_name = "\"SNOWFLAKE\".\"BUDGET_CREATOR\""
  parent_role_name   = snowflake_account_role.cdc[var.budget_role_name].name
}

# --- TERRAFORM_PLAN_ROLE: read-only refresh (Decision 9) --------------------
# Unproven until Day 3: if a refresh fails, grant the specific read privilege
# that is missing, or plan with -refresh=false for that resource (Decision 9).

resource "snowflake_grant_privileges_to_account_role" "plan_warehouse" {
  provider = snowflake.securityadmin
  for_each = {
    cdc = snowflake_warehouse.cdc.name
    ci  = snowflake_warehouse.ci.name
  }
  account_role_name = var.plan_role_name
  privileges        = ["MONITOR"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = each.value
  }
}

# verify_governance.sql runs as the plan role (read-only) on CDC_CI_WH.
resource "snowflake_grant_privileges_to_account_role" "plan_ci_warehouse_usage" {
  provider          = snowflake.securityadmin
  account_role_name = var.plan_role_name
  privileges        = ["USAGE"]
  on_account_object {
    object_type = "WAREHOUSE"
    object_name = snowflake_warehouse.ci.name
  }
}

# SHOW TASKS lists only tasks the role owns or has MONITOR/OPERATE on.
# Future grant here; terraform/pipeline adds a per-task grant for tasks that
# already exist.
resource "snowflake_grant_privileges_to_account_role" "plan_tasks_future" {
  provider          = snowflake.securityadmin
  account_role_name = var.plan_role_name
  privileges        = ["MONITOR"]
  on_schema_object {
    future {
      object_type_plural = "TASKS"
      in_database        = local.db
    }
  }
}

resource "snowflake_grant_privileges_to_account_role" "plan_database" {
  provider          = snowflake.securityadmin
  account_role_name = var.plan_role_name
  privileges        = ["USAGE", "MONITOR"]
  on_account_object {
    object_type = "DATABASE"
    object_name = local.db
  }
}

resource "snowflake_grant_privileges_to_account_role" "plan_schemas" {
  provider          = snowflake.securityadmin
  for_each          = snowflake_schema.cdc
  account_role_name = var.plan_role_name
  privileges        = ["USAGE", "MONITOR"]
  on_schema {
    schema_name = each.value.fully_qualified_name
  }
}

# REFERENCES lets the role describe the CONFIG tables without reading their rows.
resource "snowflake_grant_privileges_to_account_role" "plan_config_tables" {
  provider          = snowflake.securityadmin
  for_each          = snowflake_table.config
  account_role_name = var.plan_role_name
  privileges        = ["REFERENCES"]
  on_schema_object {
    object_type = "TABLE"
    object_name = each.value.fully_qualified_name
  }
}

resource "snowflake_grant_privileges_to_account_role" "plan_users" {
  provider          = snowflake.securityadmin
  for_each          = snowflake_service_user.cdc
  account_role_name = var.plan_role_name
  privileges        = ["MONITOR"]
  on_account_object {
    object_type = "USER"
    object_name = each.value.name
  }
}

resource "snowflake_grant_privileges_to_account_role" "plan_procedures" {
  provider          = snowflake.securityadmin
  account_role_name = var.plan_role_name
  privileges        = ["USAGE"]
  on_schema_object {
    object_type = "PROCEDURE"
    object_name = snowflake_procedure_sql.suspend_gate_tasks.fully_qualified_name
  }
}

# Named exception (Decision 9, F14): the monitors are owned by ACCOUNTADMIN;
# MONITOR is what lets a non-admin role see them in SHOW RESOURCE MONITORS.
resource "snowflake_grant_privileges_to_account_role" "plan_monitors" {
  provider = snowflake.accountadmin # Decision 9 named exception
  for_each = {
    cdc_wh  = snowflake_resource_monitor.cdc_wh.name
    account = snowflake_resource_monitor.account.name
  }
  account_role_name = var.plan_role_name
  privileges        = ["MONITOR"]
  on_account_object {
    object_type = "RESOURCE MONITOR"
    object_name = each.value
  }
}
