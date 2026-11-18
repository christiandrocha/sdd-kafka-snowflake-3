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
| **Status** | 1.0 — Ready for Build (independent review 2026-11-18) |

---

## Findings that shaped this design (verified 2026-11-17)

| # | Finding | Source | Effect on the design |
|---|---------|--------|----------------------|
| F1 | The Snowflake Terraform provider added the warehouse `generation` field in **v2.7.0**. | provider release notes v2.7.0 | Pin provider `>= 2.7`. |
| F2 | **Resource monitors cover warehouses only**, account-level included. Serverless spend is tracked by **budgets**. | Snowflake docs, *Working with resource monitors* | Serverless gate tasks leave the monitor's brake (Decision 5). |
| F3 | "A nominal charge accrues each time a task evaluates its `WHEN` condition and does not run." | Snowflake docs, `ALTER TASK` | v2's "a false `WHEN` costs nothing" is approximate; measured in the idle window (Decision 10). **Which view records it** (`SERVERLESS_TASK_HISTORY` or cloud services in `METERING_HISTORY`) is not documented: the dry run checks both, so the idle criterion cannot read zero by construction. |
| F4 | Serverless compute billed per second, rounded up; serverless tasks at a 0.9 multiplier per third-party readings of the consumption table; no minimum stated on the tasks page. | Snowflake *Understanding compute cost*; select.dev, getorchestra | A-003 partially validated; the A/B settles it. |
| F5 | Bronze tables are created by the Kafka connector (`enable.schematization=true`). Streams need existing tables. | v2 connector config, v2 `deploy.yml` order | Two Terraform roots (Decision 1). |
| F6 | `RESOURCE_CONSTRAINT = 'STANDARD_GEN_1'` is rejected on this account; `GENERATION = '1'` works. New warehouses default to Gen2 with query acceleration on. Read-back: after `CREATE WAREHOUSE … GENERATION = '1'`, `SHOW WAREHOUSES` returned `resource_constraint = STANDARD_GEN_1` and `generation = 1` (the constraint is rejected on write but reported on read). | Live probe on `GWHUBCF-QQ53235`, 2026-11-17 | DEFINE 1.1 REQ-02; AT-002 output format (Build checklist B4). |
| F7 | Budgets can call a **stored procedure** when actual or projected spend reaches a threshold (custom actions), and another one when the cycle restarts. A custom budget that contains a database monitors the serverless tasks in it. | Snowflake docs, *Custom actions for budgets*; release notes 2025-12-10 and 2026-02-24; *Budgets* | An automatic action that suspends the gate tasks is possible (Decision 5). |
| F8 | Budget spend data refreshes with a delay: up to ~8 h on the standard tier, ~1 h on a faster tier. | third-party guide (Medium); to confirm in docs at Build | The budget action is a backstop, not a fast brake. |
| F9 | A resource monitor with `FREQUENCY = NEVER` never resets its used credits. | Snowflake docs, `CREATE RESOURCE MONITOR` | Monitors sized for the whole trial, not per calendar month (Decision 8). |
| F10 | v2's `CDC_WH` had query acceleration **on** (scale factor 2), read on 2026-08-11; it never engaged in 30 days. `00_account_bootstrap.sql` says `FALSE`, but `CREATE … IF NOT EXISTS` never altered the existing warehouse. | v2 README *Cost governance*, `scripts/snowflake_setup.sql` | Profile A deviates from v2 on this one setting, by owner decision (see Cost profiles). |

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
          ▼  scripts/seed_config.sql (CI step): TABLE_METADATA seed — data, not objects
          ▼  scripts/budget.sql      (CI step): custom budget on CDC_POC + custom action (exception)
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
| `scripts/budget.sql` | Custom budget on `CDC_POC`, limit, refresh tier, custom action + cycle-start action | SQL, CI step (exception) |
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
`resource_monitor = <cdc_wh monitor>`. Provider `>= 2.7.0, < 3.0.0`, exact version in
`.terraform.lock.hcl`.

**Consequences:** the provider reads generation back through `resource_constraint` for standard
warehouses; the Build confirms a clean second `plan` (AT-001). Drift, if any, is documented — never
hidden with `ignore_changes`.

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
- a cycle-start action that does **not** resume them automatically — resuming is a human step in the
  `budget-alert` runbook, after the cause is understood;
- the faster refresh tier if available on the trial (F8; cost of the tier to be checked at Build).

**The numbers, stated plainly:**
- Healthy case: ~10 runs/burst × < 1 s — negligible next to warehouse uptime.
- Pathological worst case (every task times out every minute): 10 × 10 s per minute = 100 s/min of
  XSMALL ≈ 1.67 compute-hours/hour × 0.9 ≈ **1.5 credits/hour**.
