# DESIGN: Cost Governance 2.0 (COST_GOVERNANCE)

> Technical design for cutting billed warehouse uptime, delivering it as Terraform, and measuring
> the effect with a controlled A/B on the trial account.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COST_GOVERNANCE |
| **Date** | 2026-11-17 |
| **Author** | Christian (with Claude) |
| **DEFINE** | [DEFINE_COST_GOVERNANCE.md](./DEFINE_COST_GOVERNANCE.md) — v1.4 |
| **Status** | 1.5 — In Build (1.5: owner decision on the spending limits after reading the credit price, 2026-11-24; ready for Build since the owner review of the 1.3 → 1.4 diff, 2026-11-18; 1.1–1.3 owner decisions; 1.0 signed off by independent review 2026-11-18) |

---

## Findings that shaped this design (verified 2026-11-17)

| # | Finding | Source | Effect on the design |
|---|---------|--------|----------------------|
| F1 | The Snowflake Terraform provider added the warehouse `generation` field in **v2.7.0**. | provider release notes v2.7.0 | Pin provider `>= 2.7`. |
| F2 | **Resource monitors cover warehouses only**, account-level included. Serverless spend is tracked by **budgets**. | Snowflake docs, *Working with resource monitors* | Serverless gate tasks leave the monitor's brake (Decision 5). |
| F3 | "A nominal charge accrues each time a task evaluates its `WHEN` condition and does not run." | Snowflake docs, `ALTER TASK` | v2's "a false `WHEN` costs nothing" is approximate; measured in the idle window (Decision 10). **Which view records it** (`SERVERLESS_TASK_HISTORY` or cloud services in `METERING_HISTORY`) is not documented: the dry run checks both, so the idle criterion cannot read zero by construction. |
| F4 | Serverless compute billed per second, rounded up; serverless tasks at a 0.9 multiplier per third-party readings of the consumption table; no minimum stated on the tasks page. | Snowflake *Understanding compute cost*; select.dev, getorchestra | A-003 partially validated; the A/B settles it. |
| F5 | Bronze tables are created by the Kafka connector (`enable.schematization=true`). Streams need existing tables. | v2 connector config, v2 `deploy.yml` order | Two Terraform roots (Decision 1). |
| F6 | `RESOURCE_CONSTRAINT = 'STANDARD_GEN_1'` is rejected on this account; `GENERATION = '1'` works. New warehouses default to Gen2 with query acceleration on. Read-back: after `CREATE WAREHOUSE … GENERATION = '1'`, `SHOW WAREHOUSES` returned `resource_constraint = STANDARD_GEN_1` and `generation = 1` (the constraint is rejected on write but reported on read). Provider side (2.23.0 schema, read 2026-11-18): `snowflake_warehouse.generation` accepts `1` \| `2`; `resource_constraint` is documented as "only available for snowpark-optimized warehouses. For setting generation please use the `generation` field" — so the config sets `generation` only and never `resource_constraint`. | Live probe on `GWHUBCF-QQ53235`, 2026-11-17; provider schema 2.23.0 (`terraform providers schema -json`), 2026-11-18 | DEFINE 1.1 REQ-02; AT-002 output format (Build checklist B4); Decision 4 sets `generation` only. |
| F7 | Budgets can call a **stored procedure** when actual or projected spend reaches a threshold (custom actions), and another one when the cycle restarts. A custom budget that contains a database monitors the serverless tasks in it. | Snowflake docs, *Custom actions for budgets*; release notes 2025-12-10 and 2026-02-24; *Budgets* | An automatic action that suspends the gate tasks is possible (Decision 5). |
| F8 | Budget spend data refreshes with a delay: `TIER_6H` (default) "up to 6.5 hours"; `TIER_1H` one hour, at a budget cost "12 times higher" than the default (absolute cost not stated). **Actual**-trigger custom actions run at most once a month; failed actions are retried once, so the procedure must be idempotent. | Snowflake docs, [`SET_REFRESH_TIER`](https://docs.snowflake.com/en/sql-reference/classes/budget/methods/set_refresh_tier), [*Custom actions for budgets*](https://docs.snowflake.com/en/user-guide/budgets/custom-actions) (read 2026-11-18; replaces the 1.0 third-party source) | The budget action is a backstop, not a fast brake. `TIER_1H` chosen (owner decision 2026-11-18); its own cost is measured in the dry run and is identical in windows A and B. |
| F9 | A resource monitor with `FREQUENCY = NEVER` never resets its used credits. | Snowflake docs, `CREATE RESOURCE MONITOR` | Monitors sized for the whole trial, not per calendar month (Decision 8). |
| F10 | v2's `CDC_WH` had query acceleration **on** (scale factor 2), read on 2026-08-11; it never engaged in 30 days. `00_account_bootstrap.sql` says `FALSE`, but `CREATE … IF NOT EXISTS` never altered the existing warehouse. | v2 README *Cost governance*, `scripts/snowflake_setup.sql` | Profile A deviates from v2 on this one setting, by owner decision (see Cost profiles). |
| F11 | The latest provider is **2.23.0**. `snowflake_table`, `snowflake_procedure_sql` and `snowflake_current_account` are **preview features**: they must be listed in the provider's `preview_features_enabled`, and "may have breaking changes in future releases, even without raising the major version". | provider schema 2.23.0, `preview_features_enabled` description (read 2026-11-18) | `terraform/platform` enables exactly `snowflake_table_resource` and `snowflake_procedure_sql_resource`; the exact provider version is pinned in `.terraform.lock.hcl` (Decision 4) and upgraded only by PR. Risk added. |
| F12 | `snowflake_current_account` can set the account-level monitor (`resource_monitor`), but it is a preview resource and "external changes for this field won't be detected". | provider schema 2.23.0 (read 2026-11-18) | **Not used** (owner decision 2026-11-18): exception 3 stays as CI SQL (Decision 9). Recorded as a future alternative once the resource leaves preview. |
| F13 | The provider has **no resource for budgets or budget custom actions** (154 resources in 2.23.0, none for budgets). | provider schema 2.23.0 (read 2026-11-18) | Exception 2 (`budget.sql`) confirmed. |
| F14 | "Only users with the ACCOUNTADMIN role can create a resource monitor", "… can **assign warehouses** to resource monitors" and "… can set a resource monitor to monitor the account". A role with **MONITOR or MODIFY** on a monitor can see it in `SHOW RESOURCE MONITORS`. The provider's `snowflake_warehouse.resource_monitor` is a plain optional field (not computed), so an assignment made outside the warehouse resource shows as a diff on every plan. **Probe P1 (Appendix), run by the owner in Snowsight 2026-11-24:** P1.3 `ALTER WAREHOUSE PROBE_WH_P1 SET RESOURCE_MONITOR` as `ACCOUNTADMIN` → success; P1.4 `SHOW WAREHOUSES` → `resource_monitor = PROBE_RM_P1` on both warehouses, `STANDARD_GEN_1`. **P1.1 and P1.2 as `SYSADMIN` → success, owner `SYSADMIN` — inconclusive**: the owner's user has `DEFAULT_SECONDARY_ROLES = ["ALL"]`, so ACCOUNTADMIN counted for the privilege check while SYSADMIN, the primary role, took ownership. A rerun after `USE SECONDARY ROLES NONE` still read back `CURRENT_SECONDARY_ROLES() = {"roles":"ACCOUNTADMIN,ORGADMIN","value":"ALL"}` in the worksheet, so it proves nothing either way. Consequence: `00_terraform_bootstrap.sql` sets `DEFAULT_SECONDARY_ROLES = ()` on both service users (1.5), so each provider alias holds only its own role; the first apply with that setting is the real test of the SYSADMIN half. | Snowflake docs, [*Working with resource monitors* — Assigning warehouses to a resource monitor](https://docs.snowflake.com/en/user-guide/resource-monitors#assigning-warehouses-to-a-resource-monitor) and [Setting a resource monitor for your account](https://docs.snowflake.com/en/user-guide/resource-monitors#setting-a-resource-monitor-for-your-account); [`ALTER WAREHOUSE`, access control](https://docs.snowflake.com/en/sql-reference/sql/alter-warehouse) (read 2026-11-18); provider schema 2.23.0 | Pattern 2 as written in 1.0 (`provider = snowflake.sysadmin` with `resource_monitor`) cannot apply. `CDC_WH` is created by the `accountadmin` alias — a named exception in Decision 9. The read-only plan role gets MONITOR on both monitors (Decision 9). |
| F15 | Credit price on this account: **USD 4.65** per credit (`WAREHOUSE_METERING`, `compute`), the same on 2026-11-17 and 2026-11-23 — the Enterprise on-demand rate for AWS São Paulo in third-party price tables. Remaining trial balance **USD 395.14** on 2026-11-24 (`free_usage_balance`; the view lags up to 24 h). *Admin → Billing* shows nothing on this trial. | `SNOWFLAKE.ORGANIZATION_USAGE.RATE_SHEET_DAILY`, `REMAINING_BALANCE_DAILY`, read by the owner in Snowsight 2026-11-24 | Balance ≈ **85 credits**, so the 1.2 worst case (~63 credits ≈ USD 293, 74%) breaks the ~50% rule of Decision 8. Limits lowered in 1.5 (Decision 8). |

---

## Architecture Overview

```text
 GitHub Actions                                   Snowflake trial account GWHUBCF-QQ53235 (AWS sa-east-1)
 ─────────────                                   ─────────────────────────────────────────────────────────
 PR (same repo): fmt · validate · plan  ── env snowflake-plan (read-only identity, no reviewer)
 PR (fork):      fmt · validate only
 main:           plan → apply           ── env snowflake-dev  (TERRAFORM_SVC, required reviewer)
                                          ▼
   terraform/platform  ──────────────► DB CDC_POC (BRONZE/SILVER/GOLD/CONFIG) · CONFIG tables
     (account-level)                     WH CDC_WH (generation, QA off) · roles · service users · grants
                                         CONFIG.SP_SUSPEND_GATE_TASKS (called by the budget)
                                         monitors: CDC_WH + account (FREQUENCY = NEVER)
          │
          ▼  scripts/seed_config.sql     (CI step): TABLE_METADATA seed — data, not objects
          ▼  scripts/account_monitor.sql (CI step): ALTER ACCOUNT SET RESOURCE_MONITOR (exception 3)
          ▼  scripts/budget.sql          (CI step): custom budget on CDC_POC + custom action (exception 2)
          │
   [ stack up · connectors registered · first CDC rows land → Bronze tables exist ]   ← F5
          │
          ▼
   terraform/pipeline  ──────────────► CONFIG.SP_GATE_DOMAIN
     (needs Bronze;                      10 × stream (append-only) · 10 × gate task
      plan skipped until then)           task_compute = "warehouse" (A) | "serverless" (B)

 Local stack (Docker Compose)
 ────────────────────────────
 tests/load/generate_load.py ──► Postgres ──► Debezium ──► Kafka ──► Snowpipe Streaming ──► Bronze
   (seeded clusters, commit log)                  │                                            │ stream
                                                  └──► Prometheus ◄── sensor gate (0 credits)  │
                                                                         │                     ▼
                                       Dagster bronze_new_data_sensor ◄── CONFIG.PENDING_RUNS ◄─ gate task
                                         settle + window N (profile B)
                                                   │
                                                   ▼
                                       cdc_pipeline_job: dbt run + test ──► Silver/Gold ──► PROCESSING_LOG
```

**Cost profiles.** One codebase, two profiles selected by a versioned `tfvars` value and one Dagster
env var — the A/B is a configuration switch on the same objects (Decision 2):

| Setting | Profile A — `baseline` (v2 behaviour) | Profile B — `optimized` (v3) |
|---------|---------------------------------------|------------------------------|
| `CDC_WH` generation | `'2'` | `'1'` |
| Query acceleration | **off** — deviation from v2 (F10), owner decision 2026-11-17; v2's never engaged | off |
| Gate tasks | on `CDC_WH`, **no** timeout or failure limit (as v2) | serverless, `XSMALL` cap, timeout from the dry run, suspend after 3 failures |
| Dagster batching | none (`BATCH_WINDOW_MINUTES=0`, v2 hot cycles) | settle + window *N* = 10 min |
| Auto-suspend | 60 s | 60 s |

AT-002 (generation 1) is verified in profile B; in profile A it fails by construction.

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `terraform/platform` | Database, schemas, CONFIG tables, warehouse, roles, users, grants, monitors, `SP_SUSPEND_GATE_TASKS` | Terraform ≥ 1.11, `snowflakedb/snowflake` ≥ 2.7, < 3.0 |
| `terraform/pipeline` | Gate procedure, streams, tasks over connector-created Bronze tables | Same provider; `for_each` over the 10 Tier-1 domains |
| `terraform/env/dev.tfvars` | The only place `cost_profile` and limits are set; changed by PR | HCL |
| `scripts/00_terraform_bootstrap.sql` | One-time manual step: Terraform identities (Decision 9) | SQL, run once as `ACCOUNTADMIN` |
| `scripts/seed_config.sql` | `TABLE_METADATA` seed (renamed from `bootstrap_config.sql`, DDL moved to Terraform) | SQL, CI step |
| `terraform/platform` `CDC_CI_WH` | Warehouse for the CI SQL steps; keeps CI off `CDC_WH` during the windows | Terraform (`sysadmin` alias; covered by the account monitor) |
| `scripts/account_monitor.sql` | Assigns the Terraform-created `account_monitor` to the account; idempotent | SQL, CI step (exception 3) |
| `scripts/budget.sql` | Custom budget on `CDC_POC`, limit, refresh tier, e-mail, custom action; no cycle-start action | SQL, CI step (exception 2), role `CDC_BUDGET_ADMIN` |
| `scripts/verify_governance.sql` | Read-only account checks for AT-002/003/004 | SQL |
| `dagster/pipeline/gate.py` | Pure decision function for the sensor | Python |
| `dagster/pipeline/sensors.py`, `jobs.py` | Sensor uses `gate.decide`; job records the consumed `run_key` | Python, Dagster |
| `tests/load/generate_load.py` | Seeded, fixed-schedule load generator; writes a commit log | Python, psycopg2 |
| `docs/measurement/` | Protocol, queries, attribution method, results template | Markdown + SQL |
| `docs/runbooks/` | Connector down; monitor suspended; budget alert; gate task failure; after the trial | Markdown |
| `.github/workflows/terraform.yml` | Plan on PR, plan + approved apply on `main` | GitHub Actions |

---

## Key Decisions

### Decision 1: Two Terraform roots, with the Bronze landing in between

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** Streams need existing tables (F5); Bronze tables appear on the connector's first write.

**Choice:** `terraform/platform` (nothing that depends on data, including the budget's suspend
procedure — a SQL procedure resolves the tasks it alters at call time, so it can exist before them)
and `terraform/pipeline` (gate procedure, streams, tasks). Order: platform → `seed_config.sql` → `budget.sql` → stack + connectors → first rows
land → pipeline. Until the Bronze tables exist, the CI step for `pipeline` **skips its plan with a
notice** instead of failing, so PRs are not red for a reason unrelated to the change.

**Rationale:** Terraform owns every cost-relevant object (REQ-01) while the connector keeps owning the
Bronze schema.

**Alternatives rejected:**
1. Terraform creates Bronze tables — schematization evolves their columns; permanent drift.
2. Streams/tasks as hand-run SQL (v2) — they hold the A/B switch; they must be code.
3. One root waiting on data inside `apply` — hides an operational step; a first deploy would hang.

**Consequences:** a first deploy is two applies with a documented gap (`make deploy-platform`, then
`make deploy-pipeline` — both only open/merge PRs; applies run in CI).

---

### Decision 2: One codebase, two cost profiles, switched by PR at 00:00 UTC

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** A/B on identical load, on an account where v2 never ran; Constitution R1 forbids local
`apply`; the DEFINE aggregates credits per UTC day.

**Choice:**
- `cost_profile` (`baseline` | `optimized`) lives **only** in `terraform/env/dev.tfvars`, so every CI
  apply uses the committed value and nothing silently reverts to a default.
- A switch is a one-line PR prepared in advance and merged + apply-approved at **00:00 UTC
  (21:00 in Vitória)**, together with `BATCH_WINDOW_MINUTES` in the local Dagster `.env` and a
  Dagster restart. Actual switch time is logged in `docs/measurement/runs/switch.log`.
- `make profile-a` / `make profile-b` only **prepare the PR**; they never apply.

**Rationale:** the only differences between A and B are the ones under test; UTC days stay whole;
the switch happens at a humane local hour and through the same guarded path as any change.

**Alternatives rejected:**
1. Two parallel stacks — doubles ingestion, shared account metering blurs attribution.
2. Compare with v2's historical figures — different account and load.
3. Switch at 03:00 UTC (draft 0.3) — mixed A and B inside UTC days; midnight in Vitória.

**Consequences:** minutes between 00:00 UTC and the approved apply run in the previous profile; they
are reported, not hidden. `baseline` stays in the code after v3 ships as executable documentation.

---

### Decision 3: Keep the v2 object names; drop the `_V3` suffix; no dbt changes

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** The suffix existed for coexistence with v2, which is not on this account; Decision 2
removes parallel copies. The DEFINE forbids dbt changes in this feature.

**Choice:** Terraform variables with v2's names as defaults (`CDC_POC`, `CDC_WH`, `CDC_ROLE`,
`CDC_ROLE_RO`). `dbt/models/config/sources.yml` keeps its hard-coded `CDC_POC` (owner decision
2026-11-17); making the database name configurable in dbt goes to the roadmap.

**Consequences:** AT-002 reads `var.warehouse_name` (default `CDC_WH`) — DEFINE revision 1.3.
`CLAUDE.md` updated in the Build PR.

---

### Decision 4: Gen1 through `generation = "1"`, provider pinned ≥ 2.7

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Choice:** `generation = local.profile.generation`, `enable_query_acceleration = false`,
`warehouse_size = "XSMALL"`, `auto_suspend = 60`, `auto_resume = true`, `initially_suspended = true`,
`resource_monitor = <cdc_wh monitor>`, created by the **`accountadmin` provider alias** — only
ACCOUNTADMIN can assign a warehouse to a monitor (F14), and assigning it outside the resource would
show as a permanent diff. `resource_constraint` is never set (F6). Provider `>= 2.7.0, < 3.0.0`, exact
version in `.terraform.lock.hcl` (2.23.0 at Build; F11).

**Consequences:** the provider reads generation back through `resource_constraint` for standard
warehouses; the Build confirms a clean second `plan` (AT-001). Drift, if any, is documented — never
hidden with `ignore_changes`. `CDC_WH` is **owned by ACCOUNTADMIN**, not SYSADMIN (owner decision
2026-11-18): `CDC_ROLE` and `CDC_ROLE_RO` keep only USAGE/OPERATE, and the README lists it with the
other ACCOUNTADMIN-owned objects (Decision 9).

---

### Decision 5: Serverless gate tasks — the brake moved, with its limits written down

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** REQ-04 moves the gate tasks off `CDC_WH`; F2 means no monitor sees their spend. Per-task
caps bound the **rate** of spend, not the **total** (review finding 8).

**Choice (profile B):** each gate task is serverless with
`user_task_managed_initial_warehouse_size = "XSMALL"`, `SERVERLESS_TASK_MAX_STATEMENT_SIZE = 'XSMALL'`,
`user_task_timeout_ms` **provisional 10 000 ms**, set after the dry run to max(10 s, 5 × the p99 run
duration in `TASK_HISTORY`) — a healthy run *should* be two sub-second `INSERT`s, but that is not yet
measured, nor whether serverless start-up counts toward the timeout;
`suspend_task_after_num_failures = 3`, `schedule = 1 minute`, `when = SYSTEM$STREAM_HAS_DATA(…)`.
On top, a **custom budget** scoped to `CDC_POC` (F7) with:
- a monthly limit and Snowflake's notifications;
- a custom action on **actual** spend at 100% calling `CONFIG.SP_SUSPEND_GATE_TASKS()`, which
  suspends the ten gate tasks;
- **no cycle-start action** (owner decision 2026-11-18): `budget.sql` calls
  `REMOVE_CYCLE_START_ACTION` so none can linger, and nothing resumes the tasks automatically —
  resuming is a human step in the `budget-alert` runbook, after the cause is understood;
- refresh tier `TIER_1H` (F8, owner decision 2026-11-18).

**The numbers, stated plainly:**
- Healthy case: ~10 runs/burst × < 1 s — negligible next to warehouse uptime.
- Pathological worst case (every task times out every minute): 10 × 10 s per minute = 100 s/min of
  XSMALL ≈ 1.67 compute-hours/hour × 0.9 ≈ **1.5 credits/hour**.
- Detection delay of the budget action (F8): ~1 h on `TIER_1H` → worst-case exposure ≈ **1.5 credits**
  before the action fires (it would be ≈ 9.75 on the default 6.5-hour tier).

**A task that suspends itself must not go unnoticed.** After each load cluster the generator runs
`SHOW TASKS IN SCHEMA CDC_POC.BRONZE` on a connection **without a warehouse** (metadata only, no
resume) and logs each task's state; any task not `started` is written to stderr and to
`runs/<window>/task_states.csv`. A window in which any gate task was suspended is void (validity rules).
Profile A applies **neither** the timeout nor the failure limit, to stay identical to v2.

**Rationale:** the timeout bounds the rate mechanically; the budget action bounds the total
automatically, with a known delay; the runbook covers the human part. Compared with v2, the README
claim becomes accurate: "monitors cap warehouses; gate tasks are capped by size and timeout; a budget
suspends them if their total spend passes a limit — with a refresh delay of up to N hours."

**Alternatives rejected:**
1. Keep tasks on the warehouse — the cost under measurement.
2. Timeout of 60 s (draft 0.3) — worst case ~9 credits/hour.
3. True triggered tasks — out of scope by DEFINE; serverless triggered tasks also require a target
   completion interval. Candidate ADR.

---

### Decision 6: Batching = "wait for the burst to settle, then run once", with an explicit pending flag

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** REQ-05 asks for a minimum interval *N* between runs without losing pending rows. Two traps
in the obvious implementation:
1. **Stranding.** v2 only touches Snowflake for 3 cycles after the last Kafka activity; with *N* = 10
   those cycles expire inside the window and rows wait for the next burst — possibly forever.
2. **Two runs per burst.** Running on the first sign of a burst and again after the window pays two
   resumes per burst.

**Choice:** a pure function in `dagster/pipeline/gate.py`, state
`{quiet, last_run_at, pending, pending_since, retries, initialized}`, `quiet` = cycles since the last
Kafka activity.
- **Profile A (`N = 0`):** reproduce v2 exactly — query on the activity cycle and the next 3.
- **Profile B (`N > 0`):** query only when `pending` is set, `now − last_run_at ≥ N`, and **either**
  the burst has **settled** (`quiet ≥ QUIET_CYCLES`, default 3) **or** it has been pending for ≥ *N*
  (**starvation guard** for continuous traffic). If a settled query finds no rows, one more settled
  check, then `pending` clears. A run made mid-burst (starvation guard) keeps `pending` set.
  **An empty starvation-guard query restarts the starvation clock** (`pending_since = now`): the
  next guard query waits another *N* (1.4).

**Why `QUIET_CYCLES = 3` is enough:** "Kafka activity" is the broker receiving the message, not the
Bronze commit. Between the two sit the connector's flush, Snowpipe Streaming's commit (seconds), the
Prometheus scrape interval (15 s in v2) and the gate task's next tick (≤ 60 s). Three minutes covers
that chain with margin; the dry run measures it, and the value is a constant, not a guess baked in.

**Found in review (2026-11-17):** simulating draft 0.2 showed two runs per burst; draft 0.3 showed
starvation under continuous traffic. Draft 0.4 passed an ad-hoc simulation (legacy parity with v2 on 500 random
sequences; no stranded row and a worst wait of 10 min on 2,000) **that is not in the repository**:
these results are to be reproduced by `tests/unit/test_gate.py` at Build, which becomes the evidence.
The test file covers those cases plus the
"empty starvation-guard query followed by an immediate retry" case (at most two consecutive queries).

**Found at Build (2026-11-18, revision 1.4):** draft 0.4 / 1.0–1.3 (Pattern 4) breaks the "at most
two consecutive queries" claim under **continuous Kafka traffic with an empty `PENDING_RUNS`**. That
is the state when the gate tasks are suspended (budget action, 3 failures) while load continues.
Each activity cycle resets `retries` but keeps `pending_since`, so after the first empty guard query
`waited_enough` and `window_open` stay true and the sensor queries **every minute**: 50 queries in
60 min with *N* = 10. `CDC_WH` never suspends, which is v2's ~24 credits/day failure mode. Fix: an
empty query that was **not** settled (a starvation-guard query) sets `pending_since = now` and leaves
`retries` alone. The one-more-check retry applies only to settled queries. Same scenario after the
fix: one query per *N* (minutes 10, 20, 30, 40, 50). The simulation is kept as a regression test in
`tests/unit/test_gate.py`.

**Consequences:** profile B adds up to `QUIET_CYCLES` minutes of latency per burst, inside the
freshness guardrail (p95 ≤ *N* + 5). A gate task that fires more than 2 × `QUIET_CYCLES` minutes after
its burst leaves its row for the next one — delayed, never lost; AT-006 measures it.

---

### Decision 7: Freshness = the run that actually consumed the burst

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** "first Gold `finished_at` after `committed_at`" (draft 0.3) can pick a run that started
before the burst reached Bronze — common in profile A, which runs almost every minute (review
finding 5).

**Choice:** `PENDING_RUNS` gains `consumed_run_key`, written by the sensor in the same `UPDATE` that
marks rows consumed. `log_processing_results` (`dagster/pipeline/assets.py`, the code that writes
`PROCESSING_LOG`) writes the same key, read from the run's `dagster/run_key` tag (1.4: the 1.0–1.3
text said "the job", but `jobs.py` does not write `PROCESSING_LOG`). The sensor runs the `UPDATE`
**first** and then reads the rows it marked (`WHERE consumed_run_key = :key`). The marked set is
then exactly the set the run reports, with no window between a `SELECT` and an `UPDATE` (1.4).

