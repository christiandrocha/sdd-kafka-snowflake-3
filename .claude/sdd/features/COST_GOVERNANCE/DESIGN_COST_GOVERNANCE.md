# DESIGN: Cost Governance 2.0 (COST_GOVERNANCE)

> Technical design for cutting billed warehouse uptime, delivering it as Terraform, and measuring
> the effect with a controlled A/B on the trial account.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COST_GOVERNANCE |
| **Date** | 2026-11-17 |
| **Author** | Christian (with Claude) |
| **DEFINE** | [DEFINE_COST_GOVERNANCE.md](./DEFINE_COST_GOVERNANCE.md) — v1.2, approved |
| **Status** | Draft — awaiting independent design review |

---

## Findings that shaped this design (verified 2026-11-17)

| # | Finding | Source | Effect on the design |
|---|---------|--------|----------------------|
| F1 | The Snowflake Terraform provider added the warehouse `generation` field in **v2.7.0**. | provider release notes v2.7.0 | A-002 resolved for the warehouse: pin provider `>= 2.7`. |
| F2 | **Resource monitors cover warehouses only.** Serverless features (incl. serverless tasks) are not tracked or suspended by any monitor, account-level included; Snowflake points to **budgets** for those. | Snowflake docs, *Working with resource monitors* | Moving the gate tasks to serverless moves their spend **outside the brake**. Needs a budget and hard caps on the tasks themselves (Decision 5). |
| F3 | "A nominal charge accrues each time a task evaluates its `WHEN` condition and does not run." | Snowflake docs, `ALTER TASK` | v2's claim "a false `WHEN` costs nothing" (ADR-0019, README) is **approximately** true, not exactly. The idle criterion stays, but the ADR wording must be corrected. |
| F4 | Serverless task compute is billed per second (rounded up) at a 0.9 multiplier per third-party reading of the consumption table; the official tasks page does not state a minimum billing duration. | Snowflake *Understanding compute cost*; select.dev / getorchestra (multiplier) | A-003 **partially** validated. The 0.9 multiplier is unverified on the official table; the A/B measurement settles it empirically. |
| F5 | Bronze tables are **created by the Kafka connector** (`enable.schematization=true`), not by DDL. Streams can only be created on tables that exist. | v2 `connectors/snowflake_sink.json`, v2 `deploy.yml` order | Streams and tasks cannot be applied in the same step as the database (Decision 1). |
| F6 | `CREATE WAREHOUSE … RESOURCE_CONSTRAINT = 'STANDARD_GEN_1'` is rejected on this account; `GENERATION = '1'` works. New warehouses default to Gen2 with query acceleration on. | Live probe on `GWHUBCF-QQ53235` | Already reflected in DEFINE 1.1 REQ-02. |

---

## Architecture Overview

```text
 GitHub Actions                                   Snowflake trial account GWHUBCF-QQ53235 (AWS sa-east-1)
 ─────────────                                   ─────────────────────────────────────────────────────────
 PR:   fmt · validate · plan (both roots)
 main: apply ── protected env, reviewer ──┐
                                          ▼
   terraform/platform  ──────────────► DB CDC_POC (BRONZE/SILVER/GOLD/CONFIG) · WH CDC_WH (GENERATION, QA off)
     (account-level, once)               roles CDC_ROLE / CDC_ROLE_RO · service users · grants
                                         monitors: wh-level (CDC_WH) + account-level · budget (serverless)
          │
          ▼  scripts/bootstrap_config.sql (versioned SQL, CI step): CONFIG tables + TABLE_METADATA seed
          │
   [ stack up · connectors registered · first CDC rows land → Bronze tables now exist ]   ← F5
          │
          ▼
   terraform/pipeline  ──────────────► CONFIG.SP_GATE_DOMAIN · 10 × stream (append-only) · 10 × gate task
     (needs Bronze tables)               task_compute = "warehouse" (profile A) | "serverless" (profile B)

 Local stack (Docker Compose)
 ────────────────────────────
 tests/load/generate_load.py ──► Postgres ──► Debezium ──► Kafka ──► Snowpipe Streaming ──► Bronze
   (seeded bursts, commit log)                    │                                            │ stream
                                                  └──► Prometheus ◄── sensor gate (0 credits)  │
                                                                         │                     ▼
                                       Dagster bronze_new_data_sensor ◄── CONFIG.PENDING_RUNS ◄─ gate task
                                         + batching window N (profile B)
                                                   │
                                                   ▼
                                       cdc_pipeline_job: dbt run + test ──► Silver/Gold ──► PROCESSING_LOG
```

