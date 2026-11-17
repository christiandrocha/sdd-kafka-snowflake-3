# DEFINE: Cost Governance 2.0 (COST_GOVERNANCE)

> Cut the part of the Snowflake bill that is warehouse uptime rather than query execution,
> deliver it as Terraform, and prove the effect with a controlled A/B measurement against v2.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | COST_GOVERNANCE |
| **Date** | 2026-11-17 |
| **Author** | Christian (with Claude) |
| **Status** | Draft — awaiting approval |
| **Clarity Score** | 13/15 |
| **Approved by** | — |

---

## Problem Statement

v2 measured it on its own invoice: on 2026-08-11, `CDC_WH` executed **72.7 s** of queries and
billed **1.1188 credits** — execution was under 2% of what was paid; the rest was the 60-second
minimum per resume and the idle tail before auto-suspend. Three configuration facts keep that
ratio high: the warehouse runs as **Gen2 by default** (`STANDARD_GEN_2`, a higher credit rate per
hour, chosen by a platform default, not by a decision); the ten gate tasks run **on the
warehouse**, so each firing pays a full minute for two sub-second `INSERT`s; and the Dagster
sensor can trigger a full `dbt run` + `dbt test` **every minute** during a burst. All objects are
also created by hand-run SQL, so none of this is reproducible on another account.

The account v3 runs on (`GWHUBCF-QQ53235`, created 2026-11-17) confirms the defaults are not an
accident of the old account: on day one, every warehouse the platform provisioned was Gen2, had
query acceleration enabled, and `COMPUTE_WH` had a 300-second auto-suspend; no resource monitor existed.

---

## Target Users

| User | Role | Pain point |
|------|------|------------|
| Christian | Owner, future consultant | Needs a cost story backed by measurement, reproducible on a client account |
| Future client | Platform owner | Needs predictable spend and infrastructure that is reviewable before it is applied |
| Reviewer / hiring manager | Reads the repo | Needs to see numbers with their method, not claims |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | Every Snowflake object of v3 is created and changed by Terraform through CI, with approval |
| **MUST** | Reduce billed uptime: Gen1 warehouse, serverless gate tasks, batched dbt runs |
| **MUST** | Measure v2 config × v3 config under the same controlled load and publish method + result |
| **MUST** | Close the spending gap: a monitor at account level, not only on the pipeline warehouse |
| **SHOULD** | Runbooks for the two cost-related incidents that will happen on a client account |
| **COULD** | Run dbt only for the domains that changed |

---

## Requirements

| ID | Requirement | Priority | Verified by |
|----|-------------|----------|-------------|
| REQ-01 | Terraform defines the v3 database, schemas, warehouse, roles, grants and resource monitors. Nothing in v3 is created by hand. | MUST | AT-001 |
| REQ-02 | Warehouse settings that drive cost are set explicitly in code, never left to platform defaults: generation via `GENERATION = '1'` (the account rejects `RESOURCE_CONSTRAINT = STANDARD_GEN_1` for this), and `ENABLE_QUERY_ACCELERATION = FALSE`. | MUST | AT-002 |
| REQ-03 | A resource monitor at **account** level exists in addition to the per-warehouse monitor on the v3 warehouse, each with notify and suspend thresholds. | MUST | AT-003 |
| REQ-04 | The ten gate tasks run as **serverless** tasks (no `WAREHOUSE`), keeping the `SYSTEM$STREAM_HAS_DATA` condition and the `SP_GATE_DOMAIN` semantics of ADR-0019. | MUST | AT-004 |
| REQ-05 | The Dagster sensor enforces a minimum interval *N* between `cdc_pipeline_job` runs (env var, default 10 min). Pending rows accumulate and are consumed by the next run — none are lost. | MUST | AT-005, AT-006 |
| REQ-06 | A deterministic load generator (seeded, fixed burst size and cadence) drives the source database for measurement. | MUST | AT-007 |
| REQ-07 | A written measurement protocol runs config **A** (v2 settings: Gen2, tasks on the warehouse, no window) and config **B** (v3 settings) under the same load, each for ≥ 48 h, and records credits, resumes and freshness from the views named in *Success Criteria*. | MUST | AT-008 |
| REQ-08 | CI runs `terraform fmt -check`, `validate` and `plan` on every PR; `apply` runs only on `main`, through a protected environment with a required reviewer. | MUST | AT-009 |
| REQ-09 | The README *What it actually costs* section is rewritten with the measured A/B numbers and the exact queries that produced them. | MUST | AT-010 |
| REQ-10 | Runbooks: "Kafka connector is down" and "a resource monitor suspended the warehouse". | SHOULD | AT-011 |
| REQ-11 | `cdc_pipeline_job` selects only the dbt models downstream of the domains in the sensor's `domains` tag. | COULD | AT-012 |