**A run that fails after the `UPDATE` (1.4): reprocess, never accept the loss.** A `PENDING_RUNS`
row is a trigger, not data: every `cdc_pipeline_job` run rebuilds all models over all of Bronze,
idempotently (Bronze `merge`), so no CDC row is lost either way. What a failed run can lose is
the **trigger** and the **attribution**. Its rows are marked consumed by a key that never reaches
Gold, so freshness would pin the burst to a run that produced nothing. Choice: a
`run_failure_sensor` on `cdc_pipeline_job`, `pending_run_release_sensor` in `sensors.py`, runs
`UPDATE … SET consumed = FALSE, consumed_run_key = NULL WHERE consumed_run_key = :failed_key`. The
rows go back to pending; the next gate query re-triggers them and is attributed to the run that
actually consumes them. **No automatic retry run.** A retry would fail fast in the most likely
cause (the monitor suspended `CDC_WH`, *Error Handling*) and would add a resume outside the batching
window, which is exactly what profile B measures. The cost: released rows wait for the next gate
query. That is the next Kafka activity, or the starvation guard if traffic continues. Freshness
reports the burst as delayed or as a gap, and window validity reports failed runs.

Residual case, accepted and documented: if the sensor's `UPDATE` commits but the run is never
created (the Dagster daemon dies between the two), no failure event exists. The rows keep a key
with no run, and freshness reports a gap. The Bronze data is still processed by the next run. Freshness of a burst =
`finished_at` of the last Gold model in the run whose `run_key` consumed the **first** `PENDING_RUNS`
row detected after the burst's `committed_at` − `committed_at`. p95 per window.