**Cost profiles.** One codebase, two profiles selected by variables — the A/B is a configuration
switch on the same objects, not two deployments (Decision 2):

| Setting | Profile A — `baseline` (v2 behaviour) | Profile B — `optimized` (v3) |
|---------|---------------------------------------|------------------------------|
| `CDC_WH` generation | `'2'` | `'1'` |
| Query acceleration | off (v2 already had it off on `CDC_WH`) | off |
| Gate tasks | on `CDC_WH` | serverless, `XSMALL` cap |
| Dagster batching window *N* | 0 (none) | 10 min |
| Auto-suspend | 60 s | 60 s |

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `terraform/platform` | Account-level objects: database, schemas, warehouse, roles, users, grants, monitors, budget | Terraform ≥ 1.11, `snowflakedb/snowflake` ≥ 2.7, < 3.0 |
| `terraform/pipeline` | Gate procedure, streams and tasks over connector-created Bronze tables | Same provider; `for_each` over the 10 Tier-1 domains |
| `terraform/modules/…` | None in v3 — two flat roots are easier to review than a module hierarchy at this size | — |
| `scripts/00_terraform_bootstrap.sql` | One-time, documented manual step: the Terraform service user and its roles (chicken-and-egg) | SQL, run once as `ACCOUNTADMIN` |
| `scripts/bootstrap_config.sql` | CONFIG tables (`TABLE_METADATA`, `METADATA_HISTORY`, `PROCESSING_LOG`, `PENDING_RUNS`, `STREAM_CONSUMPTION_LOG`) and seed | Versioned SQL run by CI after `platform` apply |
| `scripts/budget.sql` | Activate the account budget and set its limit (fallback if the provider has no budget resource) | Versioned SQL run by CI |
| `dagster/pipeline/sensors.py` | Add the batching window to `bronze_new_data_sensor` without reintroducing stranding | Python, Dagster |
| `dagster/pipeline/gate.py` | Pure decision function for the sensor, unit-testable without Dagster or Snowflake | Python |
| `tests/load/generate_load.py` | Seeded, fixed-cadence load generator; writes a commit log | Python, psycopg2 |
| `docs/measurement/` | Protocol, queries, results template | Markdown + SQL |
| `docs/runbooks/` | Connector down; monitor suspended the warehouse; budget alert fired | Markdown |
| `.github/workflows/terraform.yml` | Plan on PR, apply on `main` through a protected environment | GitHub Actions |

---

## Key Decisions

### Decision 1: Two Terraform roots, with the Bronze landing in between

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** Streams must be created on existing tables (F5), and Bronze tables are created by the
connector on first write. A single root cannot create the database and the streams on its tables in
one apply.

**Choice:** `terraform/platform` (everything that does not depend on data) and `terraform/pipeline`
(procedure, streams, tasks). Order: platform → `bootstrap_config.sql` → stack + connectors → first
rows land → pipeline. `pipeline` reads the Bronze tables with a data source and fails `plan` with a
clear message if they are missing.

**Rationale:** Keeps Terraform as the owner of every cost-relevant object (REQ-01) while respecting
the connector's ownership of the Bronze schema.

**Alternatives rejected:**
1. Terraform creates the Bronze tables — rejected: schematization evolves their columns, so Terraform
   would report drift on every new source column, and fixing it means fighting the connector.
2. Keep streams/tasks as hand-run SQL (v2) — rejected: they hold the A/B switch; they must be code.
3. One root with `depends_on` a null resource that waits for data — rejected: hides an operational
   step inside `apply`, and a first deploy would hang.

**Consequences:** a first deploy is two applies with a manual-looking gap; the runbook and the
`make deploy-*` targets make the order explicit. Re-applies after that are ordinary.

---

### Decision 2: One codebase, two cost profiles

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** The A/B must compare v2 behaviour against v3 under identical load, on an account where
v2 was never deployed.

**Choice:** a `cost_profile` variable (`baseline` | `optimized`) in both roots, mapped to the table
above, plus `BATCH_WINDOW_MINUTES` for Dagster. Switching profile = `terraform apply` of both roots
+ Dagster restart, at a recorded UTC timestamp.