- Detection delay of the budget action (F8): up to ~8 h on the standard tier → worst-case exposure
  ≈ **12 credits** before the action fires (≈ 1.5 credits on the 1-hour tier).

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
marks rows consumed; the job writes the same key to `PROCESSING_LOG`. Freshness of a burst =
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
| **Status** | Accepted — owner decision on the pipeline cap (2026-11-17) |
| **Date** | 2026-11-17 |

**Context:** balance USD 400 (confirmed), trial ends 2026-12-17 and spans two calendar months; budgets
are monthly (calendar), monitors can be `NEVER` (F9). Credit price for this edition/region still to be
read from *Admin → Billing*; at USD 3–4/credit the balance is ~100–130 credits.

**Choice (in `dev.tfvars`):**

| Control | Scope | Quota | Frequency | Triggers |
|---------|-------|-------|-----------|----------|
| `cdc_wh_monitor` | `CDC_WH` | **25 credits** (owner decision) | `NEVER` | notify 50/75 · suspend 90 · suspend immediately 100 |
| `account_monitor` | account (all warehouses, incl. `COMPUTE_WH`) | 40 credits | `NEVER` | notify 50/75/90 · suspend 100 |
| `cdc_budget` (custom) | `CDC_POC` (serverless tasks, Snowpipe Streaming) | 10 credits / calendar month | monthly | notify + custom action at 100% |

**Rationale:** the measurement is estimated at ~16 credits (Measurement plan); 25 on `CDC_WH` leaves
room for the dry run and one rerun. With `NEVER`, the warehouse caps hold for the whole trial instead
of resetting mid-way.

**What the budget will see in November (estimate):** Snowpipe Streaming — v2 measured 0.0005 credits
for its whole ingestion; the measurement load is ~10× v2's rows → well under 0.1 credit. Serverless
gate tasks in profile B — ~5 bursts × 10 domains × 12 clusters/day × ~2 s ≈ 1,200 s/day ≈ 0.3 credit/day
× 0.9 → ~0.3 credit/day, ~1 credit for window B plus the idle window. Total ≈ 1–2 credits against a
10-credit monthly limit: the action should not fire during a healthy window B.

**Worst case, stated with the detection delay:** warehouses 40 (account monitor, `NEVER`) + budget
2 × 10 (two calendar months) + up to ~12 credits of overshoot per month before the budget action fires
(Decision 5, F8) ≈ **84 credits** in the pathological case, ≈ **62** if the 1-hour refresh tier is
available. At USD 3–4/credit that is ~65–80% of the trial in the worst case — **acceptable only because
it requires every gate task to time out every minute for hours**; the task-state check above makes
that visible within one cluster.

**Consequences:** **the credit price must be read before the first apply**; if 60 credits exceed
~50% of the balance, the defaults are lowered in the same PR. Monitor `NOTIFY_USERS` = the owner.

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

**Exceptions to REQ-01 ("nothing created by hand"), all versioned and listed in the README:**

| # | Step | Run by | Why not Terraform |
|---|------|--------|-------------------|
| 1 | `00_terraform_bootstrap.sql` | human, once | Terraform's own identity |
| 2 | `budget.sql` | CI | no provider resource for custom budgets / custom actions (to re-check at Build) |
| 3 | `ALTER ACCOUNT SET RESOURCE_MONITOR` | CI, only if the provider cannot assign an account-level monitor | to be checked at Build |

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
   `snowflake-plan` (`TERRAFORM_PLAN_SVC`), plan posted as a PR comment; `pipeline` plan skipped with
   a notice while Bronze does not exist.
2. **PR from a fork:** `fmt -check` + `validate` only (no secrets are exposed to forks).
3. **Push to `main`:** plan, then apply in environment `snowflake-dev` (`TERRAFORM_SVC`, required
   reviewer), then a second plan that must show no changes (AT-001), then `seed_config.sql` and
   `budget.sql`.

4. **`workflow_dispatch` ("apply pipeline"):** the first `pipeline` apply, run by hand from the
   Actions tab once the Bronze tables exist, through the same `snowflake-dev` approval. Later
   pipeline changes go through ordinary PRs.