---

## Success Criteria

Total cost = warehouse credits (`SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY`) +
serverless task credits (`SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY`), per UTC day,
over the measurement window, same load profile for A and B.

- [ ] **H1 (falsifiable):** total credits/day of config B ≤ **75%** of config A.
- [ ] **H2 (falsifiable):** warehouse resumes/day of config B ≤ **50%** of config A
      (`ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY`, resume events).
- [ ] **Freshness guardrail:** p95 delay from source commit to Gold ≤ *N* + 5 min under load in config B.
- [ ] **Idle property preserved:** over ≥ 6 h with no source traffic, 0 warehouse credits and
      < 0.01 serverless task credits.
- [ ] **No drift:** `terraform plan` on `main` after `apply` reports no changes.

If H1 or H2 is not met, the feature still ships: the deliverable is the measured result with
its method. The README states the number we got, not the number we hoped for.

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | Reproducible infra | Empty v3 namespace on the account | CI applies `main` | All v3 objects exist; a second `plan` shows no changes |
| AT-002 | Cost settings pinned | Warehouse applied | `SHOW WAREHOUSES LIKE 'CDC_WH_V3'` | `generation` = 1, `resource_constraint` = `STANDARD_GEN_1`, `enable_query_acceleration` = false |
| AT-003 | Account cap | Monitors applied | `SHOW RESOURCE MONITORS` | One account-level and one v3-warehouse monitor, thresholds as in Terraform |
| AT-004 | Serverless gate | Tasks applied, no traffic | `SHOW TASKS IN SCHEMA` + 1 h idle | Tasks have no warehouse; `SERVERLESS_TASK_HISTORY` shows no billable runs while streams are empty |
| AT-005 | Batching window | A burst every 2 min for 30 min | Sensor runs | `cdc_pipeline_job` runs ≤ ⌈30/N⌉ + 1 times |
| AT-006 | No lost domain | Low-volume domain lands between two runs inside the window | Next run fires | That domain's rows reach Silver; `PENDING_RUNS` has no row left `consumed = FALSE` older than *N* + 2 min |
| AT-007 | Deterministic load | Same seed twice | Generator runs | Identical row counts per table and per minute |
| AT-008 | A/B measured | Configs A and B, 48 h each | Protocol queries run | `VALIDATION_COST_GOVERNANCE.md` reports H1, H2, freshness and idle numbers with their queries |
| AT-009 | Guarded apply | PR changing Terraform | CI | PR shows a plan; `apply` waits for reviewer approval on `main` |
| AT-010 | Honest README | Measurement done | Read README cost section | Every number has a query in the repo that reproduces it |
| AT-011 | Runbooks usable | A reviewer who did not write them | Follows each runbook in dev | Reaches the documented end state without asking the author |
| AT-012 | Domain scoping | Only `ORDERS` changed | Run fires | Only models downstream of `bronze_orders` execute |

---

## File Ownership (preliminary)

| Path | Access |
|------|--------|
| `terraform/` | Owns |
| `scripts/*.sql` (incl. `streams_and_tasks.sql`) | Owns |
| `dagster/pipeline/sensors.py`, `jobs.py` | Owns |
| `tests/load/`, `docs/measurement/` | Owns |
| `docs/runbooks/connector-down.md`, `monitor-suspended.md` | Owns |
| `dbt/dbt_project.yml`, `.github/workflows/*.yml`, `README.md`, `CLAUDE.md`, `docs/adr/` | Shared — serialize |
| `dbt/models/**` | Reads (REQ-11 selection only) |

## Build Skills / Context

| Agent role | Loads |
|------------|-------|
| Builder | Snowflake Terraform provider docs; Snowflake docs on warehouse generations, serverless tasks and resource monitors; v2 ADR-0019, ADR-0020, ADR-0024; v2 `sensors.py`, `streams_and_tasks.sql`, `00_account_bootstrap.sql`; v2 README *Cost governance* |
| Validator | This DEFINE, `docs/measurement/PROTOCOL.md`, the measurement queries. No DESIGN, no build context. |

---

## Out of Scope

