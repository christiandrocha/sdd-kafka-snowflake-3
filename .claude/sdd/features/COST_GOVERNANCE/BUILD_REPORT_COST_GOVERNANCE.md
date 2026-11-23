# BUILD REPORT: Cost Governance 2.0 (COST_GOVERNANCE)

> Implementation report for COST_GOVERNANCE. One section per `/sdd-build` run; append, never rewrite.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COST_GOVERNANCE |
| **Date** | 2026-11-18 |
| **Author** | build-agent (Claude Code), owner Christian |
| **DEFINE** | [DEFINE_COST_GOVERNANCE.md](./DEFINE_COST_GOVERNANCE.md) — v1.4 |
| **DESIGN** | [DESIGN_COST_GOVERNANCE.md](./DESIGN_COST_GOVERNANCE.md) — v1.3 |
| **Status** | In Progress — items 1–9 and 16–18 built (15: `queries.sql` draft only); 10–14, 15, 19–22 pending |

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
   validate at the Day 3 apply**. The DESIGN 1.4 text below (numbered 1.3 when written) is ready in case it has to move to
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

### DESIGN 1.4 — prepared, NOT applied (only if the Day 3 apply rejects SECURITYADMIN)

(Numbered 1.3 when written in run 3; renumbered after run 4 used 1.3 for the Decision 11 consequence.)

Apply only if the platform apply fails on
`snowflake_grant_privileges_to_account_role.sysadmin_execute_task` with an insufficient-privileges
error. Paste the error into the row.

- **Decision 9, named-exception table**, new row:
  `| snowflake_grant_privileges_to_account_role.sysadmin_execute_task (EXECUTE TASK, EXECUTE MANAGED TASK on account → SYSADMIN) | SECURITYADMIN's MANAGE GRANTS was rejected for these global privileges at the Day 3 apply: "<error text>" | Day 3 apply log (run <id>) |`
- **Revision history:**
  `| 1.4 | <date> | Christian (with Claude) | Day 3 apply: SECURITYADMIN cannot grant EXECUTE TASK / EXECUTE MANAGED TASK; the grant joins the accountadmin named list. No scope change. |`
- **Code, same PR:** `provider = snowflake.accountadmin # Decision 9 named exception` on that
  resource. Add it to `ACCOUNTADMIN_ALLOWED` in `test_terraform_providers.py`. Change the
  assertion in `test_execute_task_privileges_are_granted_by_platform` to `accountadmin`.

### Open issues (new)

| # | Issue | Needed by | Owner |
|---|-------|-----------|-------|
| O16 | **Hypothesis:** SECURITYADMIN can grant `EXECUTE TASK` / `EXECUTE MANAGED TASK`. If the apply fails, use DESIGN 1.4 above | Day 3 apply | build-agent |
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

## Next Step

Owner reviews the PR for items 16–18, then runs the bootstrap (`docs/runbooks/terraform-state-bootstrap.md`,
`scripts/00_terraform_bootstrap.sql`) and the pre-apply checklist (credit price, probe P1, owner user,
secrets) before the Day 3 apply. Next build: `/sdd-build COST_GOVERNANCE items 10-14` (Python), then
19–22 (owner-authored docs; item 21 shared files).
When every manifest item is built: `/sdd-validate COST_GOVERNANCE` in a fresh chat.