**Rationale:** the only differences between A and B are the ones under test. No second copy of the
pipeline, no second database, nothing that could leak cost from one window into the other.

**Alternatives rejected:**
1. Two parallel stacks (`CDC_POC_A`, `CDC_POC_B`) — rejected: doubles load and ingestion, and the two
   would share account-level metering, making attribution harder.
2. Measure B only and compare with v2's historical figures — rejected: different account, different
   load, not a controlled comparison.

**Consequences:** the profile switch is part of the measurement protocol and must be timestamped.
`baseline` stays in the code after v3 ships, as executable documentation of what was measured.

---

### Decision 3: Keep the v2 object names as variable defaults; drop the `_V3` suffix

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** The `_V3` suffix existed so v3 could coexist with v2 on one account. v2 is not on this
account (DEFINE 1.1), and Decision 2 removes the need for parallel copies.

**Choice:** names are Terraform variables with v2's values as defaults (`CDC_POC`, `CDC_WH`,
`CDC_ROLE`, `CDC_ROLE_RO`). The hard-coded `database: CDC_POC` in `dbt/models/config/sources.yml`
becomes `{{ env_var('SNOWFLAKE_DATABASE', 'CDC_POC') }}`.

**Rationale:** zero churn in dbt, Dagster and connector configuration (all already read env vars),
and a client deployment changes names in one `tfvars` file.

**Consequences:** AT-002 in the DEFINE refers to `CDC_WH_V3`; it reads as `var.warehouse_name`
(default `CDC_WH`). Recorded as DEFINE revision 1.3 (naming only, no scope change). `CLAUDE.md`
updated in the same PR.

---

### Decision 4: Gen1 through `generation = "1"`, provider pinned ≥ 2.7

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** REQ-02, F1, F6.

**Choice:** `snowflake_warehouse.generation = local.profile.generation`, `enable_query_acceleration
= false`, `warehouse_size = "XSMALL"`, `auto_suspend = 60`, `auto_resume = true`,
`initially_suspended = true`, `resource_monitor = snowflake_resource_monitor.cdc_wh.name`. Provider
constraint `>= 2.7.0, < 3.0.0`, exact version locked in `.terraform.lock.hcl`.

**Rationale:** the account rejects the older `RESOURCE_CONSTRAINT` path for Gen1, and the provider
exposes `generation` since 2.7.

**Consequences:** the provider reads generation back through `resource_constraint` for standard
warehouses (provider docs note); the Build must confirm `plan` is clean after `apply` (AT-001). If it
is not, the drift is documented and `lifecycle.ignore_changes` is **not** used to hide it.

---

### Decision 5: Serverless gate tasks — with the brake moved, not removed

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** REQ-04 moves the ten gate tasks off `CDC_WH`. F2: their spend is then invisible to every
resource monitor. A misbehaving serverless task could spend credits with nothing able to suspend it.

**Choice:** in profile B, each task is serverless with:
- `user_task_managed_initial_warehouse_size = "XSMALL"` and `SERVERLESS_TASK_MAX_STATEMENT_SIZE = 'XSMALL'` — the compute size can never grow;
- `user_task_timeout_ms = 60000` — a run that hangs is killed after a minute;
- `suspend_task_after_num_failures = 3`;
- `schedule = "1 MINUTE"` + `when = SYSTEM$STREAM_HAS_DATA(…)` — same semantics as v2.

Plus an **account budget** with a monthly spending limit and notification (budgets notify; they do
not suspend). Resource monitors stay for the warehouses: one on `CDC_WH`, one at account level.

**Rationale:** the per-task caps bound the worst case mechanically (10 tasks × XSMALL × 60 s per
minute); the budget makes the residual visible. Together they replace what the warehouse monitor
used to do for these tasks.

**Alternatives rejected:**
1. Keep tasks on the warehouse — rejected: that is the cost being measured (one full minute billed
   per firing for two sub-second `INSERT`s).
2. True triggered tasks (no `SCHEDULE`) — deferred, out of scope by DEFINE; serverless triggered
   tasks additionally require a target completion interval. Candidate for a later ADR.

**Consequences:** the "credit brake" story in the README changes from "a monitor caps everything" to
"monitors cap warehouses; tasks are capped by size, timeout and failure count; a budget alerts on
the rest." That is more honest than v2's, which never covered Snowpipe Streaming either.

---

