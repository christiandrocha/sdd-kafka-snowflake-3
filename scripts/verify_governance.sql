-- ------------------------------------------------------------------------
-- verify_governance.sql — account checks for AT-002, AT-003 and AT-004
-- (COST_GOVERNANCE manifest item 9; Build checklist B1, B4).
--
-- ASSERTIVE: each check is a Snowflake Scripting block that RAISES on a
-- mismatch, so CI fails instead of printing a result nobody reads. v2's
-- version of this file documented the trap it fell into: SHOW returns zero
-- rows, without error, for objects the active role cannot see. Here "not
-- found" is a failure, never a pass.
--
-- READ-ONLY: runs as TERRAFORM_PLAN_ROLE on CDC_CI_WH (never CDC_WH, never
-- ACCOUNTADMIN). Visibility comes from terraform/platform (MONITOR on both
-- warehouses, both monitors and future tasks; USAGE on the database, schemas
-- and CDC_CI_WH), terraform/pipeline (MONITOR on each gate task) and
-- scripts/budget.sql (the budget's VIEWER instance role).
--
-- RUN BY: CI after every apply on `main`, and after every profile switch —
-- a switch that applied only one root voids the window (B1):
--   snow sql -f scripts/verify_governance.sql \
--     -D "cost_profile=optimized" -D "gate_task_timeout_ms=10000" -D "check_pipeline=true"
-- cost_profile and gate_task_timeout_ms must be the values in
-- terraform/env/dev.tfvars; check_pipeline=false until the first pipeline
-- apply (Bronze tables exist only after the connector's first write, F5).
-- ------------------------------------------------------------------------

USE ROLE TERRAFORM_PLAN_ROLE;
USE WAREHOUSE CDC_CI_WH;

-- AT-002 / REQ-02 — warehouse cost settings (F6 read-back format, B4) ---------
-- Expected in profile optimized: generation = 1, resource_constraint =
-- STANDARD_GEN_1 (rejected on write, reported on read — F6). In baseline,
-- generation = 2; resource_constraint = STANDARD_GEN_2 is assumed by symmetry
-- and confirmed in the dry run (BUILD_REPORT run 3).
SHOW WAREHOUSES LIKE 'CDC_WH';
SELECT "name", "size", "generation", "resource_constraint", "enable_query_acceleration",
       "auto_suspend", "auto_resume", "resource_monitor"
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

EXECUTE IMMEDIATE $$
DECLARE
    profile VARCHAR DEFAULT '<% cost_profile %>';
    gen VARCHAR;
    found INTEGER DEFAULT 0;
    ok INTEGER DEFAULT 0;
    bad_profile EXCEPTION (-20001, 'cost_profile must be baseline or optimized');
    at002_failed EXCEPTION (-20002, 'AT-002 failed: CDC_WH settings differ from the cost profile (see SHOW WAREHOUSES above)');
BEGIN
    IF (profile NOT IN ('baseline', 'optimized')) THEN
        RAISE bad_profile;
    END IF;
    gen := IFF(profile = 'optimized', '1', '2');
    SHOW WAREHOUSES LIKE 'CDC_WH';
    SELECT COUNT(*),
           COUNT_IF(TO_VARCHAR("generation") = :gen
                AND "resource_constraint" = 'STANDARD_GEN_' || :gen
                AND LOWER(TO_VARCHAR("enable_query_acceleration")) = 'false'
                AND "auto_suspend" = 60
                AND LOWER(TO_VARCHAR("auto_resume")) = 'true'
                AND UPPER(REPLACE("size", '-', '')) = 'XSMALL'
                AND "resource_monitor" = 'CDC_WH_MONITOR')
      INTO :found, :ok
      FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
    IF (found <> 1 OR ok <> 1) THEN
        RAISE at002_failed;
    END IF;
    RETURN 'AT-002 OK: CDC_WH generation ' || gen || ', QA off, XSMALL, 60 s, CDC_WH_MONITOR';
END;
$$;

-- AT-003 / REQ-03 — monitors (warehouse + account level, FREQUENCY = NEVER) ----
SHOW RESOURCE MONITORS LIKE 'CDC%';
SELECT "name", "credit_quota", "used_credits", "frequency", "level",
       "notify_at", "suspend_at", "suspend_immediately_at"
FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));

EXECUTE IMMEDIATE $$
DECLARE
    wh_ok INTEGER DEFAULT 0;
    account_ok INTEGER DEFAULT 0;
    at003_failed EXCEPTION (-20003, 'AT-003 failed: CDC_WH_MONITOR (WAREHOUSE) or CDC_ACCOUNT_MONITOR (ACCOUNT) missing, not NEVER, or without suspend thresholds');
BEGIN
    SHOW RESOURCE MONITORS LIKE 'CDC%';
    SELECT COUNT_IF("name" = 'CDC_WH_MONITOR' AND "level" = 'WAREHOUSE' AND "frequency" = 'NEVER'
                    AND "credit_quota" > 0 AND "suspend_at" IS NOT NULL AND "notify_at" IS NOT NULL),
           COUNT_IF("name" = 'CDC_ACCOUNT_MONITOR' AND "level" = 'ACCOUNT' AND "frequency" = 'NEVER'
                    AND "credit_quota" > 0 AND "suspend_at" IS NOT NULL AND "notify_at" IS NOT NULL)
      INTO :wh_ok, :account_ok
      FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
    IF (wh_ok <> 1 OR account_ok <> 1) THEN
        RAISE at003_failed;
    END IF;
    RETURN 'AT-003 OK: warehouse and account monitors, FREQUENCY = NEVER, notify + suspend set';