**Consequences:** freshness is tied to causality, not to timestamps that happen to be later. A burst
with no consuming run within 2 h is reported as a gap. In profile A, where runs are near-continuous, a
burst can map to a `PENDING_RUNS` row that only carries the previous burst's data; the freshness
guardrail applies to profile B only, so A's freshness is reported as indicative.

---

### Decision 8: Spending limits sized to the whole trial

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted — owner decision on the pipeline cap (2026-11-17); limits lowered by owner decision after F15 (2026-11-24, DESIGN 1.5) |
| **Date** | 2026-11-17 |

**Context:** balance USD 400 at creation, USD 395.14 on 2026-11-24; trial ends 2026-12-17 and spans
two calendar months; budgets are monthly (calendar), monitors can be `NEVER` (F9). Credit price read
2026-11-24: **USD 4.65** (F15), so the balance is **~85 credits** (1.0–1.4 assumed USD 3–4, ~100–130).

**Choice (in `dev.tfvars`):**

| Control | Scope | Quota | Frequency | Triggers |
|---------|-------|-------|-----------|----------|
| `cdc_wh_monitor` | `CDC_WH` | **25 credits** (owner decision) | `NEVER` | notify 50/75 · suspend 90 · suspend immediately 100 |
| `account_monitor` | account (all warehouses, incl. `COMPUTE_WH`) | **30 credits** (40 until 1.4) | `NEVER` | notify 50/75/90 · suspend 100 |
| `cdc_budget` (custom) | `CDC_POC` (serverless tasks, Snowpipe Streaming) | **5 credits** / calendar month (10 until 1.4) | monthly | notify + custom action at 100% |

