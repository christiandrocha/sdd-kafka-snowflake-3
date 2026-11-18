# Shares terraform/env/dev.tfvars with terraform/platform (Build checklist B1).
# Variables that only platform declares (quotas, owner_user_name) produce a
# "value for undeclared variable" warning here, not an error.

variable "snowflake_organization_name" {
  type = string
}

variable "snowflake_account_name" {
  type = string
}

variable "plan_role" {
  description = "Set only by the PR plan job (TERRAFORM_PLAN_ROLE). Null on apply."
  type        = string
  default     = null
}

variable "plan_role_name" {
  description = "Read-only role that verify_governance.sql runs as; gets MONITOR on every gate task."
  type        = string
  default     = "TERRAFORM_PLAN_ROLE"
}

variable "database_name" {
  type    = string
  default = "CDC_POC"
}

variable "warehouse_name" {
  description = "Warehouse the gate tasks use in profile baseline (v2 behaviour)."
  type        = string
  default     = "CDC_WH"
}

variable "gate_domains" {
  description = "Tier-1 Bronze tables (ADR-0022); names as created by the Kafka connector's topic2table.map."
  type        = set(string)
  default = [
    "ORDERS", "ORDER_ITEMS", "DRIVERS", "DRIVER_SHIFTS", "RESTAURANTS",
    "USERS_MONGO", "USERS_MSSQL", "PAYMENT_EVENTS", "RECOMMENDATIONS", "SEARCH_EVENTS",
  ]
}

variable "gate_task_timeout_ms" {
  description = <<-EOT
    Serverless gate-task timeout, profile optimized only (Decision 5).
    PROVISIONAL: 10 000 ms until the dry run (Day 7) measures the p99 run
    duration in TASK_HISTORY; then set to max(10 s, 5 x p99) in dev.tfvars.
    Open: whether serverless start-up counts toward the timeout (BUILD_REPORT).
  EOT
  type        = number
  default     = 10000

  validation {
    condition     = var.gate_task_timeout_ms >= 10000
    error_message = "gate_task_timeout_ms must be at least 10 000 ms (Decision 5)."
  }
}