- **dbt State** — evaluated and rejected; recorded as FT-04 (ADR only).
- Splitting ingestion, transformation and BI into separate warehouses — roadmap.
- Cost attribution by `QUERY_TAG` / object tags and a cost dashboard — roadmap.
- Dynamic Tables as a replacement for the gate — roadmap (candidate ADR).
- Migrating the gate to true triggered tasks (no `SCHEDULE`). The DESIGN must correct the
  terminology in ADR-0019 (v2 uses scheduled tasks with a `WHEN` clause), but the migration is not built here.
- Any change to dbt models other than the selection in REQ-11.

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Timeline | 15 days total; measurement needs ≥ 4 calendar days (Days 8–11) | Build must finish by Day 7, including a protocol dry run |
| Cost | Measurement budget capped at 15 credits (default, see open items) | The load profile must be sized to fit the cap |
| Technical | v2 is not deployed on this account; config A (v2 settings) must be deployed here for the A/B | The protocol compares A and B on this account only; v2's historical figures (other account) are context, not baseline |
| Account | Snowflake **trial** account `GWHUBCF-QQ53235` (AWS `sa-east-1`), created 2026-11-17 | Measurement (Days 8–11) must finish before the trial ends, and its credits come out of the trial balance; the repo must document what happens to the demo when the trial expires |
| Technical | `ACCOUNT_USAGE` views lag behind real time | Results are read after the window closes, not live |

---

## Assumptions

| ID | Assumption | If wrong, impact | Validated? |
|----|------------|------------------|------------|
| A-001 | Gen1 standard warehouses can still be created in `sa-east-1` | REQ-02 falls back to documenting the Gen2 cost and sizing around it | [x] 2026-11-17 — probe warehouse created with `GENERATION = '1'` reported `generation = 1`; `RESOURCE_CONSTRAINT = STANDARD_GEN_1` was rejected |
| A-002 | The Terraform provider supports the warehouse `GENERATION` property, serverless task and monitor settings | Unsupported settings go through a small, versioned SQL step called by CI, documented as an exception. **Higher risk since 2026-11-17:** `GENERATION` is the newer syntax and provider support must be checked first | [ ] Day 3 |
| A-006 | Trial time and credits cover Build + 4 days of measurement | Shrink the load profile, or add a payment method before Day 8 | [ ] Day 1 — check *Admin → Billing* |
| A-003 | Serverless tasks bill per second, with no 60-second minimum, at a multiplier near 1 | H1 may fail; the measurement still ships | [ ] Day 2 (rate card) |
| A-004 | The synthetic load is representative of a bursty CDC workload | Results do not generalize to continuous streaming; the README says so | [ ] By design |
| A-005 | A and B can run on the same account without interfering | Run them sequentially with v2 paused if interference shows up in the dry run | [ ] Day 7 |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Anchored on a measured invoice figure |
| Users | 2 | Future client is generic until a contract exists |
| Goals | 3 | Prioritized, each traceable to REQs |
| Success | 3 | Numbers, sources and method named; hypotheses explicitly falsifiable |
| Scope | 2 | Depends on the provider's support (A-002) and the monitor values (open question 1) |
| **Total** | **13/15** | |

---

## Open Questions

| # | Question | Blocking? | Owner | Default |
|---|----------|-----------|-------|---------|
| 1 | ~~Canonical resource-monitor values (v2 discrepancy 348/`NEVER` vs 20/`MONTHLY`)~~ | Resolved 2026-11-17 | — | Moot: v3 runs on a new account with **no** resource monitors. Terraform defines the canonical values from scratch; the DESIGN proposes them sized to the trial balance. |
| 6 | Trial end date and remaining credits | No (blocks Day 8 if short) | Christian, Day 1 | — |
| 2 | Batching window *N* | No | Christian | 10 min |
| 3 | Measurement credit cap | No | Christian | 15 credits |
| 4 | Terraform state backend | No | Christian | S3 + DynamoDB lock |
| 5 | Does the measurement isolate each change? | No | — | No: A/B measures the combined effect. The DESIGN estimates each change's share from the metering split (warehouse vs serverless) and says so. |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-11-17 | Christian (with Claude) | Initial version |
| 1.1 | 2026-11-17 | Christian (with Claude) | New trial account `GWHUBCF-QQ53235`: open question 1 resolved as moot; REQ-02/AT-002 use `GENERATION = '1'` and pin query acceleration off; A-001 validated; A-002 risk raised; A-006 and trial constraint added |

---

## Next Step

**Ready for:** `/design .claude/sdd/features/COST_GOVERNANCE/DEFINE_COST_GOVERNANCE.md` — after approval.
