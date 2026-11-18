# terraform/pipeline uses a single alias: everything here is owned by SYSADMIN
# (gate procedure, streams, tasks, and the MONITOR grants SYSADMIN makes as
# their owner). No securityadmin or accountadmin alias exists in this root.
#
# Account-level prerequisites live in terraform/platform, which is applied
# first (Decision 1): EXECUTE TASK / EXECUTE MANAGED TASK and USAGE on CDC_WH
# for SYSADMIN (grants.tf there).
#
# PR plans set TF_VAR_plan_role=TERRAFORM_PLAN_ROLE (Decisions 9 and 11).

provider "snowflake" {
  alias                    = "sysadmin"
  organization_name        = var.snowflake_organization_name
  account_name             = var.snowflake_account_name
  authenticator            = "SNOWFLAKE_JWT"
  role                     = coalesce(var.plan_role, "SYSADMIN")
  preview_features_enabled = ["snowflake_procedure_sql_resource"] # F11
}
