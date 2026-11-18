# Resource monitors sized for the whole trial (Decision 8, F9).
# FREQUENCY = NEVER: used credits never reset, so the caps hold until the trial
# ends on 2026-12-17 instead of resetting on Dec 1.
#
# Named exception (Decision 9, F14): only ACCOUNTADMIN creates resource monitors.
# The account-level assignment is CI SQL, scripts/account_monitor.sql
# (exception 3); serverless spend is not covered by monitors (F2) — see the
# budget in scripts/budget.sql (exception 2).

resource "snowflake_resource_monitor" "cdc_wh" {
  provider        = snowflake.accountadmin # Decision 9 named exception
  name            = "CDC_WH_MONITOR"
  credit_quota    = var.cdc_wh_monitor_quota
  frequency       = "NEVER"
  start_timestamp = "IMMEDIATELY"

  notify_triggers           = [50, 75]
  suspend_trigger           = 90
  suspend_immediate_trigger = 100
  notify_users              = [var.owner_user_name]
}

resource "snowflake_resource_monitor" "account" {
  provider        = snowflake.accountadmin # Decision 9 named exception
  name            = "CDC_ACCOUNT_MONITOR"
  credit_quota    = var.account_monitor_quota
  frequency       = "NEVER"
  start_timestamp = "IMMEDIATELY"

  notify_triggers = [50, 75, 90]
  suspend_trigger = 100
  notify_users    = [var.owner_user_name]
}
