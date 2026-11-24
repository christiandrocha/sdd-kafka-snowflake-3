# The only place cost_profile and the limits are set (Decision 2, Decision 8).
# Every CI apply uses the committed values; a profile switch is a one-line PR
# merged and apply-approved at 00:00 UTC (21:00 in Vitória).

# baseline = profile A (window A, v2 behaviour) · optimized = profile B (v3).
cost_profile = "baseline"

snowflake_organization_name = "GWHUBCF"
snowflake_account_name      = "QQ53235"

# Must match the owner's user on this account (DESC USER); notifications need a
# verified e-mail on that user.
owner_user_name = "CHRISTIANDROCHA"

# Decision 8 — sized for the whole trial (FREQUENCY = NEVER). Credit price read
# 2026-11-24: USD 4.65 (RATE_SHEET_DAILY, Enterprise, sa-east-1); balance
# USD 395.14 (~85 credits). Worst case 30 + 2 x 5 + ~3 overshoot = ~43 credits
# (~USD 200, ~50% of the balance). Owner decision 2026-11-24 (DESIGN 1.5).
cdc_wh_monitor_quota  = 25
account_monitor_quota = 30
# The 5-credit monthly budget lives in scripts/budget.sql (exception 2).
