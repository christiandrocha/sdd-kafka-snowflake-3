# SDD Index — sdd-kafka-snowflake-3

Live status of every feature and fast track. Updated at every phase transition.

## Goal of this version

Within 15 days, a public, English-only repository where:

1. Snowflake infrastructure is created by Terraform and deployed by CI with approval.
2. The cost changes over v2 are **measured** under a controlled load, not projected.
3. One SCD2 reference case shows end-to-end traceability, consumed by a Gold model.

"Showable" (Day 15) = CI/CD green with a real deploy, credits/day chart v2 × v3, ADRs, two
runbooks, README with *What it actually costs*.

## Features

| Feature | Phase | DEFINE | Owner |
|---------|-------|--------|-------|
| COST_GOVERNANCE | Design — draft 0.5 (two review rounds applied); awaiting independent sign-off | [DEFINE](features/COST_GOVERNANCE/DEFINE_COST_GOVERNANCE.md) · [DESIGN](features/COST_GOVERNANCE/DESIGN_COST_GOVERNANCE.md) | Christian |
| SCD2_RESTAURANTS | Define — approved 2026-11-17; Design on Day 3 | [DEFINE](features/SCD2_RESTAURANTS/DEFINE_SCD2_RESTAURANTS.md) | Christian |

## Fast tracks (mini-DEFINEs)

| ID | Change | Acceptance test | Status |
|----|--------|-----------------|--------|
| FT-01 | **Schema evolution drill**: add a nullable column to a source table in Postgres and follow it to Gold; document what propagated, what broke, and the runbook. | `docs/runbooks/schema-evolution.md` exists with the observed result of each layer (Bronze/Silver/Gold), reproduced by a script in `tests/`. | Todo |
| FT-02 | **Demo layer**: architecture diagram at the top of the README, a ≤ 2 min recording (event in Postgres → row in Gold), `make demo`. | A reviewer who never ran the project understands the flow in 90 s from the README alone. | Todo |
| FT-03 | **Security scans in CI**: Terraform static analysis (tfsec or checkov) and secret scanning. | CI fails on a planted test secret in a throwaway branch; passes on `main`. | Todo |
| FT-04 | **ADR — dbt State evaluated and rejected**, with the DATT arithmetic and the uptime-vs-execution evidence. | ADR merged; README links it from *Cost governance*. | Todo |
| FT-05 | **ADR — ingestion options compared** (docs only): Kafka/Debezium (current) vs Fivetran vs Snowflake Openflow, on latency, cost model (warehouse resumes, MAR, Openflow runtime), operations, event log vs current state, data residency. States when each is the right choice for a client. | ADR merged; every cost claim in it cites a source or is marked *unverified*; open questions listed (Fivetran history-mode granularity, Openflow runtime cost). | Todo |

## File ownership (parallelism map)

| Path | COST_GOVERNANCE | SCD2_RESTAURANTS | Fast tracks |
|------|-----------------|------------------|-------------|
| `terraform/` | **Owns** | — | FT-03 reads |
| `scripts/streams_and_tasks.sql`, `scripts/*.sql` | **Owns** | — | — |
| `dagster/pipeline/sensors.py`, `jobs.py`, `gate.py` | **Owns** | — | — |
| `tests/unit/test_gate.py`, `tests/unit/test_generate_load.py` | **Owns** | — | — |
| `terraform/env/dev.tfvars` | **Owns** | — | — |
| `tests/load/`, `docs/measurement/` | **Owns** | Reads | — |
| `docs/runbooks/` (connector-down, monitor-suspended, budget-alert, gate-task-failure, after-trial) | **Owns** | — | FT-01 adds `schema-evolution.md` |
| `dbt/macros/resolve_cdc.sql` | — | **Owns** | — |
| `dbt/models/silver/silver_restaurants*.sql` | — | **Owns** | — |
| `dbt/models/gold/gold_revenue_by_restaurant_version.sql` | — | **Owns** | — |
| `tests/fixtures/restaurant_changes.*`, `dbt/tests/assert_restaurants_history_*.sql` | — | **Owns** | — |
| `dbt/dbt_project.yml` | — (no dbt change, DESIGN Decision 3) | Shared — serialize | — |
| `dbt/models/*/schema.yml` | — | Shared — serialize | FT-01 |
| `.github/workflows/terraform.yml` (new), `deploy.yml` (delete) | **Owns** | — | — |
| `.github/workflows/ci.yml` | Shared — serialize | — | FT-03 |
| `Makefile`, `.env.example` | Shared — serialize | — | FT-02 (`make demo`) |
| `README.md`, `CLAUDE.md`, `docs/adr/` | Shared — serialize | Shared — serialize | FT-02, FT-04 |
| `.claude/skills/`, `.claude/sdd/templates/`, `.claude/sdd/README.md`, `CONSTITUTION.md` | Process files — changed only by a Retro or an explicit process PR | | |

