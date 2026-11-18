# CONFIG.SP_GATE_DOMAIN — ADR-0019 semantics, unchanged from v2
# (scripts/streams_and_tasks.sql, deleted in manifest item 8):
#   1. record that the domain has new Bronze rows (PENDING_RUNS, read by the
#      Dagster sensor);
#   2. consume the stream with a DML (INSERT ... SELECT FROM <stream>), which
#      advances its offset so SYSTEM$STREAM_HAS_DATA turns false again.
# Owner's rights, owned by SYSADMIN like the tasks that call it.
# snowflake_procedure_sql is a preview resource (F11).

resource "snowflake_procedure_sql" "gate_domain" {
  provider    = snowflake.sysadmin
  database    = var.database_name
  schema      = "CONFIG"
  name        = "SP_GATE_DOMAIN"
  return_type = "VARCHAR"
  execute_as  = "OWNER"
  comment     = "Gate task body (ADR-0019): PENDING_RUNS row + stream consumption."

  arguments {
    arg_name      = "STREAM_FQN"
    arg_data_type = "VARCHAR"
  }
  arguments {
    arg_name      = "DOMAIN_NAME"
    arg_data_type = "VARCHAR"
  }

  procedure_definition = <<-SQL
    BEGIN
      INSERT INTO ${var.database_name}.CONFIG.PENDING_RUNS (DOMAIN, DETECTED_AT, CONSUMED)
        SELECT :DOMAIN_NAME, CURRENT_TIMESTAMP(), FALSE;
      EXECUTE IMMEDIATE
        'INSERT INTO ${var.database_name}.CONFIG.STREAM_CONSUMPTION_LOG (DOMAIN, ROWS_SEEN, CONSUMED_AT) ' ||
        'SELECT ''' || :DOMAIN_NAME || ''', COUNT(*), CURRENT_TIMESTAMP() FROM ' || :STREAM_FQN;
      RETURN 'OK: ' || :DOMAIN_NAME;
    END;
  SQL
}