**Rationale:** the measurement is estimated at ~16 credits (Measurement plan); 25 on `CDC_WH` leaves
room for the dry run and one rerun, so it is **not** lowered in 1.5: a lower cap risks suspending
`CDC_WH` inside a window, which voids it. The account monitor keeps 5 credits above it for
`COMPUTE_WH` and `CDC_CI_WH`. With `NEVER`, the warehouse caps hold for the whole trial instead
of resetting mid-way.

**What the budget will see in November (estimate):** Snowpipe Streaming — v2 measured 0.0005 credits
for its whole ingestion; the measurement load is ~10× v2's rows → well under 0.1 credit. Serverless
gate tasks in profile B — ~5 bursts × 10 domains × 12 clusters/day × ~2 s ≈ 1,200 s/day ≈ 0.3 credit/day
× 0.9 → ~0.3 credit/day, ~1 credit for window B plus the idle window. Total ≈ 1–2 credits against a
5-credit monthly limit: the action should not fire during a healthy window B. A lower limit (4) was
rejected: the serverless estimate is not measured yet.

**Worst case, stated with the detection delay:** warehouses 30 (account monitor, `NEVER`) + budget
2 × 5 (two calendar months) + up to ~1.5 credits of overshoot per month before the budget action fires
on `TIER_1H` (Decision 5, F8) ≈ **43 credits** in the pathological case ≈ **USD 200**, ~50% of the
balance at USD 4.65 (F15). Up to 1.4 it was 40 + 2 × 10 + ~3 ≈ 63 credits (≈ USD 293, 74% at the read
price). Acceptable **only because it requires every gate task to time out every minute for hours**;
the task-state check above makes that visible within one cluster.

**Consequences:** the credit price was read before the first apply (F15) and the limits were lowered
in the same PR as the first apply (1.5). If the balance drops or a rerun needs more credits, the
worst case is recomputed against the ~50% rule before raising any limit (PROTOCOL §5). Monitor `NOTIFY_USERS` = the owner.

---

### Decision 9: Terraform identities, and the honest list of REQ-01 exceptions

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Choice:** `scripts/00_terraform_bootstrap.sql`, run once by a human as `ACCOUNTADMIN`, creates:
- `TERRAFORM_SVC` — key-pair auth; granted `SYSADMIN`, `SECURITYADMIN` **and `ACCOUNTADMIN`**
  (creating resource monitors and budgets requires it). Provider aliases (`sysadmin`,
  `securityadmin`, `accountadmin`) make each resource use the least-privileged role that can own it.
  Key only in the `snowflake-dev` GitHub environment and the owner's machine.
- `TERRAFORM_PLAN_SVC` — read-only role for `plan` refreshes (USAGE/MONITOR on the objects Terraform
  manages, no ownership). Key in the `snowflake-plan` environment, which has **no** reviewer, so PRs
  get a plan automatically (Decision 11). Agents use this identity, never `TERRAFORM_SVC`.
  **Unproven:** the plan refresh reads users, grants, both monitors and the budget, and USAGE/MONITOR may
  not be enough for `DESCRIBE USER`, `SHOW GRANTS` or the account monitor. Validated on Day 3; fallback:
  grant the specific read privileges that fail, and if a refresh still needs `ACCOUNTADMIN`, PR plans
  use `-refresh=false` for those resources and the full refresh runs only in the `main` job.
  Monitors are covered by F14: Terraform grants the plan role MONITOR on both monitors.

**Named exception — the `accountadmin` provider alias (owner decision 2026-11-18).** The alias is
used **only** by resources that cannot be applied with a lesser role, each one listed here and in a
comment on the resource:

