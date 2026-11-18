# BUILD REPORT: Cost Governance 2.0 (COST_GOVERNANCE)

> Implementation report for COST_GOVERNANCE. One section per `/sdd-build` run; append, never rewrite.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COST_GOVERNANCE |
| **Date** | 2026-11-18 |
| **Author** | build-agent (Claude Code), owner Christian |
| **DEFINE** | [DEFINE_COST_GOVERNANCE.md](./DEFINE_COST_GOVERNANCE.md) — v1.4 |
| **DESIGN** | [DESIGN_COST_GOVERNANCE.md](./DESIGN_COST_GOVERNANCE.md) — v1.1 |
| **Status** | In Progress — items 1–4 built; 5–22 pending |

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

## Next Step

Owner reviews and merges the PR for items 1–4 (CI apply comes with item 16). Then
`/sdd-build COST_GOVERNANCE items 5-6` (seed + `budget.sql` + `account_monitor.sql`).
When every manifest item is built: `/sdd-validate COST_GOVERNANCE` in a fresh chat.