`ci.yml` keeps its lint/validate jobs and gains `pytest tests/unit`.

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
| REQ-03 | `monitors.tf` + `budget.sql` (Decisions 5, 8) | AT-003 |
| REQ-04 | `terraform/pipeline/gate.tf` (Decision 5) | AT-004 |
| REQ-05 | `gate.py` + `sensors.py` (Decision 6) | AT-005, AT-006 |
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
  analysis.
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
| 2 | `terraform/platform/{versions,providers,backend}.tf` | Create | Provider pin, role aliases, S3 state | 1 |
| 3 | `terraform/platform/{variables,profiles}.tf`, `terraform/env/dev.tfvars` | Create | Names, `cost_profile`, limits | 2 |
| 4 | `terraform/platform/{database,config_tables,warehouse,monitors,roles,users,grants,procedures}.tf` | Create | REQ-01/02/03; `SP_SUSPEND_GATE_TASKS` | 3 |
| 5 | `scripts/seed_config.sql` (from `bootstrap_config.sql`) | Rename + modify | Seed only; DDL moved to 4 | 4 |
| 6 | `scripts/budget.sql` | Create | Custom budget + actions (exception 2) | 4 |
| 7 | `terraform/pipeline/{versions,providers,backend,variables,procedures,gate}.tf` | Create | Gate procedure, streams, tasks | 4, Bronze tables |
| 8 | `scripts/streams_and_tasks.sql`, `scripts/snowflake_setup.sql`, `scripts/00_account_bootstrap.sql` | Delete | Replaced by 1–7 (git history keeps them) | 7 |
| 9 | `scripts/verify_governance.sql` | Modify | Checks for AT-002/003/004 on the new names | 4, 7 |
| 10 | `dagster/pipeline/gate.py` | Create | Pure decision function (Decision 6) | — |
| 11 | `dagster/pipeline/sensors.py` | Modify | Use `gate.decide`; write `consumed_run_key` | 10 |
| 12 | `dagster/pipeline/jobs.py` | Modify | Pass `run_key` to `PROCESSING_LOG`; REQ-11 selection (COULD) | 11 |
| 13 | `tests/unit/test_gate.py` | Create | Parity, settle, window, starvation, retry, migration | 10 |
| 14 | `tests/load/generate_load.py`, `tests/unit/test_generate_load.py` | Create | REQ-06 / AT-007; task-state check after each cluster | — |
| 15 | `docs/measurement/{PROTOCOL.md,queries.sql,ATTRIBUTION.md,RESULTS_TEMPLATE.md}` | Create | REQ-07 | 14 |
| 16 | `.github/workflows/terraform.yml` | Create | REQ-08 (Decision 11) | 2–7 |
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
| `dagster/pipeline/{sensors,gate,jobs}.py` | Owns | |
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
| Builder (Cursor, Python) | 10–14, 17 | `gate.py` is the riskiest logic and benefits from tight human review |
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
  provider                  = snowflake.sysadmin
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
    if found_rows or state.retries >= 1:
        still_arriving = state.quiet < QUIET_CYCLES   # ran on the starvation guard mid-burst
        return replace(state, pending=still_arriving, pending_since=now if still_arriving else None, retries=0)
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
| Unit | `gate.decide` / `after_query`: legacy parity, settle, window, starvation guard, retry, two consecutive queries, cursor migration | `pytest`, table-driven + randomized parity | AT-005, AT-006 |
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
| Monitor suspends `CDC_WH` | dbt runs fail fast; sensor keeps rows pending | `monitor-suspended.md` |
| Prometheus down | Sensor fails open (v2 behaviour) — a resume, never lost data | `connector-down.md` |
| Stack machine sleeps | Gap in `commits.csv`; window voided and rerun | `PROTOCOL.md` |

---

## Configuration

| Variable | Where | Value | Notes |
|----------|-------|-------|-------|
| `cost_profile` | `terraform/env/dev.tfvars` only | `optimized` (`baseline` during window A) | No default in code |
| `database_name`, `warehouse_name`, `role_name`, `readonly_role_name` | Terraform | `CDC_POC`, `CDC_WH`, `CDC_ROLE`, `CDC_ROLE_RO` | Decision 3 |
| `cdc_wh_monitor_quota`, `account_monitor_quota`, `budget_monthly_limit` | `dev.tfvars` / `budget.sql` | 25 / 40 / 10 credits | Decision 8; confirm credit price first |
| `BATCH_WINDOW_MINUTES` | Dagster `.env` | `10` (`0` during window A) | Decision 6 |
| `QUIET_CYCLES` | `gate.py` constant | 3 | Revisited after the dry run |
| `LOAD_SEED`, `LOAD_CLUSTER_MINUTES`, `LOAD_BURST_OFFSETS`, `LOAD_ROWS_PER_BURST` | generator | `42`, `120`, `0,2,4,10,12`, `200` | Calibrated in the dry run |

---

## Security Considerations

- `TERRAFORM_SVC` (apply, incl. `ACCOUNTADMIN`) exists only in the reviewer-protected `snowflake-dev`
  environment and on the owner's machine. Agents and PR plans use `TERRAFORM_PLAN_SVC` (read-only).
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

**Ready for:** `/sdd-build COST_GOVERNANCE items 1-4` (File Manifest items 1-4: Terraform
identities and the platform root). Build checklist items B1–B5 are closed during the Build on
the Days listed.
