-- ------------------------------------------------------------------------
-- budget.sql — custom budget on CDC_POC with an automatic brake.
-- REQ-01 exception 2, REQ-03 (DESIGN Decisions 5, 8, 9; F7, F8, F13).
--
-- WHY SQL: the provider has no resource for budgets or custom actions (F13).
--
-- WHAT IT DOES
--   * Budget CDC_POC.CONFIG.CDC_BUDGET, 10 credits / calendar month, scoped to
--     the CDC_POC database: serverless gate tasks and Snowpipe Streaming, which
--     resource monitors cannot see (F2).
--   * Refresh tier TIER_1H (owner decision 2026-11-18): ~1 h detection delay
--     instead of up to 6.5 h, at a budget cost 12x the default (F8).
--   * E-mail to the owner when projected spend reaches 100%.
--   * Custom action on ACTUAL spend at 100%: CONFIG.SP_SUSPEND_GATE_TASKS().
--   * No cycle-start action (owner decision 2026-11-18): nothing resumes the
--     gate tasks automatically. Resuming is a human step,
--     docs/runbooks/budget-alert.md.
--
-- ROLES: SYSADMIN only for the three grants to the SNOWFLAKE application
-- (it owns the database, schema and procedure); everything else as
-- CDC_BUDGET_ADMIN, created and granted by terraform/platform — never
-- ACCOUNTADMIN (owner decision 2026-11-18).
--
-- RUN BY: CI, after every apply on `main`, as TERRAFORM_SVC:
--   snow sql -f scripts/budget.sql -D "notify_email=$BUDGET_NOTIFY_EMAIL"
-- The address is personal data and never lives in this repository (D1, public
-- repo): it comes from a variable of the `snowflake-dev` GitHub environment and
-- must be verified in Snowflake. Warehouse CDC_CI_WH, never CDC_WH.
--
-- IDEMPOTENT (Build checklist B5): IF NOT EXISTS on the budget; setters are
-- absolute; the database is added only if not already in scope; custom actions
-- are removed and re-added. Re-adding resets the action's once-a-month guard,
-- so after a push to `main` an over-limit budget suspends the tasks again —
-- the intended direction. The grants to SNOWFLAKE are repeated every run
-- because Snowflake drops them whenever Terraform replaces the procedure.
-- ------------------------------------------------------------------------

-- 1. Let the budget call the procedure (Custom actions for budgets) ----------
USE ROLE SYSADMIN;
GRANT USAGE ON DATABASE CDC_POC                                 TO APPLICATION SNOWFLAKE;
GRANT USAGE ON SCHEMA CDC_POC.CONFIG                            TO APPLICATION SNOWFLAKE;
GRANT USAGE ON PROCEDURE CDC_POC.CONFIG.SP_SUSPEND_GATE_TASKS() TO APPLICATION SNOWFLAKE;

-- 2. Budget instance and settings --------------------------------------------
USE ROLE CDC_BUDGET_ADMIN;
USE WAREHOUSE CDC_CI_WH;
USE SCHEMA CDC_POC.CONFIG;

CREATE SNOWFLAKE.CORE.BUDGET IF NOT EXISTS CDC_POC.CONFIG.CDC_BUDGET()
    COMMENT = 'Serverless spend in CDC_POC (gate tasks, Snowpipe Streaming). Managed by scripts/budget.sql.';

CALL CDC_POC.CONFIG.CDC_BUDGET!SET_SPENDING_LIMIT(10);
CALL CDC_POC.CONFIG.CDC_BUDGET!SET_REFRESH_TIER('TIER_1H');
CALL CDC_POC.CONFIG.CDC_BUDGET!SET_EMAIL_NOTIFICATIONS('<% notify_email %>');
CALL CDC_POC.CONFIG.CDC_BUDGET!SET_NOTIFICATION_THRESHOLD(100);

-- 3. Scope: the CDC_POC database, added only if missing ----------------------
-- ADD_RESOURCE's behaviour on an object already in the same budget is not
-- documented, so check GET_BUDGET_SCOPE first.
EXECUTE IMMEDIATE $$
DECLARE
    linked INTEGER DEFAULT 0;
    ref VARCHAR;
BEGIN
    CALL CDC_POC.CONFIG.CDC_BUDGET!GET_BUDGET_SCOPE();
    SELECT COUNT(*) INTO :linked
      FROM TABLE(RESULT_SCAN(LAST_QUERY_ID())) AS s,
           LATERAL FLATTEN(input => PARSE_JSON(TO_VARCHAR(s.$1)):resources) AS r
     WHERE r.value:resourceDomain::VARCHAR = 'DATABASE'
       AND r.value:resourceName::VARCHAR = 'CDC_POC';
    IF (linked > 0) THEN
        RETURN 'CDC_POC already in budget scope';
    END IF;
    ref := (SELECT SYSTEM$REFERENCE('DATABASE', 'CDC_POC', 'SESSION', 'applybudget'));
    CALL CDC_POC.CONFIG.CDC_BUDGET!ADD_RESOURCE(:ref);
    RETURN 'CDC_POC added to budget scope';
END;
$$;

-- 4. Actions: the suspend brake at 100% of actual spend; no cycle-start action
CALL CDC_POC.CONFIG.CDC_BUDGET!REMOVE_CUSTOM_ACTIONS();
CALL CDC_POC.CONFIG.CDC_BUDGET!ADD_CUSTOM_ACTION(
    SYSTEM$REFERENCE('PROCEDURE', 'CDC_POC.CONFIG.SP_SUSPEND_GATE_TASKS()', 'SESSION', 'USAGE'),
    ARRAY_CONSTRUCT(),
    'ACTUAL',
    100);
CALL CDC_POC.CONFIG.CDC_BUDGET!REMOVE_CYCLE_START_ACTION();

-- 5. Read-back (AT-003; verify_governance.sql repeats the checks) ------------
CALL CDC_POC.CONFIG.CDC_BUDGET!GET_SPENDING_LIMIT();            -- 10
CALL CDC_POC.CONFIG.CDC_BUDGET!GET_REFRESH_TIER();              -- TIER_1H
CALL CDC_POC.CONFIG.CDC_BUDGET!GET_BUDGET_SCOPE();              -- resources: CDC_POC
CALL CDC_POC.CONFIG.CDC_BUDGET!GET_CUSTOM_ACTIONS();            -- one ACTUAL 100 action
CALL CDC_POC.CONFIG.CDC_BUDGET!CONFIRM_CUSTOM_ACTIONS_ACCESS(); -- IS_VALID = TRUE
CALL CDC_POC.CONFIG.CDC_BUDGET!GET_CYCLE_START_ACTION();        -- none
