# Cost profiles (Decision 2, Pattern 1). The A/B is a switch of this one value,
# set only in terraform/env/dev.tfvars and changed by PR at 00:00 UTC.
# terraform/pipeline gets its own copy of this lookup (Build checklist B1).

variable "cost_profile" {
  description = "baseline (profile A, v2 behaviour) or optimized (profile B, v3). No default on purpose."
  type        = string

  validation {
    condition     = contains(["baseline", "optimized"], var.cost_profile)
    error_message = "cost_profile must be baseline or optimized."
  }
}

locals {
  profiles = {
    baseline  = { generation = "2", task_compute = "warehouse" }
    optimized = { generation = "1", task_compute = "serverless" }
  }
  profile = local.profiles[var.cost_profile]
}
