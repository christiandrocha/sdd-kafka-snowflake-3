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
| COST_GOVERNANCE | Define — awaiting approval | [DEFINE](features/COST_GOVERNANCE/DEFINE_COST_GOVERNANCE.md) | Christian |
| SCD2_RESTAURANTS | Define — awaiting approval | [DEFINE](features/SCD2_RESTAURANTS/DEFINE_SCD2_RESTAURANTS.md) | Christian |

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
| `dagster/pipeline/sensors.py`, `jobs.py` | **Owns** | — | — |
| `tests/load/`, `docs/measurement/` | **Owns** | Reads | — |
| `docs/runbooks/connector-down.md`, `monitor-suspended.md` | **Owns** | — | FT-01 adds `schema-evolution.md` |
| `dbt/macros/resolve_cdc.sql` | — | **Owns** | — |
| `dbt/models/silver/silver_restaurants*.sql` | — | **Owns** | — |
| `dbt/models/gold/gold_revenue_by_restaurant_version.sql` | — | **Owns** | — |
| `tests/fixtures/restaurant_changes.*`, `dbt/tests/assert_restaurants_history_*.sql` | — | **Owns** | — |
| `dbt/dbt_project.yml` | Shared — serialize | Shared — serialize | — |
| `dbt/models/*/schema.yml` | — | Shared — serialize | FT-01 |
| `.github/workflows/*.yml` | Shared — serialize | — | FT-03 |
| `README.md`, `CLAUDE.md`, `docs/adr/` | Shared — serialize | Shared — serialize | FT-02, FT-04 |

The two features share no owned path. They can be built in parallel; shared files are touched
one PR at a time.

## 15-day plan

Day 1 = **{to be set}**. Days 8–11 are inelastic: the A/B measurement needs calendar days of
controlled load. Any slip in week 1 comes out of week 2's polish, never out of the measurement.

| Day | COST_GOVERNANCE | SCD2_RESTAURANTS | Fast tracks |
|-----|-----------------|------------------|-------------|
| 1 | Resolve resource-monitor discrepancy on the live account (blocking). Approve both DEFINEs. Create repo from v2. | — | — |
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
| 1 | Canonical resource-monitor values (v2 docs say 348 credits / `NEVER`; `snowflake_setup.sql` says 20 / `MONTHLY`). Run `SHOW RESOURCE MONITORS` on the live account. | **Yes** (Terraform on Day 3) | — |
| 2 | Credit budget for the A/B measurement | No | Cap of 15 credits on the v3 monitor |
| 3 | Repository name | No | `sdd-kafka-snowflake-3` |
| 4 | Day 1 date | No | Next business day after DEFINE approval |
| 5 | Terraform state backend | No | S3 bucket + DynamoDB lock in the same AWS account |

## Next feature after v3 ships

| Feature | Goal | Why after v3 |
|---------|------|--------------|
| ORCHESTRATOR_AIRFLOW_PORT (v3.1) | Port orchestration from Dagster to Airflow 3: dbt via Astronomer Cosmos, the same Prometheus → `PENDING_RUNS` gate as a deferrable sensor, the same batching window. Then run the v3 measurement protocol again with the same load: same pipeline, same gate, two orchestrators — credits, freshness, operational effort. | Changing the orchestrator inside v3 would mix orchestrator behaviour into the v2 × v3 A/B and invalidate it. Constraint: the gate stays in Snowflake; triggering DAGs from Kafka messages is out, as it reopens the publish-vs-materialize gap closed by ADR-0019. |

## Roadmap (documented, not built in this version)

Data contracts beyond the single reference model · chaos test of connector redelivery · data
observability (source freshness + volume anomaly alerts to a channel) · RBAC in two layers ·
privacy layer per jurisdiction (tags, masking, retention, purge) · Oracle / SQL Server sources ·
Azure variant · project templating (copier/cookiecutter) · `engagement/` kit for client kickoff · ingestion as a module (Fivetran / Openflow variants, decided per client by FT-05) · orchestrator as a module (Dagster / Airflow, decided per client).
