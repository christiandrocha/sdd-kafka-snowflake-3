-- ------------------------------------------------------------------------
-- account_monitor.sql — REQ-01 exception 3 (DESIGN Decision 9, F12, F14).
--
-- Assigns the Terraform-created CDC_ACCOUNT_MONITOR (terraform/platform/
-- monitors.tf) to the account, so every warehouse — CDC_WH, CDC_CI_WH and
-- COMPUTE_WH — is capped for the whole trial.
--
-- Why SQL and not Terraform: the provider can only do this through
-- snowflake_current_account, a preview resource that does not detect external
-- changes (F12); kept as SQL by owner decision 2026-11-18. Future alternative:
-- move it to snowflake_current_account once it leaves preview.
--
-- Why ACCOUNTADMIN: "Only users with the ACCOUNTADMIN role can set a resource
-- monitor to monitor the account" (Snowflake docs, F14).
--
-- RUN BY: CI, after every apply on `main`, as TERRAFORM_SVC:
--   snow sql -f scripts/account_monitor.sql
-- No warehouse needed (ALTER ACCOUNT and SHOW are metadata operations).
--
-- IDEMPOTENT: setting the same monitor again is a no-op.
-- ------------------------------------------------------------------------

USE ROLE ACCOUNTADMIN;

ALTER ACCOUNT SET RESOURCE_MONITOR = CDC_ACCOUNT_MONITOR;

-- Read-back (expected: level = ACCOUNT) — AT-003 is checked by verify_governance.sql.
SHOW RESOURCE MONITORS LIKE 'CDC_ACCOUNT_MONITOR';
