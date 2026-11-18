# CONFIG.SP_SUSPEND_GATE_TASKS — the budget's custom action (Decision 5, F7).
#
# Lives in platform, not pipeline, so scripts/budget.sql can reference it before
# the gate tasks exist (Decision 1): a SQL procedure resolves the tasks it alters
# at call time. It finds the gate tasks by name (*_GATE_TASK in BRONZE), so the
# domain list lives only in terraform/pipeline. It never resumes anything:
# resuming is a human step in docs/runbooks/budget-alert.md.
#
# Owner's rights: it runs as its owner (SYSADMIN), which owns or inherits the
# gate tasks. The grant to the SNOWFLAKE application that lets the budget call
# it is in scripts/budget.sql (manifest item 6).
#
# snowflake_procedure_sql is a preview resource (F11).

resource "snowflake_procedure_sql" "suspend_gate_tasks" {
  provider    = snowflake.sysadmin
  database    = snowflake_database.cdc.name
  schema      = snowflake_schema.cdc["CONFIG"].name
  name        = "SP_SUSPEND_GATE_TASKS"
  return_type = "VARCHAR"
  execute_as  = "OWNER"
  comment     = "Budget custom action: suspends every started *_GATE_TASK in BRONZE. Never resumes."

  procedure_definition = <<-SQL
    DECLARE
      suspended INTEGER DEFAULT 0;
      rs RESULTSET;
    BEGIN
      SHOW TASKS IN SCHEMA ${snowflake_database.cdc.name}.BRONZE;
      rs := (SELECT "name" AS task_name
               FROM TABLE(RESULT_SCAN(LAST_QUERY_ID()))
              WHERE ENDSWITH("name", '_GATE_TASK') AND "state" = 'started');
      LET c1 CURSOR FOR rs;
      FOR rec IN c1 DO
        EXECUTE IMMEDIATE 'ALTER TASK ${snowflake_database.cdc.name}.BRONZE."' || rec.task_name || '" SUSPEND';
        suspended := suspended + 1;
      END FOR;
      RETURN 'Suspended ' || suspended || ' gate task(s) in ${snowflake_database.cdc.name}.BRONZE';
    END;
  SQL
}