### Decision 6: Batching = "wait for the burst to settle, then run once", with an explicit pending flag

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** REQ-05 asks for a minimum interval *N* between runs without losing pending rows. Two
traps in the obvious implementation ("skip if the last run was < *N* ago"):
1. **Stranding.** The v2 sensor only touches Snowflake for `HOT_CYCLES_AFTER_ACTIVITY = 3` cycles
   after the last Kafka activity. With *N* = 10 min those cycles expire inside the window, and rows
   written to `PENDING_RUNS` meanwhile wait for the next burst — possibly forever in a quiet period.
   Same class of bug as the global watermark (ADR-0024).
2. **Two runs per burst.** Running on the first sign of a burst and again after the window (to catch
   domains whose gate task fired later) pays two resumes per burst — the cost the window exists to cut.

**Choice:** move the decision into a pure function in `dagster/pipeline/gate.py`, with state
`{quiet, last_run_at, pending, initialized}` where `quiet` counts cycles since the last Kafka activity.
- **Profile A (`N = 0`, legacy):** reproduce v2 exactly — query on the activity cycle and the next 3.
- **Profile B (`N > 0`, batched):** query Snowflake only when `pending` is set, `now − last_run_at ≥ N`,
  and **either** the burst has **settled** (`quiet ≥ QUIET_CYCLES`, default 3 — longer than the ≤ 1 min
  gate-task lag) **or** it has been pending for ≥ *N* (**starvation guard**: under continuous traffic a
  burst never settles, so it is processed every *N* minutes instead of never). One query, one run,
  then `pending = False` — unless the run happened mid-burst, in which case `pending` stays set. If the settled query finds no
  rows (a gate task lagging unusually), `pending` stays set for one more check after another
  `QUIET_CYCLES`, then clears.

**Rationale:** one resume per burst in the common case; no Snowflake query while a burst is still
arriving or inside the window; `pending` guarantees a check for every burst seen. A pure function is
exhaustively testable with pytest (AT-005, AT-006) without Dagster, Kafka or Snowflake.

**Found in review (2026-11-17, by simulating the sketch):** the first version of this logic ran twice
per burst, and the second starved under continuous traffic (bursts every 3 min were processed only
when traffic stopped). Both scenarios are now unit-test cases.

**Consequences:** profile B adds up to `QUIET_CYCLES` minutes of latency per burst on top of *N* —
inside the DEFINE's freshness guardrail (p95 ≤ *N* + 5 min). Cursor format changes; an old-format
cursor falls into `initialized = False` and self-heals as in v2. A residual risk remains: a gate task
that fires more than 2 × `QUIET_CYCLES` minutes after the burst leaves its row for the next burst
(delayed, never lost). AT-006 measures whether this happens.

---

### Decision 7: Freshness measured from the generator's commit log and `PROCESSING_LOG`

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** the freshness guardrail needs "source commit → Gold" per burst. Gold rows carry no
source timestamp.

**Choice:** the generator logs `(burst_id, committed_at_utc)` after each burst commit. Freshness of a
burst = first `PROCESSING_LOG.finished_at` of a Gold model **after** `committed_at` − `committed_at`.
p95 over all bursts in the window.

