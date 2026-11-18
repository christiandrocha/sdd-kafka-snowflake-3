-- ------------------------------------------------------------------------
-- 00_terraform_bootstrap.sql
-- Terraform's own identities. REQ-01 exception 1 (DESIGN_COST_GOVERNANCE,
-- Decision 9): the only objects in v3 created by hand.
--
-- WHO RUNS IT: a human, once per account, in Snowsight, as ACCOUNTADMIN.
-- Agents never run it (Constitution R1).
--
-- WHAT IT CREATES
--   TERRAFORM_SVC       service user for `apply` (CI environment `snowflake-dev`,
--                       required reviewer). Granted SYSADMIN, SECURITYADMIN and
--                       ACCOUNTADMIN; the provider aliases in
--                       terraform/platform/providers.tf pick the least role per
--                       resource, and ACCOUNTADMIN only for the resources named
--                       in Decision 9.
--   TERRAFORM_PLAN_ROLE read-only role for PR `plan` refreshes. It starts with no
--                       privileges: Terraform grants it USAGE/MONITOR on the
--                       objects it creates (terraform/platform/grants.tf).
--   TERRAFORM_PLAN_SVC  service user holding TERRAFORM_PLAN_ROLE (CI environment
--                       `snowflake-plan`, no reviewer). Agents use only this one.
--
-- KEYS: generate each key pair on the owner's machine, paste only the PUBLIC key
-- (one line, no BEGIN/END) below. Private keys go to the GitHub environment
-- secrets and nowhere else. Never commit this file with a real key filled in —
-- edit a local copy.
--
-- SAFE TO RE-RUN: every statement is IF NOT EXISTS or an idempotent GRANT.
-- ------------------------------------------------------------------------

USE ROLE ACCOUNTADMIN;
SELECT CURRENT_ROLE() AS active_role, CURRENT_ACCOUNT() AS account;

-- Roles -------------------------------------------------------------------
USE ROLE USERADMIN;
CREATE ROLE IF NOT EXISTS TERRAFORM_PLAN_ROLE
    COMMENT = 'Read-only role for terraform plan in PRs. Privileges granted by terraform/platform.';

-- Users -------------------------------------------------------------------
CREATE USER IF NOT EXISTS TERRAFORM_SVC
    TYPE           = SERVICE
    DEFAULT_ROLE   = SYSADMIN
    RSA_PUBLIC_KEY = '<PASTE_TERRAFORM_SVC_PUBLIC_KEY>'
    COMMENT        = 'Terraform apply (CI environment snowflake-dev). DESIGN_COST_GOVERNANCE Decision 9.';

CREATE USER IF NOT EXISTS TERRAFORM_PLAN_SVC
    TYPE           = SERVICE
    DEFAULT_ROLE   = TERRAFORM_PLAN_ROLE
    RSA_PUBLIC_KEY = '<PASTE_TERRAFORM_PLAN_SVC_PUBLIC_KEY>'
    COMMENT        = 'Terraform plan in PRs (CI environment snowflake-plan). Read-only.';

-- Grants ------------------------------------------------------------------
USE ROLE SECURITYADMIN;
GRANT ROLE SYSADMIN            TO USER TERRAFORM_SVC;
GRANT ROLE SECURITYADMIN       TO USER TERRAFORM_SVC;
GRANT ROLE TERRAFORM_PLAN_ROLE TO USER TERRAFORM_PLAN_SVC;
-- Custom roles hang under SYSADMIN (Snowflake's recommended hierarchy).
GRANT ROLE TERRAFORM_PLAN_ROLE TO ROLE SYSADMIN;

USE ROLE ACCOUNTADMIN;
-- Needed for resource monitors, the CDC_WH monitor assignment and the
-- SNOWFLAKE database-role grants (DESIGN Decision 9, named exception; F14).
GRANT ROLE ACCOUNTADMIN TO USER TERRAFORM_SVC;

-- Read-back (expected: both users TYPE = SERVICE, has_rsa_public_key = true) --
SHOW USERS LIKE 'TERRAFORM%';
SHOW GRANTS TO USER TERRAFORM_SVC;       -- SYSADMIN, SECURITYADMIN, ACCOUNTADMIN
SHOW GRANTS TO USER TERRAFORM_PLAN_SVC;  -- TERRAFORM_PLAN_ROLE only