The two features share no owned path. They can be built in parallel; shared files are touched
one PR at a time.

## 15-day plan

Day 1 = **2026-11-18** → Day 8–11 (measurement) = **Nov 25–28** · Day 15 (showable) = **Dec 2** · trial ends **Dec 17**. Days 8–11 are inelastic: the A/B measurement needs calendar days of
controlled load. Any slip in week 1 comes out of week 2's polish, never out of the measurement.

| Day | COST_GOVERNANCE | SCD2_RESTAURANTS | Fast tracks |
|-----|-----------------|------------------|-------------|
| 1 | ✅ Repo created, CI green. ✅ Account checked (new trial, no monitors, Gen1 available). ✅ Both DEFINEs approved. ✅ Trial ends Dec 17. | — | — |
| 2 | DESIGN + second-opinion review | — | FT-04 |
| 3–4 | Build: Terraform core (warehouse Gen1, roles, monitors incl. account level, state backend), CI `plan` + approved `apply` | DESIGN + review | — |
| 5–6 | Build: serverless gate tasks, run-batching window, load generator | Build: fixture of restaurant changes, `scd2` strategy | FT-03 |
| 7 | Dry run of the measurement protocol (½ day of each config) | Build: history model, current-state reconciliation, Gold consumer, contract, tests | — |
| 8–9 | **Measurement A — v2 configuration** under the fixed load | Validate (independent session) | FT-01 |
| 10–11 | **Measurement B — v3 configuration** under the same load | Ship + Retro | — |
| 12 | Validate (independent session): queries, chart | — | FT-02 |
| 13 | Ship: ADRs, runbooks (connector down; monitor suspended the warehouse) | — | FT-05 |
| 14 | README *What it actually costs* rewritten with measured numbers. Retro. | — | — |
| 15 | Buffer / polish. LinkedIn post #2 with the measured chart. | — | — |

## Open items before Day 1

| # | Item | Blocking? | Default if unanswered |
|---|------|-----------|-----------------------|
| 1 | ~~Canonical resource-monitor values~~ — resolved 2026-11-17: new trial account `GWHUBCF-QQ53235`, no monitors; Terraform defines them from scratch. | Resolved | — |
| 2 | ~~Credit budget for the A/B measurement~~ — resolved: 25 credits on the `CDC_WH` monitor (owner decision) | Resolved | — |
| 6 | ~~Trial end date and balance~~ — resolved: 2026-12-17, USD 400 | Resolved | — |
| 7 | Credit price for this edition/region (*Admin → Billing*) | Blocks the first apply (Day 3) | Lower the limits if 60 credits > 50% of the balance |
| 3 | Repository name | No | `sdd-kafka-snowflake-3` |
| 4 | ~~Day 1 date~~ — resolved: 2026-11-18 | Resolved | — |
| 5 | ~~Terraform state backend~~ — resolved: S3 with native lockfile, no DynamoDB (DESIGN Decision 12) | Resolved | — |

## Next feature after v3 ships

| Feature | Goal | Why after v3 |
|---------|------|--------------|
| ORCHESTRATOR_AIRFLOW_PORT (v3.1) | Port orchestration from Dagster to Airflow 3: dbt via Astronomer Cosmos, the same Prometheus → `PENDING_RUNS` gate as a deferrable sensor, the same batching window. Then run the v3 measurement protocol again with the same load: same pipeline, same gate, two orchestrators — credits, freshness, operational effort. | Changing the orchestrator inside v3 would mix orchestrator behaviour into the v2 × v3 A/B and invalidate it. Constraint: the gate stays in Snowflake; triggering DAGs from Kafka messages is out, as it reopens the publish-vs-materialize gap closed by ADR-0019. |

## Roadmap (documented, not built in this version)

Data contracts beyond the single reference model · chaos test of connector redelivery · data
observability (source freshness + volume anomaly alerts to a channel) · RBAC in two layers ·
privacy layer per jurisdiction (tags, masking, retention, purge) · Oracle / SQL Server sources ·
Azure variant · project templating (copier/cookiecutter) · `engagement/` kit for client kickoff · ingestion as a module (Fivetran / Openflow variants, decided per client by FT-05) · orchestrator as a module (Dagster / Airflow, decided per client).