**Rationale:** uses data that already exists (v2's `PROCESSING_LOG`) and a clock the protocol
controls. No new instrumentation in the pipeline.

**Consequences:** bounded above by the burst cadence — a burst that is never processed shows as a
gap, not as a large delay; the protocol checks for gaps explicitly.

---

### Decision 8: Spending limits sized to the trial

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted — values provisional until the credit price is read from *Admin → Billing* |
| **Date** | 2026-11-17 |

**Context:** trial balance USD 400, ends 2026-12-17. Credit price for this edition/region not yet
read; at USD 3–4/credit the balance is roughly 100–130 credits.

**Choice (variables, defaults):**

| Control | Scope | Quota | Frequency | Triggers |
|---------|-------|-------|-----------|----------|
| `cdc_wh_monitor` | `CDC_WH` | 25 credits | `MONTHLY` | notify 50/75 · suspend 90 · suspend immediately 100 |
| `account_monitor` | account (all warehouses, incl. `COMPUTE_WH`) | 50 credits | `MONTHLY` | notify 50/75/90 · suspend 100 |
| account budget | all spend incl. serverless | 60 credits / month | monthly | notify (budgets cannot suspend) |

**Rationale:** the measurement is estimated at ~12–15 credits (see Measurement plan); 25 on the
pipeline warehouse leaves room for the dry run and reruns, and the account caps keep at least half
the trial in reserve even if everything else goes wrong.

**Consequences:** if the credit price makes 50 credits exceed ~50% of the balance, the defaults are
lowered before the first apply. Decision recorded so the numbers are reviewable, not magic.

---

### Decision 9: The one manual step — bootstrapping Terraform's own identity

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** Terraform needs a Snowflake identity before it can create anything.

**Choice:** `scripts/00_terraform_bootstrap.sql`, run once by a human as `ACCOUNTADMIN`: creates
`TERRAFORM_SVC` (TYPE = SERVICE, key-pair auth) and grants it `SYSADMIN`, `SECURITYADMIN` and the
account privileges needed for monitors and budgets. The provider uses aliases per role
(`sysadmin`, `securityadmin`, `accountadmin`) so each resource is created by the least-privileged
role that can own it.

**Rationale:** every IaC setup has this step; documenting it is better than pretending it away.

**Consequences:** REQ-01 ("nothing created by hand") has one documented exception, listed in the
README. The private key lives only in the GitHub environment secret and the owner's machine.

---

### Decision 10: Correct ADR-0019 instead of carrying its wording forward

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted |
| **Date** | 2026-11-17 |

**Context:** ADR-0019 calls the gate "Streams and **Triggered** Tasks" and states a false `WHEN` costs
nothing. The tasks are scheduled tasks with a `WHEN` clause, and F3 says a nominal charge accrues
per false evaluation.

**Choice:** at Ship, a new ADR supersedes ADR-0019's wording (not its decision): "scheduled tasks
gated by `SYSTEM$STREAM_HAS_DATA`; a false evaluation costs a nominal charge, measured here as …".

**Consequences:** the v3 idle-cost criterion (DEFINE: < 0.01 serverless credits over 6 h) becomes the
measured value of that nominal charge.

---

## Requirement coverage

| REQ | Where it is met | Verified by |
|-----|-----------------|-------------|
| REQ-01 | `terraform/platform`, `terraform/pipeline`; one documented manual step (Decision 9) | AT-001 |
| REQ-02 | `warehouse.tf` (Decision 4) | AT-002 |
| REQ-03 | `monitors.tf` + `scripts/budget.sql` (Decisions 5, 8) | AT-003 |
| REQ-04 | `terraform/pipeline/gate.tf` (Decision 5) | AT-004 |
| REQ-05 | `gate.py` + `sensors.py` (Decision 6) | AT-005, AT-006 |
| REQ-06 | `tests/load/generate_load.py` | AT-007 |
| REQ-07 | `docs/measurement/` (Measurement plan) | AT-008 |
| REQ-08 | `.github/workflows/terraform.yml` | AT-009 |
| REQ-09 | `README.md`, Day 14 | AT-010 |
| REQ-10 | `docs/runbooks/` (+ `budget-alert.md`, added by Decision 5) | AT-011 |
| REQ-11 (COULD) | `jobs.py`: select `+bronze_<domain>+` from the run's `domains` tag. Built only if Day 6 has slack; otherwise roadmap. **Not** active during the A/B, so it cannot blur the comparison. | AT-012 |

---

## Measurement plan (REQ-06, REQ-07)

**Load profile (default, calibrated in the Day 7 dry run):** one burst every **60 min**, each burst
= a fixed, seeded mix of inserts and updates across the 10 domains (~200 rows), committed in one
transaction per domain. Seed fixed; the generator writes `docs/measurement/runs/<window>/commits.csv`.

**Windows (UTC):**

| Window | Start | End | Profile |
|--------|-------|-----|---------|
| Dry run | 2026-11-24 12:00 | 2026-11-24 18:00 | A for 3 h, then B for 3 h |
| A | 2026-11-25 03:00 | 2026-11-27 03:00 | baseline |
| B | 2026-11-27 03:00 | 2026-11-29 03:00 | optimized |
| Read results | ≥ 2026-11-29 07:00 | — | (`ACCOUNT_USAGE` latency) |

**Rough cost estimate (to size the budget, not a prediction to be confirmed):**

| | Uptime per burst | Bursts/day | Rate | Credits/day | 48 h |
|--|------------------|------------|------|-------------|------|
| A | ~10 min (tasks resume + up to 2 dbt runs + idle tails) | 24 | 1.35 cr/h | ~5.4 | ~11 |
| B | ~4 min (one dbt run + idle tail) + serverless seconds | 24 | 1.0 cr/h | ~1.6 + ε | ~3 |

Total including the dry run: ~15 credits. The estimate is deliberately written down **before**
measuring so the result can disagree with it.

**Validity rules:** no manual use of `CDC_WH` during A or B (ad-hoc work goes to `COMPUTE_WH`,
which is excluded from the analysis); the machine running the stack must stay awake — any gap of
> 2 bursts in `commits.csv` voids that window and it is rerun; the profile switch timestamp is
recorded in `docs/measurement/runs/switch.log`.

**Queries (in `docs/measurement/queries.sql`):**
- Warehouse credits/day — `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY`, `WAREHOUSE_NAME = 'CDC_WH'`.
- Serverless task credits/day — `SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY`, filtered to the `CDC_POC` database.
- Cross-check — `SNOWFLAKE.ACCOUNT_USAGE.METERING_HISTORY` grouped by `SERVICE_TYPE`.
- Resumes/day — `SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY`, resume events for `CDC_WH` (exact `EVENT_NAME` value to be confirmed against the view on Day 7).
- Freshness — `commits.csv` joined with `CDC_POC.CONFIG.PROCESSING_LOG` (Decision 7).

---

## File Manifest

| # | File | Action | Purpose | Dependencies |
|---|------|--------|---------|--------------|
| 1 | `scripts/00_terraform_bootstrap.sql` | Create | Terraform service user + roles (Decision 9) | — |
| 2 | `terraform/platform/versions.tf`, `providers.tf`, `backend.tf` | Create | Provider pin, role aliases, S3 state | 1 |
| 3 | `terraform/platform/variables.tf`, `profiles.tf` | Create | Names, `cost_profile`, limits | 2 |
| 4 | `terraform/platform/database.tf`, `warehouse.tf`, `monitors.tf`, `roles.tf`, `users.tf`, `grants.tf` | Create | REQ-01/02/03 | 3 |
| 5 | `scripts/bootstrap_config.sql` | Modify | Drop hard-coded names; add `PENDING_RUNS`, `STREAM_CONSUMPTION_LOG` | 4 |
| 6 | `scripts/budget.sql` | Create | Account budget (fallback if provider lacks a resource) | 4 |
| 7 | `terraform/pipeline/*.tf` | Create | Procedure, 10 streams, 10 tasks; `cost_profile` switch | 4, Bronze tables |
| 8 | `scripts/streams_and_tasks.sql` | Delete | Replaced by 7 (kept in git history) | 7 |
| 9 | `scripts/snowflake_setup.sql`, `scripts/00_account_bootstrap.sql` | Delete | Replaced by 1–4 | 4 |
| 10 | `dagster/pipeline/gate.py` | Create | Pure decision function (Decision 6) | — |
| 11 | `dagster/pipeline/sensors.py` | Modify | Use `gate.decide`; read `BATCH_WINDOW_MINUTES` | 10 |
| 12 | `tests/unit/test_gate.py` | Create | Exhaustive tests of 10 (AT-005, AT-006) | 10 |
| 13 | `tests/load/generate_load.py` | Create | Seeded load + commit log (REQ-06) | — |
| 14 | `docs/measurement/PROTOCOL.md`, `queries.sql`, `RESULTS_TEMPLATE.md` | Create | REQ-07 | 13 |
| 15 | `.github/workflows/terraform.yml` | Create | REQ-08 | 2–7 |
| 16 | `.github/workflows/deploy.yml` | Delete | Disabled since v2; replaced by 15 | 15 |
| 17 | `dbt/models/config/sources.yml` | Modify | Database name from env var (Decision 3) | — |
| 18 | `docs/runbooks/connector-down.md`, `monitor-suspended.md`, `budget-alert.md` | Create | REQ-10 | 4–7 |
| 19 | `Makefile` | Modify | `deploy-platform`, `deploy-pipeline`, `profile-a`, `profile-b`, `load` | 2–13 |
| 20 | `CLAUDE.md`, `.env.example` | Modify | Names, account, `BATCH_WINDOW_MINUTES`, `TERRAFORM_*` vars | — |
| 21 | `README.md` | Modify | *What it actually costs* with measured numbers (REQ-09) — Day 14 | 14 |

**Total files:** ~35 (Terraform files counted individually).

---

## File Ownership & Parallelism

| Path | Access | Notes |
|------|--------|-------|
| `terraform/`, `scripts/*.sql` | Owns | |
| `dagster/pipeline/sensors.py`, `gate.py`, `jobs.py` | Owns | |
| `tests/load/`, `tests/unit/test_gate.py` | Owns | |
| `docs/measurement/`, `docs/runbooks/connector-down.md`, `monitor-suspended.md`, `budget-alert.md` | Owns | |
| `.github/workflows/terraform.yml`, `deploy.yml` | Owns (new / delete) | |
| `.github/workflows/ci.yml` | Shared — serialize | Only to add `terraform` + `pytest` jobs; FT-03 also edits it |
| `dbt/models/config/sources.yml`, `dbt/dbt_project.yml` | Shared — serialize | One-line change (Decision 3) |
| `Makefile`, `README.md`, `CLAUDE.md`, `.env.example`, `docs/adr/` | Shared — serialize | |
| `dbt/models/**` (other) | Reads | REQ-11 selection only; COULD |

No intersection with SCD2_RESTAURANTS' owned paths (`dbt/macros/resolve_cdc.sql`, restaurant models,
fixtures). The two features can be built in parallel.

