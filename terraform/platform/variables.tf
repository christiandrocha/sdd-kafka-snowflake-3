# Names keep v2's values as defaults (Decision 3). Limits and the account
# identity have no default: they live in terraform/env/dev.tfvars only.

# --- Account and identity -------------------------------------------------

variable "snowflake_organization_name" {
  description = "Snowflake organization name (account identifier, org part)."
  type        = string
}

variable "snowflake_account_name" {
  description = "Snowflake account name (account identifier, account part)."
  type        = string
}

variable "plan_role" {
  description = "Set only by the PR plan job (TERRAFORM_PLAN_ROLE): every provider alias then uses it. Null on apply."
  type        = string
  default     = null
}

variable "plan_role_name" {
  description = "Read-only role created by scripts/00_terraform_bootstrap.sql; receives USAGE/MONITOR grants here."
  type        = string
  default     = "TERRAFORM_PLAN_ROLE"
}

variable "owner_user_name" {
  description = "Owner's Snowflake user: monitor notifications and CDC_GOVERNANCE_RO. Must have a verified e-mail."
  type        = string
}

# --- Object names (Decision 3) --------------------------------------------

variable "database_name" {
  type    = string
  default = "CDC_POC"
}

variable "warehouse_name" {
  description = "Pipeline warehouse. AT-002 reads this name (DEFINE 1.3)."
  type        = string
  default     = "CDC_WH"
}

variable "role_name" {
  description = "Pipeline write role: Dagster, dbt, the Kafka sink."
  type        = string
  default     = "CDC_ROLE"
}

variable "readonly_role_name" {
  description = "Read-only exploration role (Cursor MCP)."
  type        = string
  default     = "CDC_ROLE_RO"
}

variable "governance_role_name" {
  description = "ACCOUNT_USAGE reader for cost attribution; granted to the owner only."
  type        = string
  default     = "CDC_GOVERNANCE_RO"
}

# --- Spending limits (Decision 8) -----------------------------------------

variable "cdc_wh_monitor_quota" {
  description = "Credits on the CDC_WH monitor for the whole trial (FREQUENCY = NEVER)."
  type        = number

  validation {
    condition     = var.cdc_wh_monitor_quota > 0
    error_message = "cdc_wh_monitor_quota must be positive."
  }
}

variable "account_monitor_quota" {
  description = "Credits on the account-level monitor for the whole trial (FREQUENCY = NEVER)."
  type        = number

  validation {
    condition     = var.account_monitor_quota > 0
    error_message = "account_monitor_quota must be positive."
  }
}

# --- Service users' public keys --------------------------------------------
# Public keys only (one line, no header/trailer). Not secret, but kept out of
# the repo: CI passes them as environment variables (TF_VAR_*). Private keys
# never enter Terraform. Null = user exists without a key and cannot log in.

variable "dagster_rsa_public_key" {
  type    = string
  default = null
}

variable "data_agents_rsa_public_key" {
  type    = string
  default = null
}

variable "cursor_rsa_public_key" {
  type    = string
  default = null
}
