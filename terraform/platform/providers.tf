# One provider configuration per Snowflake system role (Decision 9).
#
# Every resource names its alias explicitly; tests/unit/test_terraform_providers.py
# fails if one does not, or if a resource not on the Decision 9 list uses
# `snowflake.accountadmin`.
#
# Credentials come from the environment only (Constitution R3):
#   SNOWFLAKE_USER, SNOWFLAKE_PRIVATE_KEY (PEM), optional SNOWFLAKE_PRIVATE_KEY_PASSPHRASE.
#
# PR plans set TF_VAR_plan_role=TERRAFORM_PLAN_ROLE and authenticate as
# TERRAFORM_PLAN_SVC: every alias then uses the read-only role, so no PR plan
# ever runs with ACCOUNTADMIN (Decisions 9 and 11). Apply runs leave plan_role
# null and authenticate as TERRAFORM_SVC.

locals {
  provider_role = {
    sysadmin      = coalesce(var.plan_role, "SYSADMIN")
    securityadmin = coalesce(var.plan_role, "SECURITYADMIN")
    accountadmin  = coalesce(var.plan_role, "ACCOUNTADMIN")
  }

  # F11: exactly the preview resources this root uses.
  preview_features = ["snowflake_table_resource", "snowflake_procedure_sql_resource"]
}

provider "snowflake" {
  alias                    = "sysadmin"
  organization_name        = var.snowflake_organization_name
  account_name             = var.snowflake_account_name
  authenticator            = "SNOWFLAKE_JWT"
  role                     = local.provider_role.sysadmin
  preview_features_enabled = local.preview_features
}

provider "snowflake" {
  alias                    = "securityadmin"
  organization_name        = var.snowflake_organization_name
  account_name             = var.snowflake_account_name
  authenticator            = "SNOWFLAKE_JWT"
  role                     = local.provider_role.securityadmin
  preview_features_enabled = local.preview_features
}

# Named exception (Decision 9): only the resources listed there use this alias.
provider "snowflake" {
  alias                    = "accountadmin"
  organization_name        = var.snowflake_organization_name
  account_name             = var.snowflake_account_name
  authenticator            = "SNOWFLAKE_JWT"
  role                     = local.provider_role.accountadmin
  preview_features_enabled = local.preview_features
}
