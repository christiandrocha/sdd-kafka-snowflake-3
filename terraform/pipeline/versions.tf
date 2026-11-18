# Provider pin (DESIGN_COST_GOVERNANCE Decision 4, F1, F11).
# `generation` on snowflake_warehouse needs >= 2.7.0. The exact version is
# locked in .terraform.lock.hcl and changes only by PR with a clean plan,
# because the preview resources used here may change in a minor release (F11).
terraform {
  required_version = ">= 1.11.0" # S3 native lockfile (Decision 12)

  required_providers {
    snowflake = {
      source  = "snowflakedb/snowflake"
      version = ">= 2.7.0, < 3.0.0"
    }
  }
}
