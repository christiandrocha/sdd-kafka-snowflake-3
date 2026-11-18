# Pipeline warehouse, every cost setting explicit (Decision 4, Pattern 2; REQ-02).
#
# Named exception (Decision 9, F14): only ACCOUNTADMIN can assign a warehouse to
# a resource monitor, and the assignment lives on this resource — so CDC_WH is
# created and owned by ACCOUNTADMIN (owner decision 2026-11-18). CDC_ROLE and
# CDC_ROLE_RO get USAGE/OPERATE only (grants.tf).
#
# Generation comes from the cost profile: "2" in baseline, "1" in optimized.
# resource_constraint is never set: the provider reserves it for
# snowpark-optimized warehouses (F6).

resource "snowflake_warehouse" "cdc" {
  provider                  = snowflake.accountadmin # Decision 9 named exception
  name                      = var.warehouse_name
  warehouse_type            = "STANDARD"
  warehouse_size            = "XSMALL"
  generation                = local.profile.generation
  enable_query_acceleration = false # both profiles; deviation from v2 recorded in F10
  auto_suspend              = 60
  auto_resume               = true
  initially_suspended       = true
  resource_monitor          = snowflake_resource_monitor.cdc_wh.name
  comment                   = "CDC pipeline. Every cost setting is explicit; see DESIGN_COST_GOVERNANCE."
}