| Resource | Why ACCOUNTADMIN | Source |
|----------|------------------|--------|
| `snowflake_resource_monitor.cdc_wh`, `.account` | only ACCOUNTADMIN creates monitors | F14 |
| `snowflake_warehouse.cdc` | only ACCOUNTADMIN assigns a warehouse to a monitor; the assignment lives on the warehouse resource | F14 |
| `snowflake_grant_privileges_to_account_role` MONITOR on the two monitors → plan role | the monitors are owned by ACCOUNTADMIN | F14 |
| Grants of `SNOWFLAKE` database roles (`USAGE_VIEWER` etc.) to `CDC_GOVERNANCE_RO` | "Only users with the OWNERSHIP role can grant SNOWFLAKE database roles" (Snowflake docs, *SNOWFLAKE database roles*; confirmed at Build 2026-11-18) | — |
| Grant of `SNOWFLAKE.BUDGET_CREATOR` to `CDC_BUDGET_ADMIN` | same rule; the budget role exists so that `budget.sql` does not run as ACCOUNTADMIN (owner decision 2026-11-18) | [`CREATE BUDGET`](https://docs.snowflake.com/en/sql-reference/classes/budget/commands/create-budget) |

Any other resource on this alias is a review finding. The alias exists **only in apply**: in a PR
plan every alias (`sysadmin`, `securityadmin`, `accountadmin`) authenticates as
`TERRAFORM_PLAN_SVC` with role `TERRAFORM_PLAN_ROLE` (`var.plan_role`, set only by the PR plan job),
so no PR plan ever runs with ACCOUNTADMIN. The `main` job's plan → apply → plan sequence uses
`TERRAFORM_SVC` with the role per alias.

**Exceptions to REQ-01 ("nothing created by hand"), all versioned and listed in the README:**

| # | Step | Run by | Why not Terraform |
|---|------|--------|-------------------|
| 1 | `00_terraform_bootstrap.sql` | human, once | Terraform's own identity |
| 2 | `budget.sql` | CI, as `CDC_BUDGET_ADMIN` (`SNOWFLAKE.BUDGET_CREATOR`, `CREATE SNOWFLAKE.CORE.BUDGET` on CONFIG, `APPLYBUDGET` and USAGE on `CDC_POC`, USAGE on the procedure — all granted by `terraform/platform`), plus `SYSADMIN` only for granting USAGE on the procedure to the `SNOWFLAKE` application; idempotent | no provider resource for custom budgets / custom actions (F13) |
| 3 | `scripts/account_monitor.sql` — `ALTER ACCOUNT SET RESOURCE_MONITOR = <account_monitor>` | CI, after apply, idempotent | checked at Build (F12): the provider can do it only through `snowflake_current_account`, a preview resource that does not detect external changes; kept as SQL by owner decision 2026-11-18. **Future alternative:** move it to `snowflake_current_account` once that resource leaves preview. `verify_governance.sql` checks the assignment (AT-003). |

`seed_config.sql` is not an exception: it inserts data, not objects. CONFIG tables move into
`terraform/platform` as `snowflake_table` resources — their schema is ours and static, unlike Bronze.

---

### Decision 10: Correct ADR-0019's wording instead of carrying it forward

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Choice:** at Ship, a new ADR supersedes ADR-0019's **wording** (not its decision): the gate is
"scheduled tasks gated by `SYSTEM$STREAM_HAS_DATA`", and "a false evaluation costs a nominal charge,
measured in the idle window at X credits / 6 h".

---

### Decision 11: CI that gives every PR a plan without exposing the apply identity

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** a key in a reviewer-protected environment makes "PR shows a plan" non-automatic; no key
means no plan (review finding 4). The repo is public.

**Choice:** `terraform.yml` jobs:
1. **PR from the same repo:** `fmt -check`, `validate`, `plan` for both roots in environment
   `snowflake-plan` (`TERRAFORM_PLAN_SVC`, `TF_VAR_plan_role = TERRAFORM_PLAN_ROLE` so every provider
   alias uses the read-only role — Decision 9), plan posted as a PR comment; `pipeline` plan skipped
   with a notice while Bronze does not exist.
2. **PR from a fork:** `fmt -check` + `validate` only (no secrets are exposed to forks).
3. **Push to `main`:** plan, then apply in environment `snowflake-dev` (`TERRAFORM_SVC`, required
   reviewer), then a second plan that must show no changes (AT-001), then `seed_config.sql`,
   `account_monitor.sql` and `budget.sql`.

4. **`workflow_dispatch` ("apply pipeline"):** the first `pipeline` apply, run by hand from the
   Actions tab once the Bronze tables exist, through the same `snowflake-dev` approval. Later
   pipeline changes go through ordinary PRs.

`ci.yml` keeps its lint/validate jobs and gains `pytest tests/unit`.

**Consequence (recorded at Build, 2026-11-18, owner decision):** GitHub asks for the
`snowflake-dev` approval **before** the apply job starts, and a plan file made by the read-only
identity cannot be applied by `TERRAFORM_SVC`, because the plan carries `var.plan_role`. The
reviewer therefore approves on the strength of the **PR plan**, and the apply job **re-plans**.
`.github/scripts/plan_summary.py` reduces both plans to their changed (address, actions) pairs and
compares them. A divergence, for example another merge in between, is a **warning in the job
summary, never a failure**. When `terraform/pipeline` is skipped in a PR plan because Bronze does
not exist yet, the skip is written to the job summary. Other details settled at Build:
- `verify_governance.sql` runs with the read-only identity's key, also stored in `snowflake-dev`.
- `BUDGET_NOTIFY_EMAIL` is a **secret**, not a variable, because variables are printed unmasked in
  the logs of a public repository.
- The AWS bucket and OIDC roles are a manual step: `docs/runbooks/terraform-state-bootstrap.md`,
  with two roles (plan read-only, apply read-write), trust restricted to this repository and one
  environment each, and bucket versioning mandatory.

---

### Decision 12: Terraform state in S3 with native locking

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Choice:** one S3 bucket (versioning on, encryption on, public access blocked), keys
`sdd-kafka-snowflake-3/platform.tfstate` and `…/pipeline.tfstate`, S3 native lockfile
(`use_lockfile = true`, Terraform ≥ 1.11) — no DynamoDB table. GitHub authenticates to AWS with OIDC,
not static keys.

**Alternatives rejected:** S3 + DynamoDB (DEFINE default) — still works but is the older pattern and
one more resource; local state — unreviewable and unsafe with CI applies.

---

### Decision 13: How the saving is attributed to each change (DEFINE open question 5)

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Choice:** the A/B measures the combined effect; the share of each change is **estimated** from the
metering split and reported as an estimate:
- **Gen1:** arithmetic — (B's billed warehouse seconds ÷ 3600) × (1.35 − 1.0) credits: what B's uptime
  would have cost on Gen2 minus what it cost on Gen1. Assumes the same uptime on both generations,
  which ignores Gen2's faster execution; stated as such.
- **Serverless gate tasks:** A's warehouse resumes caused by gate tasks (resumes with only task queries
  in `QUERY_HISTORY` between resume and suspend) × billed seconds, minus B's
  `SERVERLESS_TASK_HISTORY` credits.
- **Batching:** the remainder: total(A) − total(B) − Gen1 share − tasks share.
- **Known bias:** in profile A the gate tasks overlap the sensor's queries, so resumes with *only* task
  queries will be rare; the tasks' share is underestimated and the batching remainder inflated. The
  README reports the tasks/batching split as one combined "orchestration" share if the bias is large.

**Consequences:** the README states the three shares with "estimated" next to them; only the total is
measured.

---

## Requirement coverage

| REQ | Where it is met | Verified by |
|-----|-----------------|-------------|
| REQ-01 | `terraform/platform`, `terraform/pipeline`; exceptions listed (Decision 9) | AT-001 |
| REQ-02 | `warehouse.tf` (Decision 4), profile B | AT-002 |
| REQ-03 | `monitors.tf` + `account_monitor.sql` + `budget.sql` (Decisions 5, 8, 9) | AT-003 |
| REQ-04 | `terraform/pipeline/gate.tf` (Decision 5) | AT-004 |
| REQ-05 | `gate.py` + `sensors.py` (Decision 6); `assets.py` writes the run key (Decision 7) | AT-005, AT-006 |
| REQ-06 | `tests/load/generate_load.py` | AT-007 |
| REQ-07 | `docs/measurement/` (Measurement plan, Decisions 7, 13) | AT-008 |
| REQ-08 | `.github/workflows/terraform.yml` (Decision 11) | AT-009 |
| REQ-09 | `README.md`, Day 14 | AT-010 |
| REQ-10 | `docs/runbooks/` (5 runbooks) | AT-011 |
| REQ-11 (COULD) | `jobs.py`: select `bronze_<domain>+` (downstream only) from the run's `domains` tag. Built only if Day 6 has slack; **disabled during the A/B** so it cannot blur the comparison. | AT-012 |

---

## Measurement plan (REQ-06, REQ-07)

**Load profile (calibrated in the dry run):** one **cluster every 2 h, starting at :30** (00:30, 02:30 …
UTC) so no cluster crosses a profile switch at 00:00 UTC; each cluster = 5 bursts at offsets
**0, 2, 4, 10 and 12** min; each burst ≈ 200 rows, a fixed seeded mix of inserts and updates across the
10 domains — all ten are PostgreSQL tables (`users_mongo` and `users_mssql` are named after a simulated
origin; see `init.sql` and the Debezium `table.include.list`), so one psycopg2 generator reaches all. The schedule is chosen to exercise what the DEFINE describes (review finding 1):
- Profile A: every burst triggers runs on the hot cycles — the "dbt run every minute during a burst"
  behaviour.
- Profile B: bursts 0–4 settle and run at ~:07; bursts 10–12 settle at ~:15 but the window holds them
  until :17 — **the window is binding** once per cluster.

The generator writes `docs/measurement/runs/<window>/commits.csv` (`burst_id, committed_at_utc, rows`).

**Windows (UTC; Vitória = UTC − 3):**

| Window | Start (UTC) | End (UTC) | Profile | Load |
|--------|-------------|-----------|---------|------|
| Dry run | 2026-11-24 12:00 | 2026-11-24 18:00 | A 3 h, then B 3 h | on |
| A | **2026-11-25 00:00** | **2026-11-27 00:00** | baseline | on |
| B | 2026-11-27 00:00 | 2026-11-29 00:00 | optimized | on |
| Idle | 2026-11-29 00:00 | 2026-11-29 06:00 | optimized | **off** (idle criterion, F3) |
| Read results | ≥ 2026-11-29 10:00 | — | — | `ACCOUNT_USAGE` latency |

In Vitória time, the measurement ends on 2026-11-28 at 21:00 and the idle window on 2026-11-29 at
03:00 — consistent with the `_index` plan (Days 8–11 = Nov 25–28 local).

**Predictions, written before measuring:**

| Metric per cluster | A | B | Hypothesis | Predicted outcome |
|--------------------|---|---|------------|-------------------|
| dbt runs | ~5 | 2 | — | — |
| Warehouse resumes | 1–2 (whether `CDC_WH` suspends between :04 and :10 depends on the dbt run's duration) | 2 | **H2: B ≤ 50% of A** | **Expected to fail** (B/A between 100% and 200%) |
| Billed warehouse minutes | ~18–20 | ~8 | — | — |
| Credits | see below | see below | **H1: B ≤ 75% of A** | Expected to pass (~30–40%) |

Why H2 is kept although it is expected to fail: with this load the saving comes from **shorter uptime
per resume and the cheaper generation**, not from fewer resumes; in v2 the resumes problem was already
solved by the Prometheus gate. The DEFINE says a disproved hypothesis ships with its result — this one
is written down as disproved-in-advance so the result cannot be reinterpreted after the fact.

**Rough cost estimate (written before measuring, to size limits — not a target):**

| | Warehouse uptime per cluster | Clusters/day | Rate | Credits/day | 48 h |
|--|------------------------------|--------------|------|-------------|------|
| A | ~20 min (hot-cycle queries + up to 5 dbt runs + tails) | 12 | 1.35 cr/h | ~5.4 | ~11 |
| B | ~8 min (2 runs + tails) + serverless seconds | 12 | 1.0 cr/h | ~1.6 | ~3.2 |

Plus dry run ~1 credit and idle ~0 → **~16 credits** in total, against the 25-credit cap.

**Validity rules:**
- No manual use of `CDC_WH` during the windows; ad-hoc work goes to `COMPUTE_WH`, excluded from the
  analysis. The CI SQL steps (`seed_config.sql`, `budget.sql`, `verify_governance.sql`) run on
  **`CDC_CI_WH`** (XSMALL, Gen1, 60 s, created by `terraform/platform`, owner decision 2026-11-18), also
  excluded — so the 00:00 UTC switch merge never resumes `CDC_WH`.
- The machine running the stack must stay awake. A gap of more than one cluster in `commits.csv`
  voids that window, which is rerun. **Recommended:** run the stack on a small cloud VM for Days 7–12.
- Every gate task must be `started` at every check in `task_states.csv` (Decision 5); otherwise the
  window is void.
- Results are reported **per cluster** as well as per UTC day, so a window with a missing cluster stays
  comparable.
- The profile switch PR must be applied within 30 min of 00:00 UTC (clusters start at :30).
- The switch time is recorded; minutes in the wrong profile after 00:00 UTC are reported.
- "One resume per run" holds only if the Dagster job starts querying within 60 s of the sensor's
  `SELECT`. The dry run measures the gap; if it is longer, B pays two resumes per run and the
  result is reported as such.

**Queries (`docs/measurement/queries.sql`):**
- Warehouse credits/day — `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY`, `WAREHOUSE_NAME = 'CDC_WH'`.
- Serverless task credits/day — `SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY`, database `CDC_POC`.
- Cross-check — `METERING_DAILY_HISTORY` by `SERVICE_TYPE`. Cloud services are reported **separately**
  and before/after the daily 10% adjustment, because the adjustment changes when warehouse use drops;
  they are not part of the DEFINE's "total cost".
- Resumes/day — `WAREHOUSE_EVENTS_HISTORY`, resume events for `CDC_WH` (exact `EVENT_NAME` confirmed in
  the dry run).
- Freshness — `commits.csv` × `PENDING_RUNS.consumed_run_key` × `PROCESSING_LOG` (Decision 7).
- Attribution — Decision 13.

**After the trial (DEFINE constraint):** on 2026-12-17 the account stops unless a payment method is
added. The README states it, the measured results stay in `docs/measurement/runs/` (CSV + query
output, committed), and `docs/runbooks/after-trial.md` explains how to redeploy on a new account
(`dev.tfvars` + the bootstrap step).

---

## File Manifest

| # | File | Action | Purpose | Dependencies |
|---|------|--------|---------|--------------|
| 1 | `scripts/00_terraform_bootstrap.sql` | Create | Terraform identities (Decision 9) | — |
| 2 | `terraform/platform/{versions,providers,backend}.tf` | Create | Provider pin, role aliases (`plan_role` override), preview features (F11), S3 state | 1 |
| 3 | `terraform/platform/{variables,profiles}.tf`, `terraform/env/dev.tfvars` | Create | Names, `cost_profile`, limits | 2 |
| 4 | `terraform/platform/{database,config_tables,warehouse,monitors,roles,users,grants,procedures}.tf` | Create | REQ-01/02/03; `SP_SUSPEND_GATE_TASKS` | 3 |
| 5 | `scripts/seed_config.sql` (from `bootstrap_config.sql`) | Rename + modify | Seed only; DDL moved to 4 | 4 |
| 6 | `scripts/budget.sql`, `scripts/account_monitor.sql` (+ `CDC_BUDGET_ADMIN` and its grants in `terraform/platform`) | Create | Custom budget + action (exception 2); account-level monitor assignment (exception 3) | 4 |
| 7 | `terraform/pipeline/{versions,providers,backend,variables,procedures,gate}.tf` | Create | Gate procedure, streams, tasks | 4, Bronze tables |
| 8 | `scripts/streams_and_tasks.sql`, `scripts/snowflake_setup.sql`, `scripts/00_account_bootstrap.sql` | Delete | Replaced by 1–7 (git history keeps them) | 7 |
| 9 | `scripts/verify_governance.sql` | Modify | Checks for AT-002/003/004 on the new names | 4, 7 |
| 10 | `dagster/pipeline/gate.py` | Create | Pure decision function (Decision 6) | — |
| 11 | `dagster/pipeline/sensors.py` | Modify | Use `gate.decide`; `UPDATE` first with `consumed_run_key`, then read the marked rows; `pending_run_release_sensor` for failed runs (Decision 7) | 10 |
| 12 | `dagster/pipeline/assets.py` (`run_key` → `PROCESSING_LOG`); `dagster/pipeline/jobs.py` (REQ-11 selection, COULD) | Modify | Write the run's `dagster/run_key` to `PROCESSING_LOG.RUN_KEY` | 11 |
| 13 | `tests/unit/test_gate.py` | Create | Parity, settle, window, starvation, retry, continuous-traffic regression (1.4), migration | 10 |
| 14 | `tests/load/generate_load.py`, `tests/unit/test_generate_load.py` | Create | REQ-06 / AT-007; task-state check after each cluster | — |
| 15 | `docs/measurement/{PROTOCOL.md,queries.sql,ATTRIBUTION.md,RESULTS_TEMPLATE.md}` | Create | REQ-07 | 14 |
| 16 | `.github/workflows/terraform.yml`, `.github/scripts/{plan_summary,bronze_ready}.py`, `docs/runbooks/terraform-state-bootstrap.md` | Create | REQ-08 (Decision 11); state bootstrap runbook (Decision 12) | 2–7 |
| 17 | `.github/workflows/ci.yml` | Modify | Add `pytest tests/unit` | 13 |
| 18 | `.github/workflows/deploy.yml` | Delete | Disabled since v2; replaced by 16 | 16 |
| 19 | `docs/runbooks/{connector-down,monitor-suspended,budget-alert,gate-task-failure,after-trial}.md` | Create | REQ-10 | 4–7 |
| 20 | `Makefile` | Modify | `deploy-*` and `profile-*` prepare PRs; `load`, `dry-run` | 3, 14 |
| 21 | `CLAUDE.md`, `.env.example` | Modify | Names, `BATCH_WINDOW_MINUTES`, plan identity | — |
| 22 | `README.md` | Modify | *What it actually costs*; exceptions; after-trial note (REQ-09) — Day 14 | 15 |

---

## File Ownership & Parallelism

| Path | Access | Notes |
|------|--------|-------|
| `terraform/`, `scripts/*.sql` | Owns | |
| `dagster/pipeline/{sensors,gate,jobs,assets}.py` | Owns | `assets.py` added in 1.4 (item 12); no other feature or fast track touches it |
| `tests/load/`, `tests/unit/test_gate.py`, `tests/unit/test_generate_load.py` | Owns | |
| `docs/measurement/`, the five runbooks above | Owns | |
| `.github/workflows/terraform.yml`, `deploy.yml` | Owns (new / delete) | |
| `.github/workflows/ci.yml` | Shared — serialize | Adds `pytest`; FT-03 also edits it |
| `Makefile`, `README.md`, `CLAUDE.md`, `.env.example`, `docs/adr/` | Shared — serialize | |
| `dbt/**` | Reads | No dbt change in this feature (Decision 3) |

No intersection with SCD2_RESTAURANTS' owned paths. The two features can be built in parallel.

---

## Agent Assignment Rationale

| Role | Files | Why |
|------|-------|-----|
| Builder (Claude Code, Terraform + Snowflake context, `TERRAFORM_PLAN_SVC` only) | 1–9, 16, 18, 20 | IaC; loads F1–F10 and each resource's provider docs before writing it |
| Builder (Cursor, Python) | 10–14, 17 | `gate.py` is the riskiest logic and benefits from tight human review. **Deviation (owner decision 2026-11-18):** 10–13 and 17 built by Claude Code; the human review moves to the PR |
| Author (Christian) | 15, 19, 21, 22 | Protocol, runbooks and README carry the portfolio's voice |
| Validator (fresh session) | VALIDATION | Loads DEFINE + `docs/measurement/` only |

---

## Code Patterns

### Pattern 1: Profiles as a lookup

```hcl
# terraform/platform/profiles.tf
variable "cost_profile" {
  type = string          # no default on purpose: the value lives only in terraform/env/dev.tfvars
  validation {
    condition     = contains(["baseline", "optimized"], var.cost_profile)
    error_message = "cost_profile must be baseline or optimized."
  }
}

locals {
  profiles = {
    baseline  = { generation = "2", task_compute = "warehouse" }
    optimized = { generation = "1", task_compute = "serverless" }
  }
  profile = local.profiles[var.cost_profile]
}
```

### Pattern 2: Warehouse with every cost setting explicit

```hcl
# terraform/platform/warehouse.tf — attribute names checked against provider docs at Build
resource "snowflake_warehouse" "cdc" {
  provider                  = snowflake.accountadmin # named exception, Decision 9 (F14)
  name                      = var.warehouse_name
  warehouse_size            = "XSMALL"
  generation                = local.profile.generation
  enable_query_acceleration = false
  auto_suspend              = 60
  auto_resume               = true
  initially_suspended       = true
  resource_monitor          = snowflake_resource_monitor.cdc_wh.name
  comment                   = "CDC pipeline. Every cost setting is explicit; see DESIGN_COST_GOVERNANCE."
}
```

### Pattern 3: One stream + one task per domain, compute chosen by profile

```hcl
# terraform/pipeline/gate.tf — sketch; the task resource has strict field combinations
locals {
  domains    = toset(["ORDERS", "ORDER_ITEMS", "DRIVERS", "DRIVER_SHIFTS", "RESTAURANTS",
                      "USERS_MONGO", "USERS_MSSQL", "PAYMENT_EVENTS", "RECOMMENDATIONS", "SEARCH_EVENTS"])
  serverless = local.profile.task_compute == "serverless"
}

resource "snowflake_stream_on_table" "bronze" {
  for_each    = local.domains
  database    = var.database_name
  schema      = "BRONZE"
  name        = "${each.key}_STREAM"
  table       = "\"${var.database_name}\".\"BRONZE\".\"${each.key}\""
  append_only = "true"
}

resource "snowflake_task" "gate" {
  for_each  = local.domains
  database  = var.database_name
  schema    = "BRONZE"
  name      = "${each.key}_GATE_TASK"
  started   = true
  warehouse = local.serverless ? null : var.warehouse_name
  user_task_managed_initial_warehouse_size = local.serverless ? "XSMALL" : null
  serverless_task_max_statement_size       = local.serverless ? "XSMALL" : null
  user_task_timeout_ms                     = local.serverless ? var.gate_task_timeout_ms : null
  suspend_task_after_num_failures          = local.serverless ? 3 : null
  schedule  { minutes = 1 }
  when      = "SYSTEM$STREAM_HAS_DATA('${var.database_name}.BRONZE.${each.key}_STREAM')"
  sql_statement = "CALL ${var.database_name}.CONFIG.SP_GATE_DOMAIN('${var.database_name}.BRONZE.${each.key}_STREAM', '${each.key}')"
}
```

### Pattern 4: The sensor's decision as a pure function

```python
# dagster/pipeline/gate.py — sketch
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

LEGACY_HOT_CYCLES = 3   # v2 behaviour, used when the window is 0 (profile A)
QUIET_CYCLES = 3        # profile B: cycles without Kafka activity before a burst counts as settled


@dataclass(frozen=True)
class GateState:
    quiet: int = 0                      # cycles since the last Kafka activity
    last_run_at: datetime | None = None
    pending: bool = False               # a burst was seen and not yet confirmed consumed
    pending_since: datetime | None = None
    retries: int = 0
    initialized: bool = False


def decide(state: GateState, now: datetime, kafka_activity: bool, window: timedelta):
    """Return ("query" | "skip", new_state). Never queries Snowflake while idle."""
    if kafka_activity or not state.initialized:
        since = state.pending_since if state.pending else now
        state = replace(state, quiet=0, pending=True, pending_since=since, retries=0, initialized=True)
    else:
        state = replace(state, quiet=state.quiet + 1)

    if not state.pending:
        return "skip", state
    if window == timedelta(0):                          # profile A: v2 semantics
        return ("query" if state.quiet <= LEGACY_HOT_CYCLES else "skip"), state
    settled = state.quiet >= QUIET_CYCLES * (1 + state.retries)
    waited_enough = now - state.pending_since >= window   # starvation guard for continuous traffic
    window_open = state.last_run_at is None or now - state.last_run_at >= window
    return ("query" if (settled or waited_enough) and window_open else "skip"), state


def after_query(state: GateState, now: datetime, found_rows: bool, window: timedelta) -> GateState:
    if found_rows:
        state = replace(state, last_run_at=now)
    if window == timedelta(0):
        return replace(state, pending=state.quiet < LEGACY_HOT_CYCLES)
    settled = state.quiet >= QUIET_CYCLES
    if found_rows or (settled and state.retries >= 1):
        still_arriving = state.quiet < QUIET_CYCLES   # ran on the starvation guard mid-burst
        return replace(state, pending=still_arriving, pending_since=now if still_arriving else None, retries=0)
    if not settled:                                    # 1.4: empty starvation-guard query
        return replace(state, pending_since=now)       # restart the clock; wait another N
    return replace(state, retries=state.retries + 1)    # one more settled check, then give up
```

---

## Data Flow (profile B, one cluster)

1. `generate_load.py` commits bursts at :00, :02, :04, :10, :12 and logs each.
2. Debezium → Kafka → Snowpipe Streaming commits rows to Bronze (seconds).
3. Within ≤ 1 min, each gate task with data runs **serverless** and writes `PENDING_RUNS`.
4. The sensor sees Kafka activity in Prometheus (0 credits) → `pending`. While a burst is arriving or
   the window is closed, it waits without touching Snowflake.
5. ~:07: settled, window open → one `SELECT` resumes `CDC_WH`; rows marked consumed with the run key;
   one `cdc_pipeline_job` runs `dbt run` + `dbt test`.
6. ~:15: second group settled, but the window holds it until ~:17 → second run.
7. `PROCESSING_LOG` records `finished_at` and the run key; `CDC_WH` suspends 60 s after the last query.

---

## Integration Points

| System | Contract | Change in this feature |
|--------|----------|------------------------|
| Kafka connector | Creates Bronze tables; reads `SNOWFLAKE_DATABASE`, `SNOWFLAKE_ROLE` | None |
| Prometheus | `kafka_server_brokertopicmetrics_messagesin{topic=~"pg[.]public[.].*"}`, 15 s scrape | None |
| dbt | Reads `SNOWFLAKE_*` env vars; `sources.yml` hard-codes `CDC_POC` | None |
| GitHub | Environments `snowflake-plan` (no reviewer) and `snowflake-dev` (reviewer); OIDC to AWS | New |
| AWS S3 | State bucket, native lockfile | New (outside the Snowflake budget) |

---

## Testing Strategy

| Level | What | How | AT |
|-------|------|-----|----|
| Static | fmt, validate, plan | CI on every PR, both roots (Decision 11) | AT-009 |
| Unit | `gate.decide` / `after_query`: legacy parity, settle, window, starvation guard, retry, two consecutive queries, continuous traffic with empty `PENDING_RUNS` (1.4 regression), worst wait ≤ *N* on 2,000 random sequences, cursor migration from v2. Sensor: `UPDATE`-then-read race | `pytest`, table-driven + randomized parity | AT-005, AT-006 |
| Unit | Generator: same seed → identical schedule and row counts | `pytest`, no database | AT-007 |
| Integration | Apply on dev, then `plan` shows no changes | CI apply job | AT-001 |
| Account | `SHOW WAREHOUSES`, `SHOW RESOURCE MONITORS`, `SHOW TASKS`, budget `GET_CUSTOM_ACTIONS` | `verify_governance.sql` | AT-002, 003, 004 |
| Measurement | Protocol queries | Validator session | AT-008, 010 |

---

## Error Handling

| Failure | Behaviour | Runbook |
|---------|-----------|---------|
| Bronze tables missing | `pipeline` plan skipped with a notice; apply blocked | — |
| Gate task fails 3× | Task suspends itself | `gate-task-failure.md` |
| Budget reaches its limit | Gate tasks suspended by the custom action; not auto-resumed | `budget-alert.md` |
| Monitor suspends `CDC_WH` | dbt runs fail fast; `pending_run_release_sensor` returns their rows to pending (Decision 7) | `monitor-suspended.md` |
| Prometheus down | Sensor fails open (v2 behaviour) — a resume, never lost data | `connector-down.md` |
| Stack machine sleeps | Gap in `commits.csv`; window voided and rerun | `PROTOCOL.md` |

---

## Configuration

| Variable | Where | Value | Notes |
|----------|-------|-------|-------|
| `cost_profile` | `terraform/env/dev.tfvars` only | `optimized` (`baseline` during window A; the first apply is already `baseline`, PROTOCOL §9) | No default in code |
| `database_name`, `warehouse_name`, `role_name`, `readonly_role_name` | Terraform | `CDC_POC`, `CDC_WH`, `CDC_ROLE`, `CDC_ROLE_RO` | Decision 3 |
| `cdc_wh_monitor_quota`, `account_monitor_quota`, `budget_monthly_limit` | `dev.tfvars` / `budget.sql` | 25 / 30 / 5 credits | Decision 8; credit price USD 4.65 (F15) |
| `BATCH_WINDOW_MINUTES` | Dagster `.env` | `10` (`0` during window A) | Decision 6 |
| `QUIET_CYCLES` | `gate.py` constant | 3 | Revisited after the dry run |
| `LOAD_SEED`, `LOAD_CLUSTER_MINUTES`, `LOAD_BURST_OFFSETS`, `LOAD_ROWS_PER_BURST` | generator | `42`, `120`, `0,2,4,10,12`, `200` | Calibrated in the dry run |

---

## Security Considerations

- `TERRAFORM_SVC` (apply, incl. `ACCOUNTADMIN`) exists only in the reviewer-protected `snowflake-dev`
  environment and on the owner's machine. Agents and PR plans use `TERRAFORM_PLAN_SVC` (read-only).
- The `accountadmin` provider alias is limited to the resources named in Decision 9 and is never used
  by a PR plan. `CDC_WH` and both monitors are owned by ACCOUNTADMIN.
- Environment secrets are not exposed to fork PRs; the repo is public.
- Service users' public keys are variables; private keys never enter Terraform state.
- The suspend procedure called by the budget is granted to the `SNOWFLAKE` application with the
  minimum privileges the custom-action docs require, and does nothing but `ALTER TASK … SUSPEND`.

---

## Observability

- `SHOW TASKS` + `TASK_HISTORY` for gate runs; `SERVERLESS_TASK_HISTORY` for their cost.
- Budget and monitor notifications to the owner's e-mail; budget `GET_CUSTOM_ACTIONS` in
  `verify_governance.sql`.
- Grafana unchanged (cost dashboard is roadmap).

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Laptop sleeps during ~100 h of windows | **High** | High | Cloud VM for Days 7–12, or sleep disabled; gap detection; rerun |
| Provider lacks budget / account-monitor support | Medium | Low | Exceptions 2–3 (Decision 9) |
| `snowflake_task` field combinations differ from Pattern 3 | Medium | Low | Pattern is a sketch; Build reads the resource docs first |
| Preview resources (`snowflake_table`, `snowflake_procedure_sql`) change behaviour in a minor release (F11) | Low | Medium | Exact version in `.terraform.lock.hcl`; upgrades only by PR with a clean plan |
| Budget refresh delay larger than assumed | Medium | Medium | Timeout bound holds regardless; worst case written in Decision 5 |
| Dagster job start > 60 s after the sensor's query → two resumes per run | Medium | Low | Measured in the dry run; reported as is |
| Estimate biases the reading | Medium | Medium | Estimate written before measuring; Validator is a fresh session |
| `WAREHOUSE_EVENTS_HISTORY` event names differ | Low | Low | Confirmed in the dry run |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-11-17 | Christian (with Claude) | Initial draft |
| 0.2 | 2026-11-17 | Christian (with Claude) | Self-review: Decision 6 rewritten (two resumes per burst); requirement coverage added |
| 0.3 | 2026-11-17 | Christian (with Claude) | Simulation found starvation under continuous traffic; starvation guard added |
| 0.4 | 2026-11-17 | Christian (with Claude) | Applied external review (4 blocking, 8 adjustments, minors): clustered load that exercises the window; idle window; switches at 00:00 UTC via versioned `tfvars`; plan identity + pipeline-plan skip (Decisions 11); causal freshness (Decision 7); attribution method (Decision 13); budget custom action + timeout 10 s with worst case stated (Decision 5); monitors `NEVER` (Decision 8); honest exception list and CONFIG tables in Terraform (Decision 9); S3 native lock (Decision 12); QA deviation recorded (F10); no dbt changes (Decision 3); after-trial plan. Owner decisions: 25-credit cap, automatic action, QA off in both, no `sources.yml` change. |
| 0.5 | 2026-11-17 | Christian (with Claude) | Second review (same reviewer session, not independent): suspend procedure moved to `platform` so `budget.sql` can run before `pipeline`; resume predictions written in advance — H2 expected to fail, and why; task-state check without a warehouse + validity rule; profile A without task limits (as v2); timeout derived from the dry run; read-only plan role marked unproven with fallback; domain scope clarified (all PostgreSQL — reviewer item 5 was a false positive); where the WHEN charge appears flagged for the dry run; November serverless estimate and worst case with detection delay (~84 / ~62 credits); clusters start at :30; first pipeline apply via `workflow_dispatch`; per-cluster normalization; attribution bias; simulation claims reworded until `test_gate.py` exists. |
| 1.0 | 2026-11-18 | Christian (independent review, fresh session) | Independent sign-off (fresh session): READY FOR BUILD, no blocking issues; Build notes recorded below. |
| 1.1 | 2026-11-18 | Christian (with Claude, Build session) | Build found that only ACCOUNTADMIN can assign a warehouse to a monitor (F14): `CDC_WH` moves to the `accountadmin` alias, recorded as a named exception limited to listed resources and never used by a PR plan (Decisions 4, 9, 11; Pattern 2). Account-level monitor stays CI SQL, `scripts/account_monitor.sql` (exception 3, owner decision; `snowflake_current_account` as future alternative — F12). F6 completed with the provider side; F11 (preview resources), F13 (no budget resource) added. Manifest items 2 and 6, Security and Risks updated. No scope change. Reviewed by the owner (diff), not by an independent session. |
| 1.2 | 2026-11-18 | Christian (with Claude, Build session) | Items 5–6 Build, owner decisions: budget refresh `TIER_1H`; no cycle-start action; `budget.sql` runs as a dedicated `CDC_BUDGET_ADMIN` role instead of ACCOUNTADMIN, so the `SNOWFLAKE.BUDGET_CREATOR` grant joins the Decision 9 named list. F8 now from official docs (6.5 h default / 1 h; actual actions once a month, one retry); Decision 5/8 worst case recomputed (~1.5 credits overshoot, ~63 total). SNOWFLAKE database-role grant confirmed. New `CDC_CI_WH` for the CI SQL steps (validity rules; owner decision). Not reviewed by an independent session. |
| 1.3 | 2026-11-18 | Christian (with Claude, Build session) | Items 16–18 Build, owner decisions: Decision 11 consequence recorded (approval before the job, so the apply re-plans and compares with the PR plan, warning only; pipeline-skip notice in the job summary; read-only key in `snowflake-dev` for `verify_governance.sql`; `BUDGET_NOTIFY_EMAIL` as a secret). AWS state bootstrap as a documented manual step with least-privilege OIDC roles and mandatory bucket versioning (Decision 12). Manifest item 16 lists its helpers and runbook. Item 15 stays with the owner; the build agent drafted `queries.sql` only. Not reviewed by an independent session. |
| 1.4 | 2026-11-18 | Christian (with Claude, Build session) | Items 10–13 Build: Pattern 4 / Decision 6 corrected, because an empty starvation-guard query under continuous traffic made the sensor query every minute; it now restarts `pending_since` (simulation kept as a regression test). Decision 7: `assets.py` writes the run key; the sensor runs `UPDATE` first, then reads the rows it marked; a failed run's rows are released back to pending (reprocess, no automatic retry). `assets.py` owned by COST_GOVERNANCE (no other feature touches it); manifest item 12 points to it. Agent Assignment deviation: Claude Code builds 10–13. No scope change. |
| 1.5 | 2026-11-24 | Christian (with Claude, Build session) | Owner decision after reading the credit price (F15: USD 4.65, balance USD 395.14 ≈ 85 credits): Decision 8 limits 25 / **30** / **5** (account monitor 40 → 30, budget 10 → 5, `CDC_WH` cap unchanged); worst case ~63 → ~43 credits (≈ USD 200, ~50%). `budget.sql`, `verify_governance.sql` and `dev.tfvars` follow. The first apply already sets `cost_profile = "baseline"` (PROTOCOL §9). Probe P1 recorded in F14 (P1.3/P1.4 confirm the ACCOUNTADMIN path; P1.1/P1.2 inconclusive because of secondary roles); the Terraform service users get `DEFAULT_SECONDARY_ROLES = ()`. `owner_user_name` is `CHRISTIANDR` on this account. No scope change. Not reviewed by an independent session. |

---

## Build checklist (from the independent review)

Non-blocking items from the 2026-11-18 independent review. Each must be closed by the Day shown and
recorded in the BUILD_REPORT.

| # | Close by | Item |
|---|----------|------|
| B1 | Day 3 | The `main` job applies both roots (`pipeline` only once Bronze exists). Both read `cost_profile` from the same `terraform/env/dev.tfvars`. The `pipeline` root gets its own `profiles.tf` (or a shared module) so `local.profile` exists there. Run `verify_governance.sql` after every profile switch — a switch that applied only one root voids the window. |
| B2 | Day 5 | Check in the official docs whether a task timeout counts toward `suspend_task_after_num_failures`, and recompute the Decision 5/8 worst case accordingly. Confirm that budgets and custom actions are available on a trial account, and the real refresh delay (F8 is secondary-sourced). If budgets are unavailable, state that the ceiling is timeout + failure limit + task-state check. |
| B3 | Day 3 | Source the Gen2 rate of 1.35 credits/h from Snowflake's consumption table, or derive it from window A's metering (credits ÷ billed hours) — and say which. |
| B4 | Day 3 | AT-002 format — already confirmed by the 2026-11-17 probe (see F6); align `verify_governance.sql` with that output. |
| B5 | Before the Day 7 dry run | `PROTOCOL.md` states which window may be rerun, how the monitor quota is raised by PR, and the last date a rerun still fits. `budget.sql` must be idempotent (it runs on every push to `main`). |

---

## Next Step

**Ready for:** the next `/sdd-build COST_GOVERNANCE` items (1–6 built, see the BUILD_REPORT). Build checklist items
B1–B5 are closed during the Build on the Days listed. Probe P1 (Appendix) is run by the owner before
the first apply (Day 3); its read-back is recorded in F14 (2026-11-24, DESIGN 1.5).

---

## Appendix — Probe P1 (F14), run by the owner

Run by a human in Snowsight before the first apply. Agents never run it (Constitution R1). Creates
two throwaway objects that cost nothing while suspended. Record each statement's result in F14 in the
F6 format (statement → error or success → `SHOW` read-back).

```sql
USE ROLE ACCOUNTADMIN;
CREATE RESOURCE MONITOR PROBE_RM_P1 WITH CREDIT_QUOTA = 1 FREQUENCY = NEVER START_TIMESTAMP = IMMEDIATELY;

USE ROLE SYSADMIN;
CREATE WAREHOUSE PROBE_WH_P1 WAREHOUSE_SIZE = XSMALL GENERATION = '1'
    AUTO_SUSPEND = 60 INITIALLY_SUSPENDED = TRUE;
-- P1.1 expected: insufficient privileges
ALTER WAREHOUSE PROBE_WH_P1 SET RESOURCE_MONITOR = PROBE_RM_P1;
-- P1.2 expected: insufficient privileges (the provider may set the monitor at CREATE time)
CREATE WAREHOUSE PROBE_WH_P1B WAREHOUSE_SIZE = XSMALL GENERATION = '1'
    INITIALLY_SUSPENDED = TRUE RESOURCE_MONITOR = PROBE_RM_P1;

USE ROLE ACCOUNTADMIN;
-- P1.3 expected: success
ALTER WAREHOUSE PROBE_WH_P1 SET RESOURCE_MONITOR = PROBE_RM_P1;
-- P1.4 read-back: resource_monitor = PROBE_RM_P1
SHOW WAREHOUSES LIKE 'PROBE_WH_P1%';

-- Cleanup (human): DROP WAREHOUSE IF EXISTS PROBE_WH_P1; DROP WAREHOUSE IF EXISTS PROBE_WH_P1B;
--                  DROP RESOURCE MONITOR IF EXISTS PROBE_RM_P1;
```
