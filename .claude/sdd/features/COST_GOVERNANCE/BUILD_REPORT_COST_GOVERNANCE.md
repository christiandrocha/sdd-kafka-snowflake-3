# BUILD REPORT: Cost Governance 2.0 (COST_GOVERNANCE)

> Implementation report for COST_GOVERNANCE. One section per `/sdd-build` run; append, never rewrite.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COST_GOVERNANCE |
| **Date** | 2026-11-18 |
| **Author** | build-agent (Claude Code), owner Christian |
| **DEFINE** | [DEFINE_COST_GOVERNANCE.md](./DEFINE_COST_GOVERNANCE.md) — v1.4 |
| **DESIGN** | [DESIGN_COST_GOVERNANCE.md](./DESIGN_COST_GOVERNANCE.md) — v1.4 |
| **Status** | In Progress — items 1–14 and 16–18 built and merged to `main` (#1–#6, last 2026-11-23); 15 drafted (run 7) and merged (#10, 2026-11-23), owner edits allowed until window A starts (2026-11-25 00:00 UTC); 20 built (run 8) and merged (#14, 2026-11-23); 21 drafted (run 9) and merged (#16, 2026-11-23); 19, 22 pending (owner-authored / shared); no apply yet |

---

## Run 1 — 2026-11-18 — manifest items 1–4

Branch `feat/cost-governance-items-1-4`. Requirements: REQ-01, REQ-02, REQ-03 (foundation for REQ-04
and REQ-08).

### Summary

| Metric | Value |
|--------|-------|
| **Manifest items** | 1, 2, 3, 4 of 22 |
| **Files created** | 16 (1 SQL, 13 `.tf`, 1 `.tfvars`, 1 test) + `.terraform.lock.hcl` |
| **Lines** | ~1,000 (incl. comments) |
| **Terraform resource blocks** | 28 |
| **Tests** | 41/41 pass |
| **Agents used** | 0 (direct) |

### What happened first: DESIGN 1.0 → 1.1

Before writing code, the provider schema (2.23.0) and Snowflake docs were checked. Pattern 2
(warehouse on the `sysadmin` alias with `resource_monitor`) **could not apply**: only ACCOUNTADMIN
can assign a warehouse to a monitor (F14). The Build stopped, reported, and the owner decided
(2026-11-18):

1. `CDC_WH` under ACCOUNTADMIN, with the alias limited to named resources and never used by a PR
   plan (Decision 9 named exception).
2. Account-level monitor stays CI SQL (exception 3); `snowflake_current_account` recorded as the
   future alternative (F12).

DESIGN 1.1 (F6 revised, F11–F14, Decisions 4/9/11, Pattern 2, manifest 2/6) was reviewed by the
owner as a diff and marked Ready for Build. Not reviewed by an independent session.

### Files

| # | File | Notes |
|---|------|-------|
| 1 | `scripts/00_terraform_bootstrap.sql` | `TERRAFORM_SVC` (SYSADMIN + SECURITYADMIN + ACCOUNTADMIN), `TERRAFORM_PLAN_ROLE` (no privileges; Terraform grants them), `TERRAFORM_PLAN_SVC`. Public-key placeholders. Never run by an agent. |
| 2 | `terraform/platform/versions.tf` | Terraform ≥ 1.11, provider `>= 2.7.0, < 3.0.0`; lock file pins **2.23.0** |
| 2 | `terraform/platform/providers.tf` | Aliases `sysadmin` / `securityadmin` / `accountadmin`, each `coalesce(var.plan_role, "<ROLE>")`; JWT auth from env; preview features `snowflake_table_resource`, `snowflake_procedure_sql_resource` (F11). No default provider. |
| 2 | `terraform/platform/backend.tf` | S3, `use_lockfile = true`, `encrypt = true`; bucket/region via `-backend-config` |
| 3 | `terraform/platform/variables.tf` | v2 names as defaults; account identity, owner user, quotas without default; public keys default `null` |
| 3 | `terraform/platform/profiles.tf` | Pattern 1 verbatim |
| 3 | `terraform/env/dev.tfvars` | `cost_profile = "optimized"`, org/account, owner user, 25 / 40 credits |
| 4 | `terraform/platform/database.tf` | `CDC_POC` (retention 1 day, no PUBLIC) + BRONZE/SILVER/GOLD/CONFIG |
| 4 | `terraform/platform/config_tables.tf` | 5 CONFIG tables in canonical types; `PENDING_RUNS.CONSUMED_RUN_KEY` and `PROCESSING_LOG.RUN_KEY` added (Decision 7) |
| 4 | `terraform/platform/warehouse.tf` | Pattern 2 as revised: `accountadmin` alias, `generation` from profile, QA off, XSMALL, 60 s, monitor `CDC_WH_MONITOR` |
| 4 | `terraform/platform/monitors.tf` | `CDC_WH_MONITOR` 25 cr (notify 50/75, suspend 90, immediate 100) · `CDC_ACCOUNT_MONITOR` 40 cr (notify 50/75/90, suspend 100) · both `NEVER`, notify the owner |
| 4 | `terraform/platform/roles.tf` | `CDC_ROLE`, `CDC_ROLE_RO`, `CDC_GOVERNANCE_RO`, each granted to SYSADMIN |
| 4 | `terraform/platform/users.tf` | 3 service users (`snowflake_service_user`), role grants, governance role → owner |
| 4 | `terraform/platform/grants.tf` | v2 grants ported; plan-role read grants (MONITOR/USAGE/REFERENCES); SNOWFLAKE database roles and monitor MONITOR on `accountadmin` |
| 4 | `terraform/platform/procedures.tf` | `CONFIG.SP_SUSPEND_GATE_TASKS()` — owner's rights; suspends every started `*_GATE_TASK` in BRONZE found via `SHOW TASKS`; never resumes |
| — | `tests/unit/test_terraform_providers.py` | Static guards: every resource names an alias; `accountadmin` used by exactly the Decision 9 list (mutation-checked: moving `snowflake_database.cdc` to it fails the test); aliases fall back to `plan_role`; `cost_profile` has no default; warehouse sets `generation`, never `resource_constraint`; monitors `NEVER`; no private key in Terraform |

Shared files touched (one writer at a time): `CLAUDE.md` (`_V3` row replaced — Decision 3; Terraform
rows added), `.gitignore` (Terraform artifacts; not in the ownership table). SDD files: DESIGN 1.1,
DEFINE status line, `_index.md` (feature row, Day 2 row), package regenerated.

### Commands and results

| Command | Result |
|---------|--------|
| `terraform providers schema -json` (provider 2.23.0, scratch dir) | Source for every attribute used; F11–F14 |
| `terraform -chdir=terraform fmt -check -recursive` | ✅ exit 0 |
| `terraform -chdir=terraform/platform init -backend=false` + `validate` | ✅ "The configuration is valid." |
| `terraform console -var-file=terraform/env/dev.tfvars` (backend-less copy) | ✅ `local.profile` = Gen1/serverless (optimized), Gen2/warehouse (baseline); invalid profile rejected; `plan_role` set → all three aliases resolve to `TERRAFORM_PLAN_ROLE` |
| `ruff check .` | ✅ All checks passed |
| `pytest tests/unit -q` | ✅ 41 passed |
| `terraform plan` | ⏭️ Not run: no plan identity exists yet (bootstrap not run). Day 3, CI. |

Terraform 1.11.4 was downloaded to the session scratchpad for these checks (owner-authorized); it
is not installed in the repo or the system.

### Deviations from DESIGN 1.1

| Deviation | Reason | Impact |
|-----------|--------|--------|
| New test file `tests/unit/test_terraform_providers.py` (not in the manifest) | Makes the owner's condition "accountadmin only on named resources, never in PR plans" a failing test rather than a review habit | None on scope; CI picks it up when item 17 adds `pytest tests/unit` |
| Future grants are database-level only (v2 also had CONFIG schema-level future grants) | In Snowflake, schema-level future grants take precedence over database-level ones, which silently dropped `CDC_ROLE_RO`'s future SELECT in CONFIG in v2 | `CDC_ROLE` future privileges in CONFIG become SELECT/INSERT/UPDATE/DELETE (database level) instead of SELECT/INSERT/UPDATE |
| Custom roles granted to SYSADMIN (v2 did not) | Snowflake's recommended hierarchy; lets SYSADMIN manage connector-created Bronze tables | None on the A/B |
| `EXECUTE TASK` (v2 grant) not in platform | Belongs with the task owner role, decided in `terraform/pipeline` (item 7), together with `EXECUTE MANAGED TASK` for profile B | Gate tasks cannot run until item 7 — they do not exist until then anyway |
| Decision 9 list item "SNOWFLAKE database roles — to be confirmed" | Confirmed: "Only users with the OWNERSHIP role can grant SNOWFLAKE database roles" (Snowflake docs, *SNOWFLAKE database roles*) — stays on `accountadmin` | DESIGN text still says "to be confirmed"; fix at the next DESIGN revision |

### Open issues

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O1 | **Credit price** (`_index` open item 7) — still unread; 25/40 kept in `dev.tfvars` | Before the first apply (Day 3) | Christian |
| O2 | **Probe P1** (DESIGN Appendix) — confirms F14 on this account | Before the first apply | Christian |
| O3 | `owner_user_name = "CHRISTIANDROCHA"` is v2's user name; confirm it exists on `GWHUBCF-QQ53235` with a verified e-mail (monitor notifications) | Before the first apply | Christian |
| O4 | Service users' public keys: set `TF_VAR_dagster_rsa_public_key` etc. as variables of the `snowflake-dev` environment (not secrets) | Before the stack connects (Day 5) | Christian |
| O5 | AT-001 risks to watch on the first second-plan: column `DEFAULT CURRENT_TIMESTAMP()` read back as a cast; `IDENTITY` and `NUMBER(38,0)` normalization; `start_timestamp = IMMEDIATELY` | Day 3 | build-agent |
| O6 | `TERRAFORM_PLAN_ROLE` refresh coverage unproven for users (MONITOR on USER), grants (`SHOW GRANTS TO ROLE`) and the procedure — Decision 9 fallback applies | Day 3 | build-agent |
| O7 | `SP_SUSPEND_GATE_TASKS` relies on `SHOW` + `RESULT_SCAN` inside an owner's-rights procedure; verify with a call once the tasks exist (dry run, Day 7) | Day 7 | build-agent |
| O8 | Old scripts (`00_account_bootstrap.sql`, `bootstrap_config.sql`, `snowflake_setup.sql`, `create_readonly_role.sql`, `streams_and_tasks.sql`) still in the repo and still define the same objects | Item 8 | build-agent |

### Build checklist status

| # | Status after run 1 |
|---|--------------------|
| B1 | Open — `profiles.tf` written for `platform`; `pipeline` copy and two-root `main` job in items 7 and 16 |
| B2 | Open (Day 5) |
| B3 | Open (Day 3) |
| B4 | Open — format known (F6); `verify_governance.sql` is item 9 |
| B5 | Open (before Day 7) |

### Acceptance tests

| ID | Status | Evidence |
|----|--------|----------|
| AT-001 | ⏳ Pending | Needs the first CI apply (Day 3) |
| AT-002 | ⏳ Pending | Config sets `generation = "1"` in `optimized`; verified on the account by item 9 |
| AT-003 | ⏳ Pending | Monitors defined; account assignment is item 6 |

---

## Run 2 — 2026-11-18 — manifest items 5–6

Branch `feat/cost-governance-items-5-6`, stacked on `feat/cost-governance-items-1-4` (PR #1 still
open). Requirements: REQ-01 (exceptions 2 and 3), REQ-03.

### DESIGN 1.1 → 1.2 (owner decisions, before code)

Docs read first: *Custom actions for budgets*, `CREATE BUDGET`, `ADD_CUSTOM_ACTION`,
`SET_REFRESH_TIER`, `SET_CYCLE_START_ACTION`, `SET_EMAIL_NOTIFICATIONS`, `ADD_RESOURCE`,
`GET_BUDGET_SCOPE`, `CONFIRM_CUSTOM_ACTIONS_ACCESS`, *Notifications for budgets*, Snowflake CLI
`snow sql` templating (all read 2026-11-18). Owner decisions:

1. Refresh tier **`TIER_1H`**. Official numbers replace F8's third-party source: default `TIER_6H`
   is "up to 6.5 hours"; `TIER_1H` is 1 h at a budget cost "12 times higher" (absolute cost not
   stated).
2. **No cycle-start action.** `REMOVE_CYCLE_START_ACTION` keeps it that way. Resume stays manual.
3. **`budget.sql` runs as a dedicated `CDC_BUDGET_ADMIN` role**, not ACCOUNTADMIN. Its
   `SNOWFLAKE.BUDGET_CREATOR` grant joins the Decision 9 named list (only the owner grants
   SNOWFLAKE database roles).
4. **New `CDC_CI_WH`** for the CI SQL steps. The DESIGN did not say which warehouse they use; on
   `CDC_WH`, the 00:00 UTC switch merge would resume the pipeline warehouse inside the windows
   (validity rule).

Decision 5/8 worst case recomputed: ~1.5 credits overshoot per month before the action fires
(was ~12), ~63 credits pathological total (was ~84 / ~62). DESIGN 1.2 was **not** shown to the
owner as a diff before this Build; the decisions were. Review the DESIGN diff in this PR.

### Files

| # | File | Notes |
|---|------|-------|
| 5 | `scripts/bootstrap_config.sql` → `scripts/seed_config.sql` | `git mv` + rewrite: insert-only MERGE of the 10 Tier-1 domains; DDL, grants and the Tier-2 `UPDATE` removed (DDL/grants are in Terraform; Tier-2 rows never exist on a new account). `notes` translated to English. `SYSADMIN` on `CDC_CI_WH`. |
| 6 | `scripts/account_monitor.sql` | `ALTER ACCOUNT SET RESOURCE_MONITOR = CDC_ACCOUNT_MONITOR` + `SHOW` read-back. ACCOUNTADMIN (required, F14). No warehouse. |
| 6 | `scripts/budget.sql` | Grants to `APPLICATION SNOWFLAKE` (SYSADMIN), then as `CDC_BUDGET_ADMIN`: `CREATE … BUDGET IF NOT EXISTS CDC_POC.CONFIG.CDC_BUDGET`, limit 10, `TIER_1H`, e-mail from `<% notify_email %>`, notification threshold 100, `ADD_RESOURCE(CDC_POC)` only if `GET_BUDGET_SCOPE` lacks it, `REMOVE_CUSTOM_ACTIONS` + `ADD_CUSTOM_ACTION(SP_SUSPEND_GATE_TASKS(), 'ACTUAL', 100)`, `REMOVE_CYCLE_START_ACTION`, six read-back calls incl. `CONFIRM_CUSTOM_ACTIONS_ACCESS`. |
| 6 | `terraform/platform/{variables,roles,grants,warehouse}.tf` | Changes item-4 files (same feature): role `CDC_BUDGET_ADMIN` (→ SYSADMIN, → `TERRAFORM_SVC`); grants `APPLYBUDGET`+USAGE on `CDC_POC`, `CREATE SNOWFLAKE.CORE.BUDGET`+USAGE on CONFIG, USAGE on the procedure and on `CDC_CI_WH`; `SNOWFLAKE.BUDGET_CREATOR` on `accountadmin`; warehouse `CDC_CI_WH` (XSMALL, Gen1, QA off, 60 s, `sysadmin`); plan role MONITOR on both warehouses. |
| — | `tests/unit/test_sql_scripts.py` | 20 checks: no `DROP`/`TRUNCATE`/`DELETE`/`CREATE OR REPLACE`/`UPDATE`/`RESUME`; `USE WAREHOUSE` only `CDC_CI_WH`; no e-mail address and no `&` (legacy CLI templating) in the scripts; ACCOUNTADMIN only in `account_monitor.sql`; names agree with Terraform; seed = exactly the 10 Tier-1 domains, insert-only; budget idempotency order and DESIGN values. |
| — | `tests/unit/test_terraform_providers.py` | Allowlist + `budget_creator`; `CDC_CI_WH` is Gen1 and not on the pipeline monitor. |

### Commands and results

| Command | Result |
|---------|--------|
| `terraform -chdir=terraform fmt -check -recursive` | ✅ exit 0 |
| `terraform -chdir=terraform/platform validate` | ✅ valid |
| `ruff check .` | ✅ All checks passed |
| `pytest tests/unit -q` | ✅ 69 passed |
| `snow sql` / `terraform plan` | ⏭️ Not run: no identities on the account yet; first run in CI (item 16) |

### Deviations from DESIGN 1.2

| Deviation | Reason | Impact |
|-----------|--------|--------|
| `SET_NOTIFICATION_THRESHOLD(100)` (DESIGN: "notify … at 100%") | Default is 110% of **projected** spend; 100 aligns the e-mail with the action threshold | E-mail on projected ≥ 100%; action on actual ≥ 100% |
| `GET_BUDGET_SCOPE` (not the deprecated `GET_LINKED_RESOURCES`) to test scope | Docs mark `GET_LINKED_RESOURCES` deprecated | — |

### Open issues (new)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O9 | Budgets / custom actions on a **trial** account: not stated in the docs (B2). First CI run of `budget.sql` answers it; if unavailable, Decision 5's ceiling is timeout + failure limit + task-state check | Day 3–5 | build-agent |
| O10 | Unverified on the account: `CALL <budget>!<method>` and `RESULT_SCAN` inside `EXECUTE IMMEDIATE`; `GET_BUDGET_SCOPE` return type (parsed with `PARSE_JSON(TO_VARCHAR(…))`); `REMOVE_CYCLE_START_ACTION` / `REMOVE_CUSTOM_ACTIONS` when nothing is set (if they error, guard them — never swallow errors) | First CI run | build-agent |
| O11 | `CREATE SNOWFLAKE.CORE.BUDGET` and `APPLYBUDGET` as provider privilege strings are validated only at apply | Day 3 | build-agent |
| O12 | `BUDGET_NOTIFY_EMAIL` variable in the `snowflake-dev` environment; address verified in Snowflake (`SET_EMAIL_NOTIFICATIONS` fails otherwise) | Before the first `main` run | Christian |
| O13 | `TIER_1H` budget cost: measure in the dry run (`METERING_HISTORY` by service type) and report it | Day 7 | Christian |
| O14 | README still lists `bootstrap_config.sql` and the v2 order of scripts | Item 22 (Day 14) | Christian |
| O15 | DESIGN Decision 11 still says the CI SQL steps run in the order seed → account_monitor → budget, which is what the scripts assume; `CDC_CI_WH` must exist first (it does: platform apply precedes them) | Item 16 | build-agent |

### Build checklist status after run 2

| # | Status |
|---|--------|
| B2 | **Partially closed:** refresh delay from official docs (6.5 h / 1 h, TIER_1H chosen); worst case recomputed. Open: timeout vs `suspend_task_after_num_failures`; trial availability (O9) |
| B5 | **Partially closed:** `budget.sql` idempotent by construction and by test. Open: `PROTOCOL.md` items |
| B1, B3, B4 | Unchanged |

---

## Run 3 — 2026-11-18 — manifest items 7–9

Branch `feat/cost-governance-items-7-9` (from `main`, after #1 and #2). Requirements: REQ-04,
REQ-01/02/03 (verification). DESIGN 1.2, no revision in this run. Build checklist B1 (code side)
and B4 closed.

### Owner decisions (2026-11-18)

1. `EXECUTE TASK` / `EXECUTE MANAGED TASK` granted by **`securityadmin`**: a **hypothesis to
   validate at the Day 3 apply**. The DESIGN 1.5 text below (numbered 1.3 when written) is ready in case it has to move to
   `accountadmin`.
2. `create_readonly_role.sql` deleted too (deviation from item 8), after a grep.
3. `verify_governance.sql` runs as **`TERRAFORM_PLAN_ROLE`**, with three grants: USAGE on
   `CDC_CI_WH`, MONITOR on future tasks, and the budget's VIEWER instance role.
4. A static test that SYSADMIN's USAGE on `CDC_WH` exists before the tasks. `gate_task_timeout_ms`
   stays a variable, with the open item recorded.

### What the docs settled, and what they did not

| Question | Answer | Source |
|----------|--------|--------|
| Who can grant `EXECUTE TASK` / `EXECUTE MANAGED TASK`? | **Not stated** by Snowflake. `GRANT <privileges>` covers object grants only (MANAGE GRANTS, ownership, WITH GRANT OPTION). The task docs' example uses ACCOUNTADMIN. A CIS benchmark summary (third party) says account-level grants are "implicitly reserved for the ACCOUNTADMIN and SECURITYADMIN roles", which supports the hypothesis without proving it. | [`GRANT <privileges>`](https://docs.snowflake.com/en/sql-reference/sql/grant-privilege); [Introduction to tasks](https://docs.snowflake.com/en/user-guide/tasks-intro); [Tenable CIS 2.2](https://tenable.com/audits/items/CIS_Snowflake_Foundations_v1.0.0_L1.audit:05abcfa959c6558c8c4c8d6d83b8769c) |
| Does `SHOW TASKS` show the tasks to a non-owner? | Only to "a role with either the MONITOR or OPERATE privilege on a task" (or the owner). Future grants do not cover existing objects, so the plan role gets **both** a future MONITOR grant (platform) **and** one per task, granted by SYSADMIN as owner (pipeline). | [`SHOW TASKS`](https://docs.snowflake.com/en/sql-reference/sql/show-tasks) |
| Does the budget instance role `VIEWER` exist with that name? | Yes: `GRANT SNOWFLAKE.CORE.BUDGET ROLE budgets_db.budgets_schema.my_budget!VIEWER TO ROLE budget_monitor;`, plus USAGE on the database and schema (the plan role already has both). | [*Monitor budgets*](https://docs.snowflake.com/en/user-guide/budgets/monitor) |
| What can `VIEWER` call? | `CONFIRM_CUSTOM_ACTIONS_ACCESS` accepts "any instance role". For `GET_SPENDING_LIMIT` / `GET_REFRESH_TIER`, the docs do not say → O19 | [`CONFIRM_CUSTOM_ACTIONS_ACCESS`](https://docs.snowflake.com/en/sql-reference/classes/budget/methods/confirm_custom_actions_access) |

`grep` for `create_readonly_role` before deleting it: README prose (item 22), the other deleted
scripts, and Terraform comments. No workflow and no runbook calls it (`docs/runbooks/` does not
exist yet).

### Files

| # | File | Notes |
|---|------|-------|
| 7 | `terraform/pipeline/{versions,profiles}.tf` | Byte-identical copies of platform's (B1; tested) |
| 7 | `terraform/pipeline/backend.tf` | Same bucket, key `…/pipeline.tfstate`, native lockfile |
| 7 | `terraform/pipeline/providers.tf` | **Only** the `sysadmin` alias, `coalesce(var.plan_role, "SYSADMIN")`; preview feature `snowflake_procedure_sql_resource` |
| 7 | `terraform/pipeline/variables.tf` | `gate_domains` (the 10 connector table names), `gate_task_timeout_ms` (default 10 000, validation ≥ 10 000, **PROVISIONAL** until the dry run), names, plan role |
| 7 | `terraform/pipeline/procedures.tf` | `CONFIG.SP_GATE_DOMAIN(STREAM_FQN, DOMAIN_NAME)`, owner's rights, v2 body with database-qualified names (ADR-0019) |
| 7 | `terraform/pipeline/gate.tf` | 10 append-only streams. 10 tasks: `optimized` = serverless, XSMALL/XSMALL, timeout var, 3 failures; `baseline` = `CDC_WH`, provider nulls (Snowflake defaults, as v2). 1-minute schedule, `SYSTEM$STREAM_HAS_DATA`. Per-task MONITOR to the plan role |
| 7 | `terraform/platform/grants.tf` | SYSADMIN: USAGE on `CDC_WH`; `EXECUTE TASK` + `EXECUTE MANAGED TASK` on account (hypothesis). Plan role: USAGE on `CDC_CI_WH`; MONITOR on future tasks |
| 7 | `terraform/pipeline/.terraform.lock.hcl` | Identical to platform's (2.23.0) |
| 8 | `scripts/{streams_and_tasks,snowflake_setup,00_account_bootstrap,create_readonly_role}.sql` | Deleted (git keeps them) |
| 8 | `.github/workflows/deploy.yml` | Two `echo` lines no longer name the deleted scripts. Otherwise `ci.yml`'s "referenced files exist" check turns red. The file itself goes in item 18 |
| 8 | `scripts/init.sql` | One comment now points to `terraform/pipeline/gate.tf` |
| 9 | `scripts/verify_governance.sql` | Rewritten in English, **assertive**. Four Scripting blocks RAISE (−20002 AT-002, −20003 monitors, −20005 budget, −20004 tasks). AT-002 uses the F6 read-back (`generation`, `resource_constraint = STANDARD_GEN_<n>`) — **B4 closed**. AT-004 checks 10 started tasks, compute per profile and task-level parameters. The idle `TASK_HISTORY` query is informational. Plan role on `CDC_CI_WH`; variables `cost_profile`, `gate_task_timeout_ms`, `check_pipeline` |
| 9 | `scripts/budget.sql` | + `GRANT … CDC_BUDGET!VIEWER TO ROLE TERRAFORM_PLAN_ROLE` |
| — | `tests/unit/tfparse.py` | Shared HCL block reader, extracted from `test_terraform_providers.py` |
| — | `tests/unit/test_pipeline_root.py` | B1 identity; sysadmin-only; **USAGE on `CDC_WH` granted by platform, not pipeline** (mutation-checked: turning the grant into MONITOR fails it); EXECUTE TASK on platform/`securityadmin`; Tier-1 domains; Pattern 3 lines; timeout variable; per-task + future MONITOR; ADR-0019 body; old scripts gone |
| — | `tests/unit/test_sql_scripts.py` | `verify_governance.sql` joins the non-destructive / CI-warehouse / no-e-mail checks; runs only as the plan role, no GRANT/ALTER/CREATE/INSERT/MERGE; every check RAISEs; budget VIEWER grant |

### Commands and results

| Command | Result |
|---------|--------|
| `terraform -chdir=terraform fmt -check -recursive` | ✅ exit 0 |
| `terraform validate` (platform, pipeline; `init -backend=false`) | ✅ both valid; lock files identical |
| `terraform console` (pipeline, backend-less copy, `dev.tfvars`) | ✅ `optimized` → serverless, no warehouse, 10 000 ms; `baseline` → `CDC_WH`, no timeout; `gate_task_timeout_ms=5000` rejected |
| `ruff check .` | ✅ |
| `pytest tests/unit -q` | ✅ 97 passed |
| `terraform plan`, `snow sql` | ⏭️ Not run (no identities yet) |

### Deviations from DESIGN 1.2

| Deviation | Reason | Impact |
|-----------|--------|--------|
| `create_readonly_role.sql` deleted (not listed in item 8) | Fully replaced by `roles.tf`/`grants.tf`/`users.tf`; owner decision after grep | None |
| `EXECUTE TASK`/`EXECUTE MANAGED TASK` and SYSADMIN USAGE on `CDC_WH` in **platform**, not pipeline | Account-level, independent of Bronze; keeps `pipeline` on one alias | Applied one step earlier |
| `deploy.yml` edited (2 lines) before its deletion (item 18) | Deleting the scripts otherwise fails `ci.yml` | None |
| `verify_governance.sql` is assertive and read-only (DESIGN: "read-only account checks") | v2 trap: an invisible object returns zero rows, not an error | CI fails on drift |
| Plan role read grants + budget VIEWER | Needed for item 9 as decided | Two more grant resources; one SQL grant |

### DESIGN 1.5 — prepared, NOT applied (only if the Day 3 apply rejects SECURITYADMIN)

(Numbered 1.3 when written in run 3; renumbered 1.4 in run 4 and 1.5 in run 5, as those runs used 1.3 and 1.4.)

Apply only if the platform apply fails on
`snowflake_grant_privileges_to_account_role.sysadmin_execute_task` with an insufficient-privileges
error. Paste the error into the row.

- **Decision 9, named-exception table**, new row:
  `| snowflake_grant_privileges_to_account_role.sysadmin_execute_task (EXECUTE TASK, EXECUTE MANAGED TASK on account → SYSADMIN) | SECURITYADMIN's MANAGE GRANTS was rejected for these global privileges at the Day 3 apply: "<error text>" | Day 3 apply log (run <id>) |`
- **Revision history:**
  `| 1.5 | <date> | Christian (with Claude) | Day 3 apply: SECURITYADMIN cannot grant EXECUTE TASK / EXECUTE MANAGED TASK; the grant joins the accountadmin named list. No scope change. |`
- **Code, same PR:** `provider = snowflake.accountadmin # Decision 9 named exception` on that
  resource. Add it to `ACCOUNTADMIN_ALLOWED` in `test_terraform_providers.py`. Change the
  assertion in `test_execute_task_privileges_are_granted_by_platform` to `accountadmin`.

### Open issues (new)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O16 | **Hypothesis:** SECURITYADMIN can grant `EXECUTE TASK` / `EXECUTE MANAGED TASK`. If the apply fails, use DESIGN 1.5 above | Day 3 apply | build-agent |
| O17 | `resource_constraint = STANDARD_GEN_2` in profile `baseline` is assumed by symmetry with F6; confirm in the dry run (AT-002 is only formally checked in `optimized`) | Day 7 | build-agent |
| O18 | Scripting constructs not yet run on the account: `SHOW PARAMETERS` via `EXECUTE IMMEDIATE` + `RESULT_SCAN(LAST_QUERY_ID())` inside a cursor loop; `COUNT_IF("IS_VALID")`; `SHOW RESOURCE MONITORS` `level`/`notify_at` values; `SHOW WAREHOUSES` `size` spelling | First CI run | build-agent |
| O19 | `VIEWER` may not be enough for `GET_SPENDING_LIMIT` / `GET_REFRESH_TIER` (undocumented). If not, the budget block fails loudly. Fix with the least extra grant, never ACCOUNTADMIN | First CI run | build-agent |
| O20 | Profile switch on existing tasks: the provider must move them warehouse ↔ serverless and unset timeout/failure limit when going to `baseline` (provider nulls). The second plan of the switch must be clean, and `verify_governance.sql` checks task-level parameters | Dry run (Day 7) | build-agent |
| O21 | **`gate_task_timeout_ms` is provisional (10 000 ms).** Set it to max(10 s, 5 × p99 of `TASK_HISTORY`) after the dry run. Also unknown: whether serverless start-up counts toward the timeout (B2) | Day 7 | Christian |
| O22 | `dev.tfvars` is shared: the pipeline root warns "value for undeclared variable" for platform-only variables (quotas, `owner_user_name`). Warnings only; revisit if they hide real ones in CI | Item 16 | build-agent |
| O23 | README, `docs/adr/README.md`, ADR-0019/0020/0022/0025/0029/0030 and `sensors.py` comments still name the deleted scripts. ADRs are history and are left unchanged. README is item 22; `sensors.py` is item 11 | Items 11, 22 | — |

### Build checklist status after run 3

| # | Status |
|---|--------|
| B1 | **Code side closed:** one `dev.tfvars`, identical `profiles.tf` (tested), `verify_governance.sql` asserts the profile on both roots' objects. Open: the two-root `main` job (item 16) |
| B4 | **Closed:** AT-002 asserted in the F6 format |
| B2, B3, B5 | Unchanged |

---

## Run 4 — 2026-11-18 — manifest items 16–18 (+ 15 draft)

Branch `feat/cost-governance-items-16-18` (from `main` after #3). Requirement: **REQ-08 / AT-009**.
It also makes AT-001 executable and runs exceptions 2 and 3.

### Owner decisions (2026-11-18)

1. **Item 15 stays with the owner** (DESIGN *Agent Assignment*). The agent drafted only
   `docs/measurement/queries.sql`, marked DRAFT with `TODO(owner)` decisions.
2. **AWS state bootstrap is a documented manual step** (runbook), not a third Terraform root. The
   runbook gives a least-privilege OIDC policy, trust restricted to this repository and the
   `snowflake-plan` / `snowflake-dev` environments, and **mandatory bucket versioning**.
3. The `apply` job compares its re-plan with the PR plan and **warns without blocking**.
4. A skipped pipeline plan is shown in the job summary.
5. The Decision 11 consequence is recorded → **DESIGN 1.3**. The EXECUTE TASK fallback text
   prepared in run 3 is renumbered **1.4**. PR #3's description, already merged, still calls it 1.3.

### Docs read before writing

- Snowflake CLI *Configure connections*: `snow sql -x` / `--temporary-connection` reads
  `SNOWFLAKE_ACCOUNT`, `SNOWFLAKE_USER`, `SNOWFLAKE_AUTHENTICATOR`, `SNOWFLAKE_PRIVATE_KEY_RAW`.
  Set only one of `_RAW` and `_FILE`.
- HashiCorp *S3 backend*: with `use_lockfile`, Get/Put/Delete are needed on `<key>.tflock`; no
  Delete on the state; versioning recommended.
- GitHub *Configuring OpenID Connect in AWS*: `sub` = `repo:OWNER/REPO:environment:NAME`,
  `aud` = `sts.amazonaws.com`, `id-token: write`.
- `snowflake-cli` versions on PyPI: pinned **3.32.1** (2026-11-02, more than two weeks old).

### Files

| # | File | Notes |
|---|------|-------|
| 16 | `.github/workflows/terraform.yml` | Four jobs, as in Decision 11:<br>• `static` (forks too, no secrets): fmt + validate.<br>• `plan`: same-repo PRs, `snowflake-plan`, `TF_VAR_plan_role`. Platform plan; Bronze check with the plan role; pipeline plan or a **skip notice in the summary**; summary + PR comment; plan summaries uploaded as an artifact.<br>• `apply`: push to `main`, `snowflake-dev`. Fetch the PR plan summaries → platform re-plan → **compare (warn only)** → apply → `-detailed-exitcode` plan (AT-001) → seed / account_monitor / budget → pipeline the same way once its state is non-empty → `verify_governance.sql` with the **read-only key**.<br>• `apply-pipeline`: `workflow_dispatch`; requires Bronze, then plan / apply / second plan / verify.<br>Settings: `defaults.run.shell: bash` (pipefail); one apply concurrency group, never cancelled; Terraform 1.11.4. |
| 16 | `.github/scripts/plan_summary.py` | `summarize` (changed address + actions, no values) and `compare` (always exits 0) |
| 16 | `.github/scripts/bronze_ready.py` | Parses `snow sql --format json` from `SHOW TABLES`; prints `ready` or `missing: …` |
| 16 | `terraform/platform/grants.tf` | + `plan_tables_future`: REFERENCES on future tables, **database level** (a BRONZE schema-level grant would cancel CDC_ROLE/RO's database-level future grants there) |
| 16 | `docs/runbooks/terraform-state-bootstrap.md` | Bucket (versioning **mandatory**, SSE-S3, public access blocked, owner-enforced, TLS-only policy). OIDC provider. Two roles, `sdd3-tfstate-plan` (state read-only) and `sdd3-tfstate-apply`, each trusting exactly one `sub` (`StringEquals`). Minimal S3 policy. GitHub environments, variables and secrets table. Verification and state recovery |
| 17 | `.github/workflows/ci.yml` (**shared file**) | `lint` job + `pytest==8.3.3 pyyaml==6.0.2` and `pytest tests/unit -q`. The "referenced files exist" regex now matches whole paths (it matched `scripts/x.py` inside `.github/scripts/x.py` and `../../…`, which would have turned CI red) and normalises `../`. Header note on the deletion of `deploy.yml` |
| 18 | `.github/workflows/deploy.yml` | Deleted |
| 15 (draft) | `docs/measurement/queries.sql` | DRAFT: Q1 warehouse credits/day/window (UTC), Q2 serverless tasks, Q3 metering by service type with the cloud-services adjustment, Q4 resumes, Q5 per-cluster buckets (arithmetic checked), Q6 freshness join sketch (Decision 7), Q7 idle `TASK_HISTORY`, Q8 attribution skeleton. 11 `TODO(owner)` |
| — | `tests/unit/test_workflows.py` | 22 checks:<br>• no destroy / auto-approve;<br>• static job without secrets;<br>• plan job: fork guard, read-only, never `snowflake-dev`;<br>• applies only in `snowflake-dev` on `main`, each followed by a `-detailed-exitcode` plan;<br>• compare steps warn and never `exit 1`;<br>• skip written to the summary;<br>• e-mail only from a secret;<br>• verify with the read-only key and `tail -n 1`;<br>• secrets only in jobs with an environment; `id-token` only with the AWS action;<br>• actions pinned (`@vN`, known publishers); tool versions pinned;<br>• `BRONZE_TABLES` equals `gate_domains`; `ci.yml` runs pytest;<br>• the `ci.yml` reference check passes here and still catches a missing helper. |
| — | `tests/unit/test_ci_helpers.py` | 10 checks on both helpers, including their CLIs |

### Bugs caught before they ran

| Bug | Where | Fix |
|-----|-------|-----|
| `terraform console` prints "undeclared variable" warnings on **stdout**: `profile=$(…)` would have captured them | verify steps | `tail -n 1`, plus validation of the value (`baseline\|optimized`, digits) |
| `run:` without an explicit shell is `bash -e` without pipefail: a failing `terraform plan \| tee` would pass | plan steps | `defaults.run.shell: bash` |
| `ci.yml`'s reference check matched suffixes of `.github/scripts/*.py` | ci.yml | regex with lookbehind + `../` normalisation; tested both ways |
| `vars.*` are printed unmasked in public logs — the budget e-mail would leak | budget step | `BUDGET_NOTIFY_EMAIL` is a **secret** (PR #2 description said "variable": superseded) |
| My first Q5 formula assigned a cluster's first hour bucket to the previous cluster | queries.sql | Corrected and checked with a small Python simulation |

### Commands and results

| Command | Result |
|---------|--------|
| `terraform -chdir=terraform fmt -check -recursive` | ✅ |
| `terraform validate` (platform, pipeline) | ✅ |
| `ruff check .` | ✅ |
| `pytest tests/unit -q` | ✅ 130 passed |
| `ci.yml` reference check, run locally from the YAML | ✅ exit 0; a planted missing helper → exit 1 |
| `terraform console` profile/timeout extraction with `tail -n 1` | ✅ `optimized`, `10000` |
| Workflow on GitHub | ⏭️ `static` and `ci.yml` run on the PR. `plan` / `apply` need the bootstrap (runbook) and the environments |

### Deviations from DESIGN 1.3

| Deviation | Reason | Impact |
|-----------|--------|--------|
| New `.github/scripts/` (not in the ownership table) | The compare and Bronze-check logic needed tests; inline shell could not be tested | Recorded in manifest item 16 (DESIGN 1.3) |
| New runbook `terraform-state-bootstrap.md` (not among the five of item 19) | Owner decision: manual AWS step, documented | — |
| Edited the reference-check regex in `ci.yml` | Needed for item 16 not to break CI | Shared file, one change at a time |
| Two AWS roles instead of one | Plan job gets no write access to the state | One more `AWS_ROLE_ARN` value (per environment) |

### Open issues (new)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O24 | **Bootstrap before Day 3:** AWS (runbook §1–4); GitHub environments with `snowflake-dev` → reviewer + `main` only (§5); the variables and secrets in §5. **`BUDGET_NOTIFY_EMAIL` is a secret** (replaces O12's "variable") | Day 3 | Christian |
| O25 | A same-repo PR branch can edit `terraform.yml` and use the `snowflake-plan` key (no reviewer by design). It is read-only, but it can read metadata. Acceptable while only the owner pushes branches; revisit if collaborators join | Ongoing | Christian |
| O26 | `gh api …/commits/<sha>/pulls` and `gh run list --commit` locate the PR plan. A direct push or a squash merge, where the head SHA differs, gives "no PR plan" as a warning, not a failure | First `main` run | build-agent |
| O27 | `snow sql -x` against a `SHOW` statement with `--format json`: the output shape is unverified. `bronze_ready.py` accepts any nesting; an error fails the step loudly | First PR plan | build-agent |
| O28 | `CDC_GOVERNANCE_RO` has USAGE on `CDC_WH` only, but measurement queries must not use `CDC_WH` during windows (`queries.sql` TODO) | Before Day 8 | Christian |
| O29 | Item 15 (`PROTOCOL.md`, `ATTRIBUTION.md`, `RESULTS_TEMPLATE.md`, finished `queries.sql`) and B5 | Before Day 7 | Christian |

---

## Run 5 — 2026-11-18 — manifest items 10–13

Branch `feat/cost-governance-items-10-13`, **stacked on `feat/cost-governance-items-16-18`
(PR #4)**: `main` is still at DESIGN 1.2 and 1.3 lives in #4. Requirement: **REQ-05 / AT-005,
AT-006**, with the Decision 7 support for REQ-07.

### DESIGN 1.3 → 1.4 (before code; owner-reviewed diff, two conditions added)

1. **Pattern 4 bug.** A simulation of Pattern 4 as written showed that continuous Kafka traffic
   with an empty `PENDING_RUNS` makes the sensor query **every minute** (50 queries in 60 min,
   *N* = 10). This is the state when gate tasks are suspended while load continues. Fix: an empty
   starvation-guard query restarts `pending_since`, giving one query per *N*. The simulation is
   kept as `test_regression_*`.
2. **Item 12 → `assets.py`**, the code that actually writes `PROCESSING_LOG`. `assets.py` is now
   owned by COST_GOVERNANCE. Checked: not in `_index`, not in SCD2's DEFINE, no fast track, no open PR.
3. **Sensor order inverted**: `UPDATE` first, under the run key, inside one transaction; then read
   the rows it marked.
4. **Owner condition — failed run after the `UPDATE` (Decision 7): reprocess, never accept the
   loss.** `pending_run_release_sensor` (a `run_failure_sensor` on `cdc_pipeline_job`) returns the
   run's rows to pending. **No automatic retry**: it would fail fast on a suspended `CDC_WH` and add
   a resume outside the window. Residual case, documented: an `UPDATE` committed with no run ever
   created.
5. **Owner condition — the worst-wait property must exercise empty guard queries mid-burst.**
   Confirmed and asserted: the 2,000-world corpus produces **1,675 empty mid-burst guard queries,
   1,191 of them followed by a run that finds rows**. An explicit test covers the case: burst
   arriving, empty guard query, clock restarted, next guard after *N* finds rows.
6. **Agent Assignment deviation**: Claude Code builds 10–13 (owner decision); human review in the PR.

The fallback text for EXECUTE TASK is renumbered **1.5**.

### Docs and versions checked

- `dagster/Dockerfile` pins `dagster==1.6.*`. I read the **1.6.14** wheel source (downloaded to
  the scratchpad, never imported):
  - `run_failure_sensor(monitored_jobs=…, default_status=…)` exists;
  - run-status sensor functions accept resource parameters (`get_resource_args`);
  - `RunFailureSensorContext.dagster_run` is available;
  - `RUN_KEY_TAG = "dagster/run_key"`;
  - `AssetExecutionContext.run_tags` exists.
- Snowflake connector default paramstyle is `pyformat`, so `%(run_key)s` works. An explicit
  `BEGIN … COMMIT` works with autocommit on.

### Files

| # | File | Notes |
|---|------|-------|
| 10 | `dagster/pipeline/gate.py` (new) | `GateState`, `decide`, `after_query` (1.4 fix); `to_cursor` / `from_cursor` with **v5 cursor migration** (`hot h` → pending, `quiet = 3 − h`); `new_run_key`; `consume_pending` (`BEGIN` → mark → read marked → `COMMIT`, `ROLLBACK` on error); `release_pending`. **No Dagster import**, so it can be tested in CI |
| 11 | `dagster/pipeline/sensors.py` | v6 header. The bronze sensor uses the gate. `BATCH_WINDOW_MINUTES` comes from the environment (default 0 = profile A). The run key is the Dagster `run_key` and is tagged with the window. **The false "implicit PRIMARY KEY" comment is gone** (the v5 code marked `WHERE consumed = FALSE`). New `pending_run_release_sensor` with no `RunRequest`. Docstrings now point to `terraform/pipeline/gate.tf` instead of the deleted script (part of O23) |
| 12 | `dagster/pipeline/assets.py` | `run_key = context.run_tags.get("dagster/run_key")` → `PROCESSING_LOG.RUN_KEY` (14 placeholders). `None` for manual runs |
| 12 | `dagster/pipeline/__init__.py` | Registers `pending_run_release_sensor`. **Deviation**: this file is in no ownership row; one line, needed for the sensor to exist |
| 13 | `tests/unit/test_gate.py` (new) | 27 tests, listed below |

What `test_gate.py` covers:
- **Profile A:** legacy parity with the v5 logic on **500 random sequences**, with random `found`.
- **Profile B:**
  - a settled burst runs once (`[7]`);
  - the cluster `0/2/4/10/12` runs at `[7, 17]`;
  - continuous traffic gives a guard every 10 min, and at the end `60/70/71`, which is the
    "at most two" of Decision 6;
  - an empty settled query gets its retry, then the burst clears;
  - at most two consecutive queries.
- **Regression:** the 1.3 `after_query` gives 50 queries per hour; the fix gives `[10…50]`.
- **Explicit case** of an empty guard query mid-burst.
- **Property on 2,000 worlds** (bursty activity, task row probability 1.0–0.05, lag 0–2 min):
  - no stranded row;
  - **worst wait 10 min = *N***; p95 9 min over 73,648 rows;
  - never more than 2 queries in consecutive minutes;
  - the corpus contains ≥ 100 empty mid-burst guards and ≥ 50 later finds.
- **Cursor:** round trip; empty cursor (profile A queries at once, B at settle); v5 migration
  with `hot` 0–3 keeps v5 behaviour; migration into profile B.
- **PENDING_RUNS** (SQLite behind a pyformat adapter):
  - UPDATE-first marks then reads exactly the marked rows;
  - **race: a row inserted after the `UPDATE` stays pending and is consumed next time**;
  - the v5 order is shown losing that trigger;
  - a failed read rolls back the marks;
  - **a failed run's rows are released and re-consumed under the next key**, other runs' rows
    untouched, an unknown key releases 0.
- **Static wiring:** sensor, release sensor (no retry), `assets.py` insert.

### Mutation check

Restoring the 1.3 `after_query` makes **4 tests fail**:
- the at-most-two test;
- the fixed regression;
- the explicit empty-guard test;
- the 2,000-world property, through its query-rate assertion.

The worst-wait bound **alone did not catch the bug**: extra queries do not lengthen waits. That is
why the property now also asserts the query rate.

### Commands and results

| Command | Result |
|---------|--------|
| `ruff check .` | ✅ |
| `pytest tests/unit -q` | ✅ 157 passed (27 in `test_gate.py`) |
| `python -m py_compile dagster/pipeline/*.py` | ✅ |
| `terraform fmt -check`, `validate` | ✅ (only a comment changed in `grants.tf`) |
| Dagster load of the code location | ⏭️ Not run locally (no Dagster on the host); first stack start |

### Deviations from DESIGN 1.4

| Deviation | Reason | Impact |
|-----------|--------|--------|
| `gate.py` also holds the PENDING_RUNS DB-API helpers | Keeps the SQL testable without Dagster | — |
| `__init__.py` edited (not in the ownership table) | Registering the new sensor | One line |
| Profile B's first tick on an empty cursor queries at settle (3 min), not at once | Pattern 4 semantics; rows written before the sensor started are still consumed | +3 min once, after a Dagster restart in profile B |
| REQ-11 (COULD) not built | Day 6 slack only; disabled during the A/B anyway | — |

### Open issues (new)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O30 | `BATCH_WINDOW_MINUTES` is not in `.env.example` yet (item 21, shared file) and must switch with `cost_profile` (Decision 2) | Item 21 / before Day 7 | Christian |
| O31 | The code location has not been loaded by a real Dagster 1.6 yet: `run_failure_sensor` with a resource parameter, `context.run_tags` on the asset | First stack start | build-agent |
| O32 | In profile B the switch at 00:00 UTC restarts Dagster. A pending burst survives (cursor), but a cursor written by profile A has `last_run_at` from A, which can hold B's first run up to *N* | Dry run (Day 7) | Christian |
| O33 | Residual case of Decision 7 (`UPDATE` committed, run never created) shows as a freshness gap. Count them in the dry run | Day 7 | Christian |
| O34 | Merge order: #4 first **without** `--delete-branch`, then `gh pr edit <this PR> --base main`, then delete #4's branch (lesson from #1/#2) | Merge | Christian |

---

## Run 6 — 2026-11-18 — manifest item 14

Branch `feat/cost-governance-item-14`, **stacked on `feat/cost-governance-items-10-13`** (PR #5,
itself on #4). Requirement: **REQ-06 / AT-007**, plus the Decision 5 task-state validity rule.
DESIGN 1.4, no revision in this run.

### Owner decisions (2026-11-18)

1. A burst more than 60 s late is **skipped and recorded**, never run late. The count appears in
   `--plan-only` ("would skip N") and in the final summary.
2. A gate task not `started` → warning, the load continues, and `task_states.csv` gets a
   **`window_valid`** column.
3. Identity of the task check: **`CDC_ROLE_RO`**. The check **fails if it does not see exactly the
   10 tasks**; it never returns empty.
4. Tests for an update that affects 0 rows (warning when a burst affects fewer than
   `LOAD_ROWS_PER_BURST`) and for **resume after a crash between commit and CSV write**, with the
   behaviour documented.
5. Prerequisites (O35) stay with the owner.

### Behaviour, as documented in the module docstring

| Situation | Behaviour |
|-----------|-----------|
| Same `LOAD_SEED` | Identical schedule **and** identical operations (table, kind, key, values). Each burst has its own RNG seeded by `(seed, burst_id)`, so a restart reproduces a burst without history (AT-007) |
| Burst > 60 s late | Not run; line in `skipped.csv` + stderr; `skipped=N` in the summary; exit code 1 |
| Update target missing (its burst was skipped) | Updates affect 0 rows; `commits.csv.rows` = rows **actually** affected; stderr warning "affected X < 200 planned rows"; `underfilled` in the summary |
| **Crash between Postgres COMMIT and the CSV append** | On restart, every past burst missing from `commits.csv` is probed by the deterministic key of its first `orders` insert. If present, the burst is logged with `source=recovered`; `committed_at_utc` comes from that row's `dt_current_timestamp`, the transaction start, ms before commit; `rows` is the planned count. **Never re-executed**: replayed updates would emit duplicate CDC events. Inserts are `ON CONFLICT DO NOTHING` as a second guard |
| Burst fails mid-transaction | ROLLBACK; no CSV line; the error propagates and the process stops. A restart re-runs it if still within 60 s, otherwise it is skipped |
| Task check sees ≠ 10 gate tasks (0, 9, 11) | `TaskVisibilityError`; exit code 3. Checked at start-up, so a misconfiguration fails before the first burst |
| A gate task not `started` | stderr warning; `window_valid=false` from that check on (cumulative, survives restarts); the load continues; exit code 1 at the end |

### Files

| File | Notes |
|------|-------|
| `tests/load/generate_load.py` (new) | Pure parts: `schedule` (clusters at :30 UTC, every 120 min, offsets `0,2,4,10,12`, validated so no cluster crosses a day or the next cluster); `allocate` (largest remainder over fixed weights; 200 = the weights); `plan_burst` / `plan_window` (facts insert-only; entities about half updates against earlier bursts' deterministic UUID5 keys; synthetic values); `sql_for` (parameterised; `%s::jsonb` for `payment_events.event`); `due_action`. I/O: `run_burst` (one transaction), `committed_at_of` (recovery probe), `CsvLog` (append + fsync), `TaskStateLog`, `parse_task_states`, `snowflake_task_rows` (CDC_ROLE_RO, key-pair from file, **no warehouse set**, DictCursor), `run` (injectable clock / sleep / stderr), `plan_report`, `main` (`--plan-only`, `--no-task-check` for local testing only). `psycopg2`, `snowflake.connector` and `cryptography` are imported lazily |
| `tests/unit/test_generate_load.py` (new) | 28 tests, listed below |

What `test_generate_load.py` covers:
- **Schedule:** 24 clusters × 5 bursts in window A, at :30 of even hours; no day crossing;
  bad offsets rejected; `allocate` sums.
- **AT-007:** same seed → identical; another seed → same schedule, different operations;
  200 rows per burst; restart reproduces a burst.
- **Content:**
  - facts are insert-only, and updates target only earlier inserts;
  - the probe key is the first `orders` insert;
  - the data is synthetic;
  - the SQL is parameterised, and inserts never overwrite.
- **Time:** wait / run / skip at 60 s; `plan_report` counts would-be skips (7 at 02:33:30).
- **Task check:** exactly ten accepted; empty / 9 / 11 rejected; `window_valid` turns false and
  stays false across restarts.
- **Run loop with fakes:**
  - 5 bursts → 5 commits, live rows, 2 task checks;
  - **an update affecting 0 rows → real counts and 4 warnings**;
  - **late bursts → 3 skipped, 2 run**;
  - **crash between commit and CSV → `recovered`, timestamp from Postgres, b1 never re-executed**;
  - an uncommitted burst is re-run;
  - a failed burst rolls back with no line;
  - **no visibility → stops before any burst**;
  - not-started → continues, `window_valid=false`;
  - `--plan-only` touches no database.

### Mutation checks

- Disabling recovery fails the crash-resume test.
- Not turning `window_valid` false fails 2 tests.

### Commands and results

| Command | Result |
|---------|--------|
| `ruff check .` | ✅ |
| `pytest tests/unit -q` | ✅ 185 passed (28 in `test_generate_load.py`) |
| `generate_load.py --window dry-run --start 2026-11-24T12:00Z --end 2026-11-24T18:00Z --plan-only` | ✅ `clusters=3 bursts=15 rows=3000`; inserts/updates per table; `would skip 0` |
| Against Postgres / Snowflake | ⏭️ Not run (stack and identities not up; R1 — agents do not touch the account) |

### Deviations from DESIGN 1.4

| Deviation | Reason | Impact |
|-----------|--------|--------|
| `commits.csv` gains a 4th column `source` (`live` \| `recovered`) | Recovered bursts must be distinguishable; their `committed_at_utc` is the transaction start | `queries.sql` Q6 reads the first three columns, unchanged |
| New `skipped.csv` | Owner decision 1 | — |
| Task check at start-up **and** 20 min after each cluster's first burst (DESIGN: "after each load cluster") | Fail before the first burst on misconfiguration; 20 min = after the last burst (+12) and its gate-task tick | — |
| Exit codes 0 / 1 / 3 | 1 = window not valid (skips or a task not started), 3 = visibility error | Usable by `make load` (item 20) |

### Open issues (new)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O35 | Prerequisites: `CURSOR_MCP_USER` key pair (public key in `TF_VAR_cursor_rsa_public_key`, O4); `LOAD_SNOWFLAKE_PRIVATE_KEY_PATH`; the machine/VM for Days 7–12 with `psycopg2-binary`, `snowflake-connector-python`, `cryptography` | Before Day 7 | Christian |
| O36 | `CURSOR_MCP_USER` has `DEFAULT_WAREHOUSE = CDC_WH` (`users.tf`). The generator sends only `SHOW TASKS`, which needs no warehouse and does not resume one. **Verify in the dry run** that `WAREHOUSE_EVENTS_HISTORY` shows no `CDC_WH` resume caused by this user. If it does, set its default warehouse to `CDC_CI_WH` by PR | Day 7 | build-agent |
| O37 | The generator updates `restaurants` (≈ 21 updates per cluster): SCD2_RESTAURANTS reads `tests/load/` (`_index` ownership). Its history model will see these versions; coordinate fixture vs measurement load at its Design | SCD2 Design (Day 3) | Christian |
| O38 | Dependency versions on the VM are not pinned by this repo (no `requirements` for `tests/load/`) | Before Day 7 | Christian |

---

## Merge of #4 → #5 → #6 — 2026-11-23

No code change. Stacked PRs merged in order with merge commits (O34): #4 `178f0d2`, #5 `788902e`,
#6 `251bf62`. After each merge the next PR was retargeted to `main`. CI green on each merge commit.

| Finding | Action |
|---------|--------|
| Environment `snowflake-dev` (used by `apply (main)`) **did not exist**. GitHub would have created it on first use **without** a required reviewer, so a merge to `main` would have run an unapproved apply | Merge held; owner created `snowflake-dev` with required reviewer `christiandrocha`; checked by API before merging |
| `plan (read-only)` failed on #4 and #5: `Input required and not supplied: aws-region` (repository variables/secrets not set) | Recorded as O39 |
| Terraform `apply (main)` runs on `178f0d2` (waiting for approval) and `788902e` (queued) | Cancelled with `gh run cancel` by owner decision; nothing applied. The #6 merge did not start a Terraform run (no Terraform path changed) |
| `main` has no branch protection | Recorded as O40 |

### Open issues (new / closed)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O34 | ~~Merge order #4 → #5 → #6~~ — **closed** 2026-11-23 | — | — |
| O39 | Repository variables and secrets for `terraform.yml` not set (`TF_STATE_REGION` first; state bucket, Terraform identities' keys). Every plan fails until they exist | Before the first apply | Christian |
| O40 | `main` is not protected: nothing requires green CI or a PR before a push, which is what triggers `apply (main)`. The `snowflake-dev` reviewer is the only gate | Before the first apply | Christian |

---

## Run 7 — 2026-11-23 — manifest item 15 (draft for the owner)

Branch `feat/cost-governance-item-15`, from `main` (`58c27ae`). Requirement: **REQ-07 / AT-008**
(REQ-06 for the load section). Closes Build checklist **B5**. DESIGN 1.4, no revision in this run.

**Agent Assignment deviation (owner decision 2026-11-23):** item 15 is owner-authored. The build
agent wrote the full draft so that the protocol exists **before** the dry run (2026-11-24 12:00 UTC).
The owner edits it in the PR. Every rule written here was fixed before any measurement ran.

### Owner decisions (2026-11-23, defaults accepted as proposed)

1. Queries run on **`CDC_WH`, only outside the windows** (dry-run evening; ≥ 2026-11-29 10:00 UTC).
   No Terraform change. This closes O28.
2. **Q5, per cluster:** the 2 h bucket `[hh:00, hh+2:00)` with even `hh` is exact. Q5b checks that
   no cluster's activity crosses the bucket end.
3. **Q6, freshness input:** `commits.csv` is pasted in as a `VALUES` CTE, built with an `awk` line.
   No stage, table or script is created (`CDC_GOVERNANCE_RO` cannot create objects anyway).
4. **Gen2 rate (B3):** measured as `rate_A` = window A credits ÷ billed hours, with the
   consumption table's 1.35 reported as a reference only.
5. **Reruns (B5):** each void window may be rerun once, at the next 00:00 UTC. The last start is
   2026-11-29 00:00 UTC; the idle window and the reading then move. A quota raise goes through a
   `dev.tfvars` PR. A rerun extends the SCD2 embargo.

### Docs read before writing (Snowflake docs, 2026-11-23)

| Fact | Source | Used in |
|------|--------|---------|
| `RESUME_WAREHOUSE` / `SUSPEND_WAREHOUSE` exist, with event state `STARTED`; `TIMESTAMP` is `TIMESTAMP_LTZ` | `WAREHOUSE_EVENTS_HISTORY` | Q4 (exact `event_name` replaces the `ILIKE`), Q4b |
| Warehouses bill per second, with a 60 s minimum each time they resume | *Understanding compute cost* | Q4b `GREATEST(60, …)` |
| `TIMEZONE` defaults to `America/Los_Angeles` (account » user » session); `CURRENT_TIMESTAMP()` returns the session time zone; an offset in a string cast to `TIMESTAMP_NTZ` is not applied | *Parameters*; `CURRENT_TIMESTAMP`; *Date & time data types* | Q6 `$detected_at_tz`, Q0 |
| `METERING_DAILY_HISTORY` and `WAREHOUSE_EVENTS_HISTORY`: up to 3 h of latency; `SERVERLESS_TASK`, `SNOWPIPE_STREAMING` and `WAREHOUSE_METERING` are documented service types | view pages | PROTOCOL §6, Q3 |
| No Gen2 credit table on the compute-cost page; it points to the external consumption PDF | *Understanding compute cost* | B3 default: rate measured from A |

### Files

| File | Notes |
|------|-------|
| `docs/measurement/PROTOCOL.md` (new) | §1 metrics and hypotheses. §2 windows (UTC and Vitória). §3 the generator commands per window. §4 switches S0–S3, with steps and the `switch.log` format. §5 validity rules and the **rerun policy (B5)**. §6 how results are read (role, warehouse, `awk`, output file names). §7 the **dry-run checklist D1–D12**. §8 what is committed. §9 change log |
| `docs/measurement/ATTRIBUTION.md` (new) | Decision 13 in prose. The `rate_B ≈ 1.0` self-check before any share is computed. Formulas for the Gen1, gate-task and batching shares. The known bias, with a reporting rule fixed in advance. Negative shares are reported as is |
| `docs/measurement/RESULTS_TEMPLATE.md` (new) | Windows as run, the predictions copied verbatim from the DESIGN, H1/H2/freshness/idle, per day, per cluster, freshness, attribution, items reported apart, caveats |
| `docs/measurement/queries.sql` | All 9 `TODO(owner)` resolved. New: Q0 (time-zone checks), Q4b (billed seconds from resume/suspend pairs), Q5b (bucket-crossing check), Q8a (measured rates with the self-check), Q8b (task-only intervals), Q8c (share arithmetic). Q6 rewritten (below). 4 `TODO(dry run)` remain, all listed in PROTOCOL §7 |

### Bugs caught in the 2026-11-18 draft before they ran

| Draft | Problem | Fix |
|-------|---------|-----|
| Q6 joined `detected_at >= committed_at_utc` directly | `DETECTED_AT` is `CURRENT_TIMESTAMP()` in the gate task's session time zone, stored as NTZ (`procedures.tf`). With the default `America/Los_Angeles`, every detection would look ~8 h **earlier** than the commit, and freshness would pick a burst ~8 h later or report gaps | `CONVERT_TIMEZONE($detected_at_tz, 'UTC', detected_at)`; Q0.1/Q0.2 confirm the time zone in the dry run (D1) |
| Q6 filtered `consumed_run_key IS NOT NULL` before taking the first detection | This silently skipped to a later row, which is not Decision 7's "first row detected after the commit". A never-consumed first row would have hidden a gap | Take the first detection, whatever its key; a NULL key counts as a gap |
| Q6 counted every Gold row | A failed Gold model still has a `FINISHED_AT` | `status = 'success'` |
| Q6 had no upper bound | Decision 7: no consuming run within 2 h means a gap | Join bounded at 120 min; gaps counted separately from the percentiles |
| Q6 ran as `CDC_GOVERNANCE_RO` | That role has no `SELECT` on `CDC_POC.CONFIG` (`grants.tf`) | Q6 and Q0.2 run as `CDC_ROLE_RO` |
| Header: `USE WAREHOUSE COMPUTE_WH` | `CDC_GOVERNANCE_RO` has `USAGE` on `CDC_WH` only | `CDC_WH`, only outside the windows (owner decision 1) |
| Q4 used `event_name ILIKE '%RESUME%'` | This would also match `RESUME_CLUSTER` and double-count a resume | `event_name = 'RESUME_WAREHOUSE'` |

### Commands and results

| Command | Result |
|---------|--------|
| `ruff check .` | ✅ |
| `pytest tests/unit -q` | ✅ 185 passed (no code changed) |
| Parse every statement of `queries.sql` with `sqlglot` (Snowflake dialect; `USE`/`SET`/`SHOW` skipped; scratch venv, not a repo dependency) | ✅ 12 / 12 parse. Syntax only |
| `awk` line from PROTOCOL §6 on a sample `commits.csv` | ✅ produces valid `VALUES` rows |
| Against the account | ⏭️ Not run (R1; no apply yet). Every query first runs in the dry run |

### Deviations from DESIGN 1.4

| Deviation | Reason | Impact |
|-----------|--------|--------|
| Item 15 drafted by the build agent (Agent Assignment: author Christian) | Owner decision, so the protocol exists before the dry run | Owner edits in the PR |
| ATTRIBUTION reports one "orchestration" share when task-only billed time is < **10%** of A's (DESIGN: "if the bias is large") | A threshold fixed before measuring cannot be chosen after seeing the numbers | Owner may change the 10% in the PR, but not after A starts |
| `rate_B ≈ 1.0 ± 5%` self-check added before any share is computed | Billed seconds are derived from events; Gen1 at 1 credit/h is a known reference that validates the derivation | If it fails, shares wait for a Q4b fix |
| Switch S3 carries `gate_task_timeout_ms` | Only profile B applies the timeout (Decision 5), so changing it during A has no effect, and a separate apply would be one more stack change | — |

### Open issues (new / closed)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O28 | ~~Queries on `CDC_WH` during windows~~ — **closed** by owner decision 1 | — | — |
| O29 | ~~Item 15 and B5~~ — **closed as a draft**. Owner review of PROTOCOL / ATTRIBUTION in the PR | Before the dry run | Christian |
| O41 | **`PENDING_RUNS.DETECTED_AT` time zone** (D1). The query handles either answer. A cleaner fix would set `TIMEZONE = 'UTC'` on the gate tasks (task session parameter, `terraform/pipeline/gate.tf`), but that is a DESIGN change and is **not** made here. If the owner wants it, it goes into DESIGN 1.5 first, then into the S0 PR, so that A and B share it | Dry run | Christian |
| O42 | Q8b classifies task queries by `QUERY_HISTORY.user_name = $task_user` (expected `SYSTEM`, unverified, D4). If the dry run shows something else, change the `SET` | Dry run | Christian |
| O43 | Prerequisite for S0 (before 2026-11-24 12:00 UTC): the first apply (O1, O24, O39, O40), Bronze tables, then the pipeline apply. Without it there is no dry run, and the §5 rerun policy starts to apply to A | 2026-11-24 12:00 UTC | Christian |

### Build checklist status after run 7

| # | Status |
|---|--------|
| B3 | **Method closed** (rate measured from A, 1.35 as reference). Value after window A |
| B5 | **Closed (draft):** `PROTOCOL.md` §5 states which window may be rerun, how the quota is raised by PR, and the last rerun date. `budget.sql` idempotence was closed in run 2 |
| B1, B2 | Unchanged |

---

## Merge of #10 — 2026-11-23

No code change. PR #10 (item 15 draft) merged with a merge commit, `37c84ca`, after #9
(SCD2_RESTAURANTS DESIGN) at `0cf8f62`. The `SDD_V3_PACKAGE.md` regenerated in both PRs was
checked against the generator after a simulated merge, and it was up to date. CI was green on the
merge commit. No Terraform run started (no Terraform path changed). The `_index.md` row was
updated in #11 (`9287873`).

Owner edits to PROTOCOL / ATTRIBUTION (the 10% rule, the S3 timeout) remain open until window A
starts, 2026-11-25 00:00 UTC. Any later change goes in PROTOCOL §9 with the windows it affects.

---

## Run 8 — 2026-11-23 — manifest item 20 (`Makefile`, shared file)

Branch `feat/cost-governance-item-20`, from `main` (`731cf2b`). Requirements: **REQ-07** (switches
and load of the protocol), REQ-06 (generator) and REQ-08 (deploy). DESIGN 1.4, no revision. **Shared
file touched: `Makefile`** (FT-02 will add `make demo` later; it is still Todo, so there is no
conflict).

### Targets

| Target | Behaviour |
|--------|-----------|
| `load WINDOW=A\|B\|dry-run` | Runs `generate_load.py` with the exact `--start/--end/--out` of PROTOCOL §3. `.env` is sourced into the process only, and nothing is printed. Exit code 0/1/3 is passed through. An unknown `WINDOW` is a make `$(error)`, so it also fails under `make -n` |
| `load-plan WINDOW=…` | The same with `--plan-only`; touches no database |
| `dry-run` | `load WINDOW=dry-run`. v2's `dry-run` (`load_to_postgres.py --dry-run`) is renamed **`produce-dry-run`**; nothing in the repo called the old name |
| `batch-window N= SWITCH=` | Rewrites or appends only `BATCH_WINDOW_MINUTES` in `.env`, recreates `dagster` and `dagster-daemon` (`env_file` is read at creation) and appends a line to `runs/switch.log` (PROTOCOL §4 step 2). `N` must be a whole number |
| `profile-a` / `profile-b` `[SWITCH= AT= TIMEOUT_MS=]` | In a **temporary worktree** from `origin/main`, so the user's checkout is untouched. Sets `cost_profile`, and with `TIMEOUT_MS` also `gate_task_timeout_ms` (S3). Shows the diff, commits citing REQ-07, pushes, and opens a **draft** PR whose title carries the switch and time. Then it removes the worktree and the local branch. Refuses when there is nothing to change. Never applies or merges |
| `deploy-platform` | Refuses on `main`. Runs `terraform fmt -check` and `validate` (both roots) when `terraform` is installed; otherwise prints that the CI `static` job runs them. Then `pytest tests/unit`, push, `gh pr create --fill` |
| `deploy-pipeline` | `gh workflow run terraform.yml --ref main -f target=pipeline`. The run waits for the `snowflake-dev` approval like any apply |

### Files

| File | Notes |
|------|-------|
| `Makefile` (shared) | Targets above; `.PHONY` updated |
| `tests/unit/test_makefile.py` (new) | 26 tests, all via `make -n` or by reading the file. The PROTOCOL §3 table and the Makefile windows must match. Unknown `WINDOW` fails. No `terraform apply`, `destroy`, `gh pr merge` or `--auto` anywhere in the Makefile (R1). The profile targets prepare a draft PR from `origin/main` and cite REQ-07. The timeout branch is inert without `TIMEOUT_MS`. `batch-window` touches one key. `deploy-pipeline` matches the workflow's `target` input |

### Commands and results

| Command | Result |
|---------|--------|
| `ruff check .` | ✅ |
| `pytest tests/unit -q` | ✅ 211 passed (26 new) |
| `bash -n scripts/*.sh` | ✅ (`make ci-local`'s `yamllint` half needs `yamllint`, which is not installed on this machine — pre-existing; CI `lint` runs it) |
| `make -n` on every new target | ✅ expansions as expected |
| **End to end** in a throwaway clone (local bare `origin`, fake `gh` and `docker` on `PATH`; nothing left the machine) | ✅ `profile-a SWITCH=S2 AT=…`: branch on origin only, `dev.tfvars` diff, commit `chore(profile): cost_profile = baseline (REQ-07)`, draft `gh pr create` with the right title, no worktree or local branch left. `profile-b` on an already-optimized `main`: exit 1, nothing left. `profile-b TIMEOUT_MS=12000`: line appended with a comment. `TIMEOUT_MS=12s` and `N=ten` rejected. `batch-window` on an `.env` without a trailing newline: key appended on its own line, then rewritten in place; `switch.log` gets its header and lines |
| Mutation checks | A wrong window date in the Makefile fails 2 tests. Adding `gh pr merge` fails 1 test. The Makefile was restored and checked identical to a backup with `diff` |

### Deviations from DESIGN 1.4

| Deviation | Reason | Impact |
|-----------|--------|--------|
| `deploy-pipeline` **dispatches** the `terraform.yml` workflow instead of "only opening/merging PRs" (Decision 1, *Consequences*) | Decision 11.4 defines the first pipeline apply as a `workflow_dispatch`; the DESIGN is inconsistent between the two. Owner decision 2026-11-23: follow Decision 11 and record it here, no DESIGN revision | None: the run still waits for the `snowflake-dev` reviewer; nothing is applied by `make` |
| `deploy-platform` opens the PR of the current branch after local checks (the DESIGN does not define its steps) | The platform apply is a push to `main` (Decision 11.3), so "deploying" means opening the PR | — |
| New targets `load-plan` and `batch-window`, beyond `deploy-*`, `profile-*`, `load` and `dry-run` | `batch-window` is the Dagster half of the switch (Decision 2; PROTOCOL §4 step 2), which has to happen in the same minute; `load-plan` is the safe first step of PROTOCOL §3 | — |
| Profile PRs open as **drafts** | Prepared in advance; a draft cannot be merged by accident before the switch time | At the switch: `gh pr ready <n>`, then merge |
| `tests/unit/test_makefile.py` is not in the `_index` ownership map | New file, only this feature uses it | Add it to the map with the next `_index` change |
| `gate_task_timeout_ms` written into the shared `dev.tfvars` | Already the documented place (variable description, Decision 5) | The `platform` root warns "undeclared variable" (known, O22) |

### Open issues (new)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O44 | `load` sources `.env` with `sh` (`set -a; . ./.env`). Docker's `env_file` format allows values that `sh` reads differently, such as unquoted spaces or `$`. If a value breaks, quote it in `.env`. No value is printed either way | First `make load` | Christian |
| O45 | `POSTGRES_HOST` and `POSTGRES_PORT` are not in `.env.example`. The generator defaults to `localhost:5432`, which is right when it runs on the stack host. On a separate VM, set them (item 21) | Before Day 7, if a VM is used | Christian |

---

## Run 9 — 2026-11-23 — manifest item 21 (draft) and GitHub settings

Branch `feat/cost-governance-item-21`, from `main` (`cd712af`). Requirements: **REQ-07**
(`BATCH_WINDOW_MINUTES` and the load identity for the protocol), **REQ-08** (CI gates). DESIGN 1.4,
no revision. **Shared files touched: `.env.example`, `CLAUDE.md`.**

**Agent Assignment deviation (owner decision 2026-11-23):** item 21 is owner-authored. The build agent
drafted it because O30 and O45 are needed before the dry run. The owner edits it in the PR.

### GitHub settings changed (owner decision 2026-11-23; no secret handled)

| Setting | Before | After | Closes |
|---------|--------|-------|--------|
| Ruleset `main protection (O40)`, id 27924450, on the default branch | `main` unprotected | PR required (0 approvals: one author), required checks `lint` + `validate` (`ci.yml` job names), no deletion, no force push, **no bypass actors** (admins included) | **O40** |
| Environment `snowflake-dev`: deployment branches | any branch | custom policy: `main` only. Reviewer `christiandrocha` re-sent in the same call and checked afterwards | O24 (the environment half) |
| Repository variable `SNOWFLAKE_ACCOUNT` | — | `GWHUBCF-QQ53235` | O39 (part) |
| `snowflake-plan` variable `SNOWFLAKE_USER` | — | `TERRAFORM_PLAN_SVC` | O39 (part) |
| `snowflake-dev` variables `SNOWFLAKE_USER`, `SNOWFLAKE_PLAN_USER` | — | `TERRAFORM_SVC`, `TERRAFORM_PLAN_SVC` | O39 (part) |

**Still missing for O39**, and set by the owner after the bootstrap:
- repository variables `TF_STATE_BUCKET`, `TF_STATE_REGION` and the three `*_RSA_PUBLIC_KEY`;
- `AWS_ROLE_ARN` in each environment;
- every secret: the two private keys in `snowflake-dev`, one in `snowflake-plan`, and
  `BUDGET_NOTIFY_EMAIL`.

The required checks do not include `terraform.yml`'s `static` or `plan` jobs, because that
workflow runs only on Terraform paths. A docs-only PR would wait for them forever.

### Files

| File | Notes |
|------|-------|
| `.env.example` (shared) | New *Measurement* section. `BATCH_WINDOW_MINUTES=10` (matches `optimized` on `main`), with the rule that it switches with `cost_profile` through `make batch-window` (O30). `POSTGRES_HOST`/`POSTGRES_PORT` for the generator on the host (O45). `LOAD_SNOWFLAKE_USER`, `LOAD_SNOWFLAKE_PRIVATE_KEY_PATH` (host path) and an optional passphrase. `LOAD_*` calibration variables commented out, with the PROTOCOL rule. The `postgres` container also reads `.env`, but the official image does not use `POSTGRES_HOST` or `POSTGRES_PORT` (it reads `PGPORT`) |
| `CLAUDE.md` (shared) | Two rows in *Environments and names*: the profile switch (both halves, the `make` targets) and the GitHub protection. New section *Measurement windows*: no `CDC_WH`, no stack-reaching merges other than the switch PR, no SCD2 account or Postgres work while a window is open |

### Commands and results

| Command | Result |
|---------|--------|
| `sh -c 'set -a; . ./.env.example'` (how `make load` reads `.env`) | ✅ values parse (O44 check on the template) |
| `ruff check .` · `pytest tests/unit -q` | ✅ · ✅ 211 passed (no code changed) |
| `gh api` read-back of the ruleset, environment policy and variables | ✅ as in the table above |

### Open issues (closed / new)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O30 | ~~`BATCH_WINDOW_MINUTES` not in `.env.example`~~ — **closed** (draft) | — | — |
| O40 | ~~`main` not protected~~ — **closed** | — | — |
| O45 | ~~`POSTGRES_HOST`/`POSTGRES_PORT` not in `.env.example`~~ — **closed** (draft) | — | — |
| O46 | With the ruleset, **every** change to `main` goes through a PR with green `lint` + `validate`, the switch PRs at 00:00 UTC included. CI takes ~35 s; open the switch PR as ready a few minutes early, so the checks are green at 00:00 | S2, S3 | Christian |

---

## Next Step

Builder-owned manifest items are all built (1–14, 16–18 and 20; 20 merged in #14, `3ea3c29`, CI green; `test_makefile.py` added to the `_index` ownership map). Item 15 drafted in
run 7 and merged (#10); item 21 drafted in run 9 and merged (#16, `c46e6f8`, CI green through the new `main` ruleset). Remaining: 19 (runbooks), 22 (README,
Day 14) — owner-authored. **Needed before S0 / the dry run (2026-11-24 12:00 UTC):** credit price (O1), state
backend bootstrap, Terraform identities, the rest of the repository variables and every secret (O39), then the first apply
through CI with approval (O43).
When every manifest item is built: `/sdd-validate COST_GOVERNANCE` in a fresh chat.
