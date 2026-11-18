# The only place cost_profile and the limits are set (Decision 2, Decision 8).
# Every CI apply uses the committed values; a profile switch is a one-line PR
# merged and apply-approved at 00:00 UTC (21:00 in Vitória).

# baseline = profile A (window A, v2 behaviour) · optimized = profile B (v3).
cost_profile = "optimized"

snowflake_organization_name = "GWHUBCF"
snowflake_account_name      = "QQ53235"

# Must match the owner's user on this account (DESC USER); notifications need a
# verified e-mail on that user.
owner_user_name = "CHRISTIANDROCHA"

# Decision 8 — sized for the whole trial (FREQUENCY = NEVER). The credit price
# (_index open item 7) must be read before the first apply; if 60 credits are
# more than ~50% of the balance, lower these in the same PR.
cdc_wh_monitor_quota  = 25
account_monitor_quota = 40
# The 10-credit monthly budget lives in scripts/budget.sql (exception 2).