END;
$$;

-- AT-003 / Decision 5 — the serverless brake: custom budget on CDC_POC ---------
EXECUTE IMMEDIATE $$
DECLARE
    spending_limit NUMBER;
    tier VARCHAR;
    actions INTEGER DEFAULT 0;
    valid_actions INTEGER DEFAULT 0;
    budget_failed EXCEPTION (-20005, 'Budget check failed: CDC_BUDGET limit is not 10, tier is not TIER_1H, or its custom action is missing or invalid');
BEGIN
    CALL CDC_POC.CONFIG.CDC_BUDGET!GET_SPENDING_LIMIT();
    SELECT $1 INTO :spending_limit FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
    CALL CDC_POC.CONFIG.CDC_BUDGET!GET_REFRESH_TIER();
    SELECT $1 INTO :tier FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
    CALL CDC_POC.CONFIG.CDC_BUDGET!CONFIRM_CUSTOM_ACTIONS_ACCESS();
    SELECT COUNT(*), COUNT_IF("IS_VALID") INTO :actions, :valid_actions
      FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
    IF (spending_limit <> 10 OR tier <> 'TIER_1H' OR actions < 1 OR valid_actions <> actions) THEN
        RAISE budget_failed;
    END IF;
    RETURN 'Budget OK: limit 10, TIER_1H, ' || actions || ' valid custom action(s)';
END;
$$;

-- AT-004 / REQ-04 — gate tasks (only after the first pipeline apply) ----------
-- Profile optimized: no warehouse, timeout = gate_task_timeout_ms and failure
-- limit 3 set at task level. Profile baseline: CDC_WH and neither parameter
-- set at task level (Snowflake defaults, as v2).
EXECUTE IMMEDIATE $$
DECLARE
    check_pipeline VARCHAR DEFAULT '<% check_pipeline %>';
    profile VARCHAR DEFAULT '<% cost_profile %>';
    timeout_ms VARCHAR DEFAULT '<% gate_task_timeout_ms %>';
    tasks INTEGER DEFAULT 0;
    tasks_ok INTEGER DEFAULT 0;
    params_bad INTEGER DEFAULT 0;
    task_level INTEGER DEFAULT 0;
    timeout_ok INTEGER DEFAULT 0;
    failures_ok INTEGER DEFAULT 0;
    rs RESULTSET;
    at004_failed EXCEPTION (-20004, 'AT-004 failed: expected 10 started *_GATE_TASK in CDC_POC.BRONZE with the profile''s compute and parameters');
BEGIN
    IF (check_pipeline <> 'true') THEN
        RETURN 'AT-004 skipped: check_pipeline = ' || check_pipeline;
    END IF;
    SHOW TASKS IN SCHEMA CDC_POC.BRONZE;
    rs := (SELECT "name" AS task_name,
                  "state" AS task_state,
                  COALESCE("warehouse", '') AS task_warehouse
             FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
            WHERE ENDSWITH("name", '_GATE_TASK'));
    LET c1 CURSOR FOR rs;
    FOR rec IN c1 DO
        tasks := tasks + 1;
        IF (rec.task_state = 'started'
            AND rec.task_warehouse = IFF(profile = 'optimized', '', 'CDC_WH')) THEN
            tasks_ok := tasks_ok + 1;
        END IF;
        EXECUTE IMMEDIATE 'SHOW PARAMETERS IN TASK CDC_POC.BRONZE."' || rec.task_name || '"';
        SELECT COUNT_IF("key" IN ('USER_TASK_TIMEOUT_MS', 'SUSPEND_TASK_AFTER_NUM_FAILURES') AND "level" = 'TASK'),
               COUNT_IF("key" = 'USER_TASK_TIMEOUT_MS' AND "level" = 'TASK' AND "value" = :timeout_ms),
               COUNT_IF("key" = 'SUSPEND_TASK_AFTER_NUM_FAILURES' AND "level" = 'TASK' AND "value" = '3')
          INTO :task_level, :timeout_ok, :failures_ok
          FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()));
        IF ((profile = 'optimized' AND (timeout_ok <> 1 OR failures_ok <> 1))
            OR (profile = 'baseline' AND task_level <> 0)) THEN
            params_bad := params_bad + 1;
        END IF;
    END FOR;
    IF (tasks <> 10 OR tasks_ok <> 10 OR params_bad <> 0) THEN
        RAISE at004_failed;
    END IF;
    RETURN 'AT-004 OK: 10 started gate tasks, profile ' || profile;
END;
$$;

-- AT-004 idle criterion — informational, read after 1 h without load ---------
-- During the idle window every gate-task run should be a skipped evaluation
-- (WHEN false). Not asserted here: the window is a measurement step
-- (docs/measurement/PROTOCOL.md), and the nominal WHEN charge (F3) is read from
-- the metering views, not from this query.
SELECT name, state, COUNT(*) AS runs
FROM TABLE(CDC_POC.INFORMATION_SCHEMA.TASK_HISTORY(
    SCHEDULED_TIME_RANGE_START => DATEADD('hour', -1, CURRENT_TIMESTAMP()),
    RESULT_LIMIT => 10000))
WHERE ENDSWITH(name, '_GATE_TASK')
GROUP BY name, state
ORDER BY name, state;