---

## Agent Assignment Rationale

| Role | Files | Why |
|------|-------|-----|
| Builder (Claude Code, Terraform + Snowflake context) | 1–9, 15–16, 19 | IaC and account objects; must load F1–F6 and the provider docs for each resource before writing it |
| Builder (Cursor, Python) | 10–13, 17 | Small, interactive edits; `gate.py` is the riskiest logic and benefits from tight human review |
| Author (Christian) | 14, 18, 21 | Protocol, runbooks and README are the portfolio's voice |
| Validator (fresh session) | VALIDATION | Loads DEFINE + `docs/measurement/` only |

---

## Code Patterns

### Pattern 1: Profiles as a lookup, not as conditionals scattered through resources

```hcl
# terraform/platform/profiles.tf
variable "cost_profile" {
  type    = string
  default = "optimized"
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
# terraform/platform/warehouse.tf — attribute names to be checked against provider docs at Build
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
# terraform/pipeline/gate.tf — sketch; the provider's task resource has strict field combinations
locals {
  domains = toset(["ORDERS", "ORDER_ITEMS", "DRIVERS", "DRIVER_SHIFTS", "RESTAURANTS",
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
  user_task_timeout_ms                     = 60000
  suspend_task_after_num_failures          = 3
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

## Data Flow (profile B, one burst)

1. `generate_load.py` commits a burst at *t0* and logs it.
2. Debezium → Kafka → Snowpipe Streaming commits rows to Bronze (seconds).
3. Within ≤ 1 min, each gate task with data runs **serverless**, writes `PENDING_RUNS`.
4. The sensor sees Kafka activity in Prometheus (0 credits) → `pending`. While the burst is still
   arriving (`quiet < 3`) or the last run was < *N* ago, it waits without touching Snowflake.
5. Once settled and outside the window, one `SELECT` on `PENDING_RUNS` resumes `CDC_WH`, all rows of
   the burst are marked consumed, one `cdc_pipeline_job` runs `dbt run` + `dbt test` on the same resume.
6. `PROCESSING_LOG` records `finished_at`; `CDC_WH` suspends 60 s after the last query.

---

## Integration Points

| System | Contract | Change in this feature |
|--------|----------|------------------------|
| Kafka connector | Creates Bronze tables; reads `SNOWFLAKE_DATABASE`, `SNOWFLAKE_ROLE` | None |
| Prometheus | `kafka_server_brokertopicmetrics_messagesin{topic=~"pg[.]public[.].*"}` | None |
| dbt | Reads `SNOWFLAKE_*` env vars | `sources.yml` database from env var |
| GitHub | Environment `snowflake-dev` with required reviewer; secrets `TF_SNOWFLAKE_PRIVATE_KEY`, AWS role for state | New |
| AWS S3 | Terraform state bucket with native lockfile | New (outside Snowflake budget) |

---

## Testing Strategy

| Level | What | How | AT |
|-------|------|-----|----|
| Static | Terraform format, validation, plan | CI on every PR, both roots | AT-009 |
| Unit | `gate.decide` / `after_query`: legacy parity with v2, settling, window, retry, cursor migration | `pytest`, table-driven; includes stranding, two-runs-per-burst, continuous-traffic starvation and lagging-task scenarios | AT-005, AT-006 |
| Integration | Apply on dev, then `plan` shows no changes | CI apply job + second plan | AT-001 |
| Account checks | `SHOW WAREHOUSES`, `SHOW RESOURCE MONITORS`, `SHOW TASKS` | `scripts/verify_governance.sql` (updated) | AT-002, 003, 004 |
| Generator | Same seed twice → identical counts | `pytest` on the plan the generator builds, no DB | AT-007 |
| Measurement | Protocol queries | Validator session | AT-008, 010 |

---

## Error Handling

| Failure | Behaviour |
|---------|-----------|
| Bronze tables missing at `pipeline` plan | Data source check fails with "run the stack and wait for first rows" |
| Gate task fails 3× | Task suspends itself; `budget-alert` / task-failure runbook |
| Monitor suspends `CDC_WH` | dbt runs fail fast; sensor keeps rows pending; `monitor-suspended` runbook |
| Prometheus down | Sensor fails open (v2 behaviour) — costs a resume, never loses data |
| Stack machine sleeps during a window | Gap detected in `commits.csv`; window voided and rerun |

---

## Configuration

| Variable | Where | Default | Notes |
|----------|-------|---------|-------|
| `cost_profile` | both Terraform roots | `optimized` | `baseline` only during window A |
| `database_name`, `warehouse_name`, `role_name`, `readonly_role_name` | Terraform | `CDC_POC`, `CDC_WH`, `CDC_ROLE`, `CDC_ROLE_RO` | Decision 3 |
| `cdc_wh_monitor_quota`, `account_monitor_quota`, `budget_limit` | Terraform | 25 / 50 / 60 credits | Decision 8 — provisional |
| `BATCH_WINDOW_MINUTES` | Dagster env | `10` | `0` reproduces v2 |
| `LOAD_SEED`, `LOAD_BURST_MINUTES`, `LOAD_ROWS_PER_BURST` | generator | `42`, `60`, `200` | Calibrated on Day 7 |

---

## Security Considerations

- Terraform runs as `TERRAFORM_SVC` with key-pair auth; roles split by provider alias (Decision 9).
- The private key exists only as a GitHub **environment** secret (not a repository secret), so
  workflows from forks and unprotected branches cannot read it. The repo is public.
- Public keys of service users are variables (not secret); private keys never enter Terraform state.
- Agents never run `apply` (Constitution R1): they run `plan` locally against dev with read-only use.

---

## Observability

- `SHOW TASKS` + `TASK_HISTORY` for gate runs; `SERVERLESS_TASK_HISTORY` for their cost.
- Budget notification and monitor notifications go to the account owner's e-mail.
- Grafana: unchanged in this feature (cost dashboard is roadmap).

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Provider lacks budget support or an account-level monitor assignment | Medium | Low | `scripts/budget.sql` and a versioned `ALTER ACCOUNT SET RESOURCE_MONITOR` step, documented as exceptions (A-002 fallback) |
| Provider `snowflake_task` field combinations differ from Pattern 3 | Medium | Low | Pattern is a sketch; Build checks the resource docs first |
| Laptop sleeps during 96 h of measurement | **High** | High | Disable sleep; detect gaps; rerun window. Option: run the stack on a small cloud VM for Days 8–11 |
| Estimate is wrong in the favourable direction and biases reading | Medium | Medium | Estimate written down before measuring; Validator is a fresh session |
| `WAREHOUSE_EVENTS_HISTORY` event names differ from assumed | Low | Low | Confirm on Day 7 dry run |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 0.1 | 2026-11-17 | Christian (with Claude) | Initial draft |
| 0.2 | 2026-11-17 | Christian (with Claude) | Self-review: Decision 6 rewritten (settle-then-run; v1 of it paid two resumes per burst); requirement coverage table added |
| 0.3 | 2026-11-17 | Christian (with Claude) | Simulation found starvation under continuous traffic; starvation guard added to Decision 6 / Pattern 4 |

---

## Next Step

Independent design review (fresh session, DEFINE + this file only). Then
**Ready for:** `/build .claude/sdd/features/COST_GOVERNANCE/DESIGN_COST_GOVERNANCE.md`
