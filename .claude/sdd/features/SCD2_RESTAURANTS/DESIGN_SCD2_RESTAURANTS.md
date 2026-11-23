# DESIGN: SCD Type 2 for Restaurants — reference case (SCD2_RESTAURANTS)

> Technical design for deriving restaurant version history from the CDC event log already in
> Snowflake, and for a Gold model that attributes each sale to the restaurant as it was then.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | SCD2_RESTAURANTS |
| **Date** | 2026-11-23 |
| **Author** | design-agent (Claude Code), owner Christian |
| **DEFINE** | [DEFINE_SCD2_RESTAURANTS.md](./DEFINE_SCD2_RESTAURANTS.md) — v1.1, Approved |
| **Status** | 1.0.1 — Draft, awaiting independent review (Decisions 8–9 owner-approved) |

---

## Findings that shaped this design (verified 2026-11-23)

| # | Finding | Source | Effect on the design |
|---|---------|--------|----------------------|
| F1 | **The dbt Bronze model does not keep history.** `bronze_restaurants` is `incremental`/`merge` on `uuid`, with a per-batch `ROW_NUMBER` dedup: one row per restaurant, the latest. Same for `bronze_order_items` (one row per `order_item_id`). The DEFINE's "Bronze keeps every CDC event" is true only of the **raw landing table** `CDC_POC.BRONZE.RESTAURANTS` (`source('bronze_raw', 'RESTAURANTS')`), which the connector only appends to (ADR-0025). | `dbt/models/bronze/bronze_restaurants.sql`, `bronze_order_items.sql`, `dbt/models/config/sources.yml` | The history reads the raw landing table, not `ref('bronze_restaurants')` (Decision 2). Same for the item event time (Decision 5). |
| F2 | Nothing in the repo purges the raw landing tables: no `TRUNCATE`/`DELETE` in `terraform/`, `scripts/`, `dagster/`, `dbt/`. Database Time Travel is 1 day, which does not matter for a table that only grows. | `grep` over the repo; `terraform/platform/database.tf` | Rebuilding from the raw table is deterministic for as long as the table lives. |
| F3 | `resolve_cdc` takes the strategy from `CONFIG.TABLE_METADATA` through `get_config_for(model_name)`, which strips the layer prefix: `silver_restaurants_history` → `restaurants_history`, which is not registered. It would fall back to `upsert` with `unique_key = 'id'` and log a warning. `TABLE_METADATA` holds one strategy per **source table**, and its seed (`scripts/seed_config.sql`) and table (`terraform/platform/config_tables.tf`) are owned by COST_GOVERNANCE. | `dbt/macros/get_table_config.sql`, `_index.md` ownership | Strategy passed as an explicit macro argument, with no `TABLE_METADATA` row (Decision 1). |
| F4 | Postgres `restaurants` has `PRIMARY KEY (uuid)` and **no `REPLICA IDENTITY FULL`**. Debezium: "the before field contains only the primary key column because the table's REPLICA IDENTITY setting is DEFAULT." With `delete.handling.mode=rewrite`, the flattened value "directly contains the key/value pairs that were in the before field". | `scripts/init.sql`; Debezium PostgreSQL connector docs (*delete event value*); Debezium *New Record State Extraction* docs | The delete row in the raw table carries `uuid`, `__OP = 'd'`, `__SOURCE_TS_MS` and **NULL in every other column**, `restaurant_id` included. The delete version therefore never matches an item by `restaurant_id` (Decision 6). Whether NOT NULL columns such as `dt_current_timestamp` arrive as NULL or as a default is *unverified*: the Build checks the first real delete row. |
| F5 | Debezium "provides at least once delivery of change events" during fault recovery. The Bronze models already assume redelivery ("idempotent over Snowpipe Streaming redelivery"). | Debezium PostgreSQL docs (*Behavior when things go wrong*); `bronze_*.sql` headers | The history deduplicates exact repeats of an event before versioning (Decision 3). |
| F6 | `ts_ms` / `source.ts_ms` is the time the change was made in the database. For snapshot rows (`op = 'r'`) it is the time of the snapshot read, *not* a business time. The connector runs `snapshot.mode = initial`. | Debezium PostgreSQL docs (*source* block, `op` values); `connectors/debezium.json` | Rows that existed before CDC started get the snapshot time as their first `valid_from`. An item snapshotted a few ms before its restaurant would match nothing (Decision 6). The exact per-row meaning of `ts_ms` during an initial snapshot is *unverified*; the simulation covers both orders. |
| F7 | dbt model contracts are supported for `table` (and `view`, without constraints). "When enforced, your contract must include every column's name and data_type." dbt runs a preflight check that compares the query's columns with the contract and fails the build on a mismatch. Ephemeral models are not supported. | dbt docs, *Model contracts*; project pins `dbt-core==1.7.*` / `dbt-snowflake==1.7.*` (`dagster/Dockerfile`, `ci.yml`) | Gold model `table` with `contract: {enforced: true}` and explicit `CAST`s in its final `SELECT` (Decision 7). How strictly dbt-snowflake 1.7 compares precision (`NUMBER` vs `NUMBER(38,0)`) is *unverified*; settled by the first real build. |
| F8 | The Dagster pipeline runs `dbt run --select bronze silver gold`, then `dbt test --select bronze silver gold`, on **every gated run**. A failing test fails the run, and COST_GOVERNANCE's `pending_run_release_sensor` puts its rows back to pending, so the next window runs it again. | `dagster/pipeline/assets.py`, `dagster/pipeline/sensors.py` (COST_GOVERNANCE Decision 7) | Every new model rebuilds on every run. A failing SCD2 test would re-run the pipeline every window, which costs credits, so the tests default to `warn` inside the pipeline (Decision 8). The extra models must not exist during the A/B measurement (Decision 9). |
| F9 | `restaurant_id` is not unique. The seeded data has collisions (v2 resolves them with a `QUALIFY`). The load generator inserts restaurants with `restaurant_id = randint(2, 10**5)` and order items with `restaurant_id = randint(1, 500)`. It updates only `average_rating` and `num_reviews` of the restaurants it created itself (UUID5 keys under its own namespace). | `gold_revenue_per_restaurant.sql`, `silver/schema.yml` (`unique` at warn), `tests/load/generate_load.py` | The point-in-time join resolves ties deterministically and flags them (Decision 6). The fixture uses its own key namespace and a `restaurant_id` range no generator reaches (Decision 10). The load's rating updates create real versions (O37), not fixture noise. |
| F10 | No consumer outside dbt reads `silver_restaurants`: Dagster's processing log counts rows generically from `run_results.json`, and nothing in `observability/`, `scripts/` or `docs/measurement/` names it. | `grep` over the repo | A-003 is **validated**. Decision 4 keeps the table anyway. |
| F11 | The CI only runs `dbt deps` + `dbt parse` with dummy credentials and prints model/test counts. It does not compile against Snowflake. | `.github/workflows/ci.yml` | Parsing is the only automatic check before the Day 12 build. The SQL logic is pinned by the simulation (below) and by the dbt tests on the real account. |

### Assumptions from the DEFINE

| ID | Status after this design |
|----|--------------------------|
| A-001 (seeded data has almost no restaurant changes) | Still open. Checked at the first real build: `SELECT uuid, COUNT(*) FROM CDC_POC.BRONZE.RESTAURANTS GROUP BY 1 HAVING COUNT(*) > 1`. Measurement load will add versions anyway (F9). |
| A-002 (one event per committed update) | Still open. The fixture commits each change in its own transaction, with a ≥ 1.1 s gap, so a count mismatch points at Debezium, not at the fixture. |
| A-003 (no consumer outside dbt) | **Validated** (F10). |

---

## Architecture Overview

```text
Postgres public.restaurants ──Debezium──► Kafka ──Snowpipe Streaming──► CDC_POC.BRONZE.RESTAURANTS (raw, append-only)
Postgres public.order_items ──Debezium──► Kafka ──Snowpipe Streaming──► CDC_POC.BRONZE.ORDER_ITEMS (raw, append-only)
         ▲                                                                   │                        │
tests/fixtures/restaurant_changes.py                                         │                        │
(known changes, own key range)                                               │                        │
                                                                             │                        │
   existing, unchanged:                                                      │                        │
   bronze_restaurants (merge) ─► silver_restaurants (upsert) ─► gold_revenue_per_restaurant           │
             │                          ▲ reconciles (AT-004)               ▲ same total (AT-006)     │
             │ horizon = MAX(kafka_created_at)                              │                         │
             ▼                          │                                   │                         │
   NEW silver_restaurants_events (view) ◄───────────── raw RESTAURANTS      │                         │
             │                          │                                   │                         │
             ▼ resolve_cdc(strategy='scd2')                                 │                         │
   NEW silver_restaurants_history (table) ─────────────┐                    │                         │
                                                       ▼                    │                         │
   silver_order_items (existing) ──► NEW silver_restaurants_item_attribution (table) ◄── MIN(__SOURCE_TS_MS)
                                                       │                                 per item, raw ORDER_ITEMS
                                                       ▼
                                  NEW gold_revenue_by_restaurant_version (table, enforced contract)
```

---

## Components

| Component | Purpose | Technology |
|-----------|---------|------------|
| `resolve_cdc` — `scd2` branch | Generic: one row per CDC event per key, with `version_number`, `valid_from`, `valid_to`, `is_current`, `is_deleted` | dbt macro (Jinja + Snowflake SQL) |
| `silver_restaurants_events` | Projects the raw landing table into the macro's input contract (lowercase columns, `op`, `source_ts_ms`, `kafka_*`), capped at Bronze's horizon | dbt `view` |
| `silver_restaurants_history` | The SCD2 history of restaurants | dbt `table` |
| `silver_restaurants_item_attribution` | One row per order item: its event time and the restaurant version it belongs to, with an attribution status | dbt `table` |
| `gold_revenue_by_restaurant_version` | Revenue per restaurant version, with an enforced contract | dbt `table` |
| `restaurant_changes.py` | Deterministic fixture that issues known changes in Postgres | Python 3.11, `psycopg2` |
| Tests | History shape, reconciliation, fixture counts, sum preservation | dbt singular tests, `pytest` |
| ADR-0031 | Event-log SCD2 vs dbt snapshots, one domain | Markdown |

---

## Key Decisions

### Decision 1: `scd2` is selected by an explicit macro argument, not by `TABLE_METADATA`

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-11-23 |

**Context:** `resolve_cdc` reads the strategy from `TABLE_METADATA`, which is keyed by source table (F3).
The history is a second reading of the same table that `silver_restaurants` already reads as `upsert`.

**Choice:** `resolve_cdc(source_ref, model_name=none, strategy=none)`. When `strategy` is given, it
wins. `unique_key` still comes from the config of `model_name`. The history model calls
`resolve_cdc(ref('silver_restaurants_events'), model_name='silver_restaurants', strategy='scd2')`.
The error message for an unknown strategy lists `scd2`. With no `strategy` argument, the three
existing branches compile to the same SQL as today, byte for byte.

**Rationale:** one table can be read two ways at once. A `TABLE_METADATA` row cannot express that,
and writing one would touch `scripts/seed_config.sql`, `config_tables.tf` and the drift test, all
owned by COST_GOVERNANCE.

**Alternatives Rejected:**
1. Add a `restaurants_history` row to `TABLE_METADATA`. Rejected: it crosses ownership (R6), and it
   registers a "domain" with no source table, which the drift test and `sync_metadata.py` do not
   expect.
2. Change `restaurants` to `scd2` in `TABLE_METADATA`. Rejected: it would change `silver_restaurants`,
   which REQ-03 forbids.

**Consequences:**
- The strategy of the history lives in code, not in config. That is acceptable: it is a modelling
  choice, not an operational switch.
- REQ-01's "without changing the behaviour of the other three" becomes checkable: the compiled SQL
  of all ten existing Silver models must be unchanged (Testing Strategy, T1).

---

### Decision 2: The history reads the raw landing table, capped at Bronze's horizon

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-11-23 |

**Context:** F1. Only the raw table keeps every event. But the raw table keeps receiving rows
while a `dbt run` is in flight, so a history read a few seconds after `bronze_restaurants` could see
events that `silver_restaurants` did not. The reconciliation test (AT-004) would then fail
intermittently.

**Choice:** a view `silver_restaurants_events` selects from `source('bronze_raw', 'RESTAURANTS')`
with the same column projection as `bronze_restaurants` (no dedup). It keeps:
- `UUID IS NOT NULL`, which drops the tombstones;
- `RECORD_METADATA:CreateTime::BIGINT <= (SELECT MAX(kafka_created_at) FROM {{ ref('bronze_restaurants') }})`.

That `ref` also orders the view after Bronze in the DAG.

**Rationale:** the history and the current state are built from the same set of events, so the
two can be compared exactly. The view is free to build (DDL only), and it gives an auditor the event
log under readable column names.

**Alternatives Rejected:**
1. `ref('bronze_restaurants')`. Rejected: it has one row per key, so there is no history (F1).
2. A new model under `dbt/models/bronze/`. Rejected: `bronze/**` is *Reads* for this feature, and
   Bronze is the layer that mirrors ingestion, not one that reshapes it.
3. An `ephemeral` CTE. Rejected: it cannot be queried or tested by itself, and it is a node type
   whose Dagster asset behaviour this design has not verified.
4. No horizon. Rejected: AT-004 would be flaky under a live connector.

**Consequences:**
- The `view` needs a header-comment justification (CLAUDE.md convention). The text is in Pattern 2.
- If the Bronze watermark ever skips a late-landing row (a row whose `CreateTime` is below the
  previous maximum), the history will contain it and `silver_restaurants` will not. AT-004 then
  fails on a **real** Bronze defect, which is the purpose of the test. Risk R4.

---

### Decision 3: Exact repeats of an event are collapsed before versioning; equal-content versions are not (REQ-09 deferred)

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-11-23 |

**Context:** F5. A redelivered message is the **same event** twice. REQ-09 (COULD) is about
**different events** that carry identical tracked values.

**Choice:** inside the `scd2` branch, keep one row per
`(unique_key, kafka_partition, kafka_offset, source_ts_ms)`. `source_ts_ms` is in the key because a
topic recreated in dev (`docker compose down -v`) reuses offsets, while the Snowflake table keeps the
old rows. REQ-09 stays out, as the DEFINE's default for open question 4 says.

**Rationale:** without the dedup, one redelivered message adds a fake version and breaks the
fixture count ("changes + 1"). With it, the version count is a property of the source, not of the
transport.

**Alternatives Rejected:**
1. Dedup on `(kafka_partition, kafka_offset)` only. Rejected: it collides after a topic is recreated.
2. Implement REQ-09 now. Rejected for this version (DEFINE timeline). Its trigger is recorded
   instead: if A-001's count shows repeated `op = 'r'` rows for a key (a re-snapshot), REQ-09 moves
   into the next version.

**Consequences:**
- Same-millisecond changes to one key stay as separate versions, ordered by `kafka_offset`. The
  earlier one gets a zero-length interval `[t, t)`, which by construction matches no item. The
  simulation covers this case.

---

### Decision 4: `silver_restaurants` stays an `upsert` table; a test proves it agrees with the history

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-11-23 |

**Context:** DEFINE open question 3, REQ-03.

**Choice:** `silver_restaurants.sql` is not modified. The test `assert_restaurants_history_reconciles_current`
compares `history WHERE is_current` with `silver_restaurants` in both directions (`EXCEPT` each way)
on `uuid` plus every business column.

**Rationale:** zero change for any consumer (MUST goal 2), and the test gives the same guarantee a
view would.

**Alternatives Rejected:**
1. Make `silver_restaurants` a view over the history. Rejected: it changes its materialization and
   lineage for no gain, and it couples the frozen Gold model to the new code.

**Consequences:**
- Two code paths compute the current state. The test is what keeps them from drifting apart, so it
  must run on every pipeline run (Decision 8).

---

### Decision 5: An item's event time is the first time CDC saw it

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-11-23 |

**Context:** DEFINE open question 1. `silver_order_items.source_ts_ms` is the **latest** event.
`dt_current_timestamp` comes from a different clock (business data: seeded rows carry historical
dates), so comparing it with CDC validity intervals would mix clocks.

**Choice:** `item_event_ts = TO_TIMESTAMP_NTZ(MIN(__SOURCE_TS_MS), 3)` per `ORDER_ITEM_ID`, from
`source('bronze_raw', 'ORDER_ITEMS')`. The item population is `silver_order_items` with
`restaurant_id IS NOT NULL`, exactly the population of `gold_revenue_per_restaurant`.

**Rationale:** this is the DEFINE's default, and it uses the same clock as `valid_from`. `MIN` is
immune to redelivered rows. Using the existing item population is what makes the sum test (AT-006)
exact.

**Alternatives Rejected:**
1. `silver_order_items.source_ts_ms`. Rejected: an item edited after a restaurant change would move
   to the newer version.
2. `dt_current_timestamp`. Rejected: different clock.
3. Add a `first_source_ts_ms` column to `bronze_order_items`. Rejected: `bronze/**` is *Reads*, and
   the column would be wrong for any key the merge saw only after the update.

**Consequences:**
- Every pipeline run aggregates the raw `ORDER_ITEMS` table on two columns. That is the
  project's largest table (≈ 210 k seeded rows plus the load). It is a columnar scan of two
  columns; its cost is recorded at the Day 12 build (Observability).

---

### Decision 6: Point-in-time join on `restaurant_id`, with an explicit status for every item

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-11-23 |

**Context:** DEFINE open question 2 and constraint 2. There are three edge cases: the delete row has
`restaurant_id` NULL (F4), snapshot rows have a capture time rather than a business time (F6), and
`restaurant_id` is not unique (F9). The success criterion asks for "exactly one version, or an
explicit `unmatched` flag; zero items match two versions".

**Choice:** an item joins history rows where:
- `h.restaurant_id = i.restaurant_id`;
- `NOT h.is_deleted`;
- `i.item_event_ts >= h.effective_from`, where `effective_from` is `'1900-01-01'` when
  `version_number = 1 AND op = 'r'`, and `valid_from` otherwise;
- `i.item_event_ts < COALESCE(h.valid_to, '9999-12-31')`.

When more than one candidate matches, the row with the latest `(valid_from, kafka_offset)` wins.
Every item gets exactly one `attribution_status`:

| Status | Meaning |
|--------|---------|
| `matched` | Exactly one version was valid at the event time |
| `before_first_capture` | Matched a snapshot first version, and the event time is before the snapshot read |
| `ambiguous_resolved` | Several restaurants (`uuid`s) sharing the `restaurant_id` were valid; the latest won; `candidate_count` keeps the number |
| `no_version_at_event_time` | The `restaurant_id` has history, but no live version at that time (for example, after a delete) |
| `unregistered` | The `restaurant_id` never appears in the history (v2's `sem_cadastro`) |

**Rationale:**
- The tie-break mirrors v2's `QUALIFY`, so it stays deterministic.
- The backfill applies **only to snapshot rows**. The first draft applied it to every first version,
  and the simulation showed that this attributes sales to a restaurant created **after** them.
- Every item appears exactly once, so revenue is never dropped or doubled.

**Alternatives Rejected:**
1. Resolve `restaurant_id` → `uuid` first, then join on `uuid`. Rejected: which `uuid` is valid
   depends on time, so this hides the ambiguity instead of flagging it.
2. Leave ambiguous items unattributed. Rejected: it fails "exactly one version" and makes the
   breakdown noisier than v2's.
3. Backfill every first version. Rejected: the simulation found it wrong (above).

**Consequences:**
- Revenue after a restaurant is deleted shows up as `no_version_at_event_time` instead of being
  attributed to a deleted restaurant. That is honest, and it is visible in Gold.

---

### Decision 7: Gold grain and contract

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-11-23 |

**Choice:** `gold_revenue_by_restaurant_version` has one row per `attribution_key`:
- `uuid || ':' || version_number` for an attributed row;
- `'unattributed:' || attribution_status || ':' || restaurant_id` otherwise.

Columns, all English, all `CAST` explicitly in the final `SELECT`:

| Column | Type | Constraint |
|--------|------|------------|
| `attribution_key` | `VARCHAR` | `not_null` |
| `restaurant_id` | `NUMBER(38,0)` | `not_null` |
| `restaurant_uuid` | `VARCHAR` | — |
| `version_number` | `NUMBER(38,0)` | — |
| `valid_from`, `valid_to` | `TIMESTAMP_NTZ` | — |
| `attribution_status` | `VARCHAR` | `not_null` |
| `restaurant_name`, `city`, `country`, `cuisine_type` | `VARCHAR` | — |
| `average_rating` | `FLOAT` | — |
| `items_sold`, `orders`, `units` | `NUMBER(38,0)` | `not_null` |
| `gross_revenue`, `discounts`, `net_revenue` | `FLOAT` | `not_null` |

Schema tests: `unique` + `not_null` on `attribution_key`, and `accepted_values` on
`attribution_status`. Snowflake enforces `not_null` only; the rest are metadata (F7).

**Rationale:** aggregating per version answers the analyst's question ("revenue while it was
Italian") and keeps the table small. Item-level detail lives in Silver, where it is tested. The
explicit `CAST`s pin types that would otherwise depend on Avro → schematization mappings (`FLOAT`
comes from `decimal.handling.mode = double`).

**Alternatives Rejected:**
1. Item-level Gold. Rejected: it duplicates Silver and is not an aggregate (ADR-0026 categories).
2. Contract on the Silver models too. Rejected: REQ-05 asks for one reference contract.

**Consequences:**
- AT-007 is checked by hand: change one `CAST` and confirm that `dbt build` fails. It needs a
  connection, so it cannot run in CI (F11).

---

### Decision 8: SCD2 tests are `warn` inside the gated pipeline and `error` in Build/Validation

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted — owner (Christian), 2026-11-23 |
| **Date** | 2026-11-23 |

**Context:** F8. A test that fails with `error` fails the Dagster run. The failed-run release puts
its rows back to pending, so every batching window would run (and fail) the whole pipeline again,
spending `CDC_WH` credits until someone looks. ADR-0027 would class these tests as `error`, because
a wrong history makes a metric wrong.

**Choice:** each SCD2 singular test sets
`config(severity = 'error' if var('scd2_strict', false) else 'warn')`. Build and Validation run
`dbt build --vars '{scd2_strict: true}'`. The pipeline runs with the default, so a failure shows up
as a warning in the run log and the `PROCESSING_LOG` asset, without a retry loop.

**Rationale:** a new reference feature must not be able to turn a data defect into a cost incident
in the pipeline that COST_GOVERNANCE is measuring. The owner of the data still sees the failure.

**Alternatives Rejected:**
1. `error` everywhere (ADR-0027 as written). Rejected: retry loop and credit burn (F8).
2. Exclude the tests from the pipeline's `dbt test`. Rejected: it requires editing `assets.py`
   (COST_GOVERNANCE), and the reconciliation would then never run where the drift happens.

**Consequences:**
- This is an exception to ADR-0027. ADR-0031 records it. The owner accepted it; the reviewer may still challenge it.

---

### Decision 9: No SCD2 artifact touches `main` or the account during the A/B measurement

| Attribute | Value |
|-----------|-------|
| **Status** | Accepted — owner (Christian), 2026-11-23; `_index.md` plan updated |
| **Date** | 2026-11-23 |

**Context:**
- F8: any new model under `silver/` or `gold/` runs on every gated run.
- The fixture writes to Postgres, so it adds CDC events.
- Either would change the work done in Measurement B compared with Measurement A
  (2026-11-25 → 2026-11-28) and invalidate the A/B.
- The plan put SCD2 Validation on Days 8–9, inside that window.
- The account has had no apply yet (COST_GOVERNANCE O39), and the raw tables do not exist until the
  connector first writes, so an end-to-end SCD2 build is impossible before the window anyway.

**Choice:**
1. **Days 6–11:** offline Build only. Write the macro, models, tests, fixture and ADR; check them
   with `dbt parse`, `pytest` and the simulation. PRs stay open (not merged).
2. **Nothing SCD2** runs on the account or on Postgres from the Day 7 dry run until Measurement B
   ends (2026-11-29 00:00 UTC): no fixture, no `dbt build`.
3. **Day 12 (Nov 29):**
   - merge;
   - apply the fixture;
   - run `dbt build --vars '{scd2_strict: true}'` twice (determinism);
   - record A-001/A-002/F4/F7 results in the BUILD_REPORT.
4. **Day 13:** independent Validation. **Day 14:** Ship and Retro, alongside COST_GOVERNANCE.

**Rationale:** the A/B is the version's main deliverable, and the plan says the measurement days are
not negotiable. SCD2 adds work to every run, so it must arrive after the measurement.

**Alternatives Rejected:**
1. Merge before Day 8. Rejected: there is not enough time, and the Measurement A pipeline would then
   carry the SCD2 work while v2 does not, which biases the comparison.
2. Build on the account under a separate warehouse during the window. Rejected: the fixture still
   adds CDC events to the measured pipeline.

**Consequences:**
- The README's measured costs do not include the SCD2 models. The README states this (item 22 of
  COST_GOVERNANCE, shared file) and gives the Day 12 build's cost of the four new models as a
  separate line.
- `_index.md`'s 15-day plan moved the SCD2 rows: Build offline on Days 7–11, real build on Day 12, Validate on Day 13, Ship on Day 14 (done 2026-11-23).

---

### Decision 10: Fixture with its own key space, one commit per change, run once

| Attribute | Value |
|-----------|-------|
| **Status** | Proposed |
| **Date** | 2026-11-23 |

**Context:** REQ-07 and AT-001/003/005. The measurement load also creates restaurant versions (F9,
O37), so the fixture must not depend on them or collide with them.

**Choice:** `tests/fixtures/restaurant_changes.py`:
- Keys are UUID5 under a fixed fixture namespace (different from the load generator's).
- `restaurant_id` values are 990001–990004, outside every generator range.
- Order items use their own UUID5 keys.
- Each step commits on its own and sleeps 1.1 s, so `source_ts_ms` values are distinct and ordered.
- If any fixture key already exists, the script refuses to run (exit 2). Re-running would add
  versions and break the "changes + 1" count.
- `--plan-only` prints the steps without connecting.
- The expected result lives in `restaurant_changes_expected.csv`, with one row per
  (`uuid`, `version_number`): `op`, `cuisine_type`, `city`, `is_deleted`. A singular test
  embeds the same rows.

| Step | Change | Expected effect |
|------|--------|-----------------|
| 1 | Insert R1 (Italian, São Paulo), R2, R3, R4 | 4 × version 1 (`op = 'c'`) |
| 2 | Insert item I1 for R1 | I1 → R1 v1 |
| 3 | R1 `cuisine_type` → Japanese | R1 v2 |
| 4 | Insert item I2 for R1 | I2 → R1 v2 (AT-005) |
| 5 | R2 `city` → Curitiba, then → Recife (two commits) | R2 v2, v3 |
| 6 | R3 `average_rating` 4.10 → 4.60 | R3 v2 |
| 7 | Insert item I3 for R4 | I3 → R4 v1 |
| 8 | Delete R4 | R4 v2, `is_deleted`; absent from `silver_restaurants` (AT-003) |
| 9 | Insert item I4 for R4 (restaurant already deleted) | I4 → `no_version_at_event_time` |

Expected result: R1 2 versions, R2 3, R3 2, R4 2 (the last deleted), i.e. changes + 1 for each
restaurant. This covers ≥ 3 restaurants updated and ≥ 1 deleted (REQ-07).

**Rationale:** the fixture is deterministic, independent of the load and checkable without access
to Postgres.

**Alternatives Rejected:**
1. Reuse seeded restaurants. Rejected: unknown prior versions and `restaurant_id` collisions (F9).
2. SQL file run with `psql`. Rejected: it cannot refuse a second run or space the commits reliably.

**Consequences:**
- Step 9 inserts an item for a restaurant that no longer exists. That works because `scripts/init.sql`
  declares no foreign keys (checked 2026-11-23).

---

## Requirement coverage

| REQ | Design element | AT |
|-----|----------------|-----|
| REQ-01 | `scd2` branch of `resolve_cdc` + `strategy` argument (Decisions 1, 3); compiled SQL of the other strategies unchanged (T1) | AT-001, AT-002, AT-003 |
| REQ-02 | `silver_restaurants_events` (view) + `silver_restaurants_history` (Decision 2) | AT-001 |
| REQ-03 | `silver_restaurants` unchanged + `assert_restaurants_history_reconciles_current` (Decision 4) | AT-004 |
| REQ-04 | `silver_restaurants_item_attribution` + `gold_revenue_by_restaurant_version`; `gold_revenue_per_restaurant` untouched (Decisions 5, 6, 7) | AT-005, AT-006 |
| REQ-05 | Enforced contract, explicit `CAST`s (Decision 7) | AT-007 |
| REQ-06 | `assert_restaurants_history_single_current`, `_no_overlap`, `_contiguous` | AT-002 |
| REQ-07 | `tests/fixtures/restaurant_changes.py` + expected CSV + `assert_restaurants_history_fixture_versions` (Decision 10) | AT-001, AT-003 |
| REQ-08 | `docs/adr/0031_scd2_from_the_cdc_event_log.md` (also records the Decision 8 exception) | AT-008 |
| REQ-09 | Deferred, with a trigger (Decision 3) | — |

---

## File Manifest

| # | File | Action | Purpose | Agent | Dependencies |
|---|------|--------|---------|-------|--------------|
| 1 | `dbt/macros/resolve_cdc.sql` | Modify | `strategy` argument; `scd2` branch (Pattern 1); header documents it | Builder | None |
| 2 | `dbt/models/silver/silver_restaurants_events.sql` | Create | Raw projection + horizon (Pattern 2) | Builder | None |
| 3 | `dbt/models/silver/silver_restaurants_history.sql` | Create | `resolve_cdc(..., strategy='scd2')` | Builder | 1, 2 |
| 4 | `dbt/models/silver/silver_restaurants_item_attribution.sql` | Create | Event time + point-in-time join (Pattern 3) | Builder | 3 |
| 5 | `dbt/models/gold/gold_revenue_by_restaurant_version.sql` | Create | Per-version aggregate, explicit `CAST`s | Builder | 4 |
| 6 | `dbt/models/silver/schema.yml` | Modify (shared) | Entries for 2–4: `not_null`/`unique` on keys, `accepted_values` on `attribution_status` | Builder | 2–4 |
| 7 | `dbt/models/gold/schema.yml` | Modify (shared) | Contract for 5 (Decision 7) | Builder | 5 |
| 8 | `dbt/tests/assert_restaurants_history_single_current.sql` | Create | REQ-06 | Builder | 3 |
| 9 | `dbt/tests/assert_restaurants_history_no_overlap.sql` | Create | REQ-06 | Builder | 3 |
| 10 | `dbt/tests/assert_restaurants_history_contiguous.sql` | Create | REQ-06 | Builder | 3 |
| 11 | `dbt/tests/assert_restaurants_history_reconciles_current.sql` | Create | AT-004 | Builder | 3 |
| 12 | `dbt/tests/assert_restaurants_history_fixture_versions.sql` | Create | AT-001/003: if any fixture key exists, every expected version must exist, and nothing else | Builder | 3, 14 |
| 13 | `dbt/tests/assert_restaurants_history_revenue_sum_preserved.sql` | Create | AT-006: totals of 5 = totals of `gold_revenue_per_restaurant` | Builder | 5 |
| 14 | `tests/fixtures/restaurant_changes.py` + `restaurant_changes_expected.csv` | Create | REQ-07 (Decision 10) | Builder | None |
| 15 | `tests/unit/test_restaurant_changes.py` | Create | Plan is deterministic; keys outside generator ranges; refuses a second run (mocked cursor); CSV matches the plan | Builder | 14 |
| 16 | `docs/adr/0031_scd2_from_the_cdc_event_log.md` | Create (shared dir) | REQ-08 | Author (Christian), drafted by Builder | 1–13 |
| 17 | `docs/adr/README.md` | Modify (shared) | Index entry | Builder | 16 |
| 18 | `README.md` | Modify (shared, after COST_GOVERNANCE item 22) | Short SCD2 section + note that measured costs exclude SCD2 (Decision 9) | Author | 5, 16 |

**Total files:** 19 (18 rows; row 14 is two files). `dbt/dbt_project.yml` is **not** changed: the
SCD2 models get their materializations in their own `config()` blocks, and Silver/Gold defaults
already apply.

---

## File Ownership & Parallelism

| Path | Access | Notes |
|------|--------|-------|
| `dbt/macros/resolve_cdc.sql` | Owns | |
| `dbt/models/silver/silver_restaurants*.sql` | Owns | `silver_restaurants.sql` itself is **not** modified (Decision 4) |
| `dbt/models/gold/gold_revenue_by_restaurant_version.sql` | Owns | |
| `dbt/tests/assert_restaurants_history_*.sql` | Owns | |
| `tests/fixtures/restaurant_changes.*` | Owns | |
| `tests/unit/test_restaurant_changes.py` | Owns | **New** in `_index.md` |
| `.claude/sdd/features/SCD2_RESTAURANTS/sim_scd2.py` | Owns | Design simulation (below) |
| `dbt/models/silver/schema.yml`, `dbt/models/gold/schema.yml` | Shared — serialize | COST_GOVERNANCE does not touch dbt (its Decision 3); FT-01 might |
| `docs/adr/`, `README.md` | Shared — serialize | README after COST_GOVERNANCE item 22 |
| `dbt/models/bronze/**`, `dbt/models/config/sources.yml`, `silver_order_items.sql`, `gold_revenue_per_restaurant.sql`, `silver_restaurants.sql` | Reads | |
| `tests/load/generate_load.py` | Reads | Key ranges (F9) |
| `dagster/pipeline/assets.py`, `sensors.py` | Reads | F8; not changed (Decision 8) |

No intersection with COST_GOVERNANCE's owned paths.

---

## Agent Assignment Rationale

No `.claude/agents/` directory exists in this repository.

| Role | Files | Why |
|------|-------|-----|
| Builder (Claude Code) | 1–15, 17 | dbt + SQL; loads this DESIGN, the `resolve_cdc` header, ADR-0025, F4/F7 sources |
| Author (Christian) | 16, 18 | ADR and README carry the portfolio's voice |
| Validator (fresh session) | VALIDATION | DEFINE, fixture, test SQL only (DEFINE *Build Skills*) |

---

## Code Patterns (sketches — not production code)

### Pattern 1: `scd2` branch of `resolve_cdc` (sketch)

```sql
{# signature: resolve_cdc(source_ref, model_name=none, strategy=none) #}
{% set strategy = strategy or cfg.get('cdc_strategy', 'upsert') %}
...
{% elif strategy == 'scd2' %}
    WITH dedup AS (
        SELECT *
        FROM {{ source_ref }}
        WHERE {{ id_col }} IS NOT NULL
        QUALIFY ROW_NUMBER() OVER (
            PARTITION BY {{ id_col }}, kafka_partition, kafka_offset, source_ts_ms
            ORDER BY kafka_created_at
        ) = 1
    ),
    versioned AS (
        SELECT
            *,
            ROW_NUMBER() OVER w                              AS version_number,
            TO_TIMESTAMP_NTZ(source_ts_ms, 3)                AS valid_from,
            TO_TIMESTAMP_NTZ(LEAD(source_ts_ms) OVER w, 3)   AS valid_to,
            op IS NOT DISTINCT FROM 'd'                      AS is_deleted
        FROM dedup
        WINDOW w AS (PARTITION BY {{ id_col }} ORDER BY source_ts_ms, kafka_offset)
    )
    SELECT *, (valid_to IS NULL AND NOT is_deleted) AS is_current
    FROM versioned
```

`valid_to` of the last version is NULL, so a closing delete version is `is_current = FALSE` with
`valid_to` NULL. Snowflake supports the named `WINDOW` clause; if the Build finds otherwise, it
repeats the `OVER (...)` inline.

### Pattern 2: `silver_restaurants_events` header and horizon (sketch)

```sql
{{ config(materialized = 'view', schema = 'SILVER') }}
-- 'view', not Silver's 'table': this is a projection of the raw landing table into
-- resolve_cdc's input contract, kept as a view so it costs nothing to build and an auditor
-- can read the event log. It is NOT deduplicated by key (bronze_restaurants is). See
-- DESIGN_SCD2_RESTAURANTS Decision 2.
SELECT
    UUID AS uuid, RESTAURANT_ID AS restaurant_id, ...,          -- same list as bronze_restaurants
    __OP AS op, __SOURCE_TS_MS AS source_ts_ms,
    RECORD_METADATA:offset::BIGINT AS kafka_offset,
    RECORD_METADATA:partition::INT AS kafka_partition,
    RECORD_METADATA:CreateTime::BIGINT AS kafka_created_at
FROM {{ source('bronze_raw', 'RESTAURANTS') }}
WHERE UUID IS NOT NULL
  AND RECORD_METADATA:CreateTime::BIGINT <= (
      SELECT COALESCE(MAX(kafka_created_at), 0) FROM {{ ref('bronze_restaurants') }})
```

### Pattern 3: Point-in-time attribution (sketch)

```sql
WITH items AS (
    SELECT s.order_item_id, s.order_id, s.restaurant_id, s.quantity, s.subtotal, s.discount_applied,
           f.item_event_ts
    FROM {{ ref('silver_order_items') }} s
    JOIN (SELECT ORDER_ITEM_ID AS order_item_id,
                 TO_TIMESTAMP_NTZ(MIN(__SOURCE_TS_MS), 3) AS item_event_ts
          FROM {{ source('bronze_raw', 'ORDER_ITEMS') }}
          WHERE ORDER_ITEM_ID IS NOT NULL GROUP BY 1) f USING (order_item_id)
    WHERE s.restaurant_id IS NOT NULL
),
candidates AS (
    SELECT i.order_item_id, h.uuid, h.version_number, h.valid_from, h.kafka_offset,
           COUNT(*) OVER (PARTITION BY i.order_item_id) AS candidate_count
    FROM items i
    JOIN {{ ref('silver_restaurants_history') }} h
      ON  h.restaurant_id = i.restaurant_id
      AND NOT h.is_deleted
      AND i.item_event_ts >= IFF(h.version_number = 1 AND h.op = 'r',
                                 '1900-01-01'::TIMESTAMP_NTZ, h.valid_from)
      AND i.item_event_ts <  COALESCE(h.valid_to, '9999-12-31'::TIMESTAMP_NTZ)
    QUALIFY ROW_NUMBER() OVER (PARTITION BY i.order_item_id
                               ORDER BY h.valid_from DESC, h.kafka_offset DESC) = 1
)
SELECT i.*, c.uuid AS restaurant_uuid, c.version_number, COALESCE(c.candidate_count, 0) AS candidate_count,
       CASE ... END AS attribution_status          -- the five statuses of Decision 6
FROM items i LEFT JOIN candidates c USING (order_item_id)
```

---

## Simulation of the decision logic

`sim_scd2.py` in this folder implements Patterns 1 and 3, plus the `upsert` reconciliation, in
sqlite window functions over a synthetic event set. The set covers:
- a redelivered duplicate and a same-millisecond tie;
- a tombstone and a PK-only delete;
- items snapshotted before their restaurant;
- two `uuid`s sharing a `restaurant_id`;
- an unregistered `restaurant_id`, an item after a delete, and an event beyond the horizon.

Run it with `python3 -I .claude/sdd/features/SCD2_RESTAURANTS/sim_scd2.py`.

| Run | Result |
|-----|--------|
| First draft (backfill on **every** first version) | REQ-06, reconciliation and sum checks passed, but item `i6` (sold at t=2000) was attributed to restaurant D, **created at t=2500**, as `ambiguous_resolved`. Wrong attribution. |
| After fix (backfill only when `version_number = 1 AND op = 'r'`) | All 16 checks pass: one current per key, no overlaps, contiguous; duplicate collapsed (A = 3 versions); delete closes B; tombstone and post-horizon event excluded; history ≡ current state; one row per item; AT-005 holds; first event time used; `before_first_capture`, `no_version_at_event_time`, `ambiguous_resolved` and `unregistered` each assigned where expected; sum preserved. |

Limits: sqlite is not Snowflake (`QUALIFY`, `IFF`, `TO_TIMESTAMP_NTZ` and `IS NOT DISTINCT FROM`
differ), so the simulation pins the **logic**, not the SQL dialect. The dialect is checked by the
Day 12 build.

---

## Data Flow

```text
1. Fixture (Day 12) commits 4 inserts, 4 updates, 1 delete and 4 items in Postgres, one commit per step
   │
   ▼
2. Debezium → Kafka → Snowpipe Streaming append to raw RESTAURANTS / ORDER_ITEMS
   │
   ▼
3. Gated Dagster run: dbt run bronze silver gold
   bronze_restaurants (merge) → silver_restaurants_events (view, horizon) → silver_restaurants_history
   → silver_restaurants_item_attribution → gold_revenue_by_restaurant_version
   │
   ▼
4. dbt test: schema tests + 6 singular tests (warn in the pipeline, error with scd2_strict)
```

---

## Integration Points

| External System | Integration Type | Authentication |
|-----------------|-----------------|----------------|
| Postgres (dev, docker compose) | `psycopg2` from the fixture | `POSTGRES_*` from the environment (never printed, R3) |
| Snowflake `CDC_POC` | dbt (`CDC_ROLE`, `CDC_WH`) | Key pair from `SNOWFLAKE_PRIVATE_KEY_PATH` (existing profile) |

---

## Testing Strategy

| # | Test | Scope | Files | Tools | When |
|---|------|-------|-------|-------|------|
| T1 | Other strategies unchanged | Compiled SQL of the 10 existing Silver models identical before/after item 1 | `target/compiled/` diff | `dbt compile` (needs a connection) — Day 12; `dbt parse` in CI before that | Day 12 |
| T2 | Fixture plan | Determinism, key ranges, refuse re-run, CSV = plan | `tests/unit/test_restaurant_changes.py` | `pytest` | CI, every PR |
| T3 | Logic | Patterns 1 and 3 | `sim_scd2.py` | Python/sqlite | Design + Build |
| T4 | History shape | REQ-06 | tests 8–10 | dbt | Day 12, then every run |
| T5 | Reconciliation, fixture counts, sum | AT-004, AT-001/003, AT-006 | tests 11–13 | dbt, `scd2_strict` | Day 12 (twice), Validation |
| T6 | Contract | AT-007 | manual `CAST` change | `dbt build` | Day 12, Validation |
| T7 | Determinism | Full rebuild twice, `HASH_AGG(*)` of history and Gold equal | ad hoc query in BUILD_REPORT | Snowflake | Day 12 |

---

## Error Handling

| Error Type | Handling Strategy | Retry? |
|------------|-------------------|--------|
| Fixture keys already present | Exit 2, message, no write | No |
| Fixture step fails mid-way | That step's transaction rolls back; exit 1. Re-running is refused (keys exist), so recovery is manual and documented in the script's docstring | No |
| SCD2 test fails in the pipeline | `warn`: logged, the run succeeds (Decision 8) | No |
| Contract mismatch | `dbt build` fails on the Gold model | No — fix the SQL |
| Unknown strategy string | Compiler error listing `upsert | append | log | scd2` | No |

---

## Configuration

| Config Key | Type | Default | Description |
|------------|------|---------|-------------|
| `scd2_strict` (dbt var) | bool | `false` | `true` makes the SCD2 singular tests `error` (Build, Validation) |
| `POSTGRES_*` (env) | string | — | Fixture connection, same variables as `tests/load` |

---

## Security Considerations

- Restaurant data is business data, not personal data. `phone_number` is a business line, and the
  fixture's is synthetic (D1). SCD2 on **users** stays out of scope (DEFINE; Constitution D3).
- The history keeps every past value forever, by design. If a restaurant column ever becomes
  personal data, the purge mechanism has to cover this table too. ADR-0031 records this.
- No new role, grant or credential. The fixture reads its connection from the environment.

---

## Observability

| Aspect | Implementation |
|--------|----------------|
| Logging | Fixture prints each step with its commit time (no credentials) |
| Metrics | Day 12 BUILD_REPORT: rows and build time for the four models, and the credits of the first build from `QUERY_HISTORY` by tag/model (Decision 9's separate README line) |
| Data | `attribution_status` counts in Gold make attribution gaps visible without a query on Silver |

---

## Risks

| # | Risk | Likelihood | Mitigation |
|---|------|------------|------------|
| R1 | dbt-snowflake 1.7 contract type comparison stricter or looser than expected (F7) | Medium | Explicit `CAST`s; Day 12 build settles types before Validation |
| R2 | Delete rows carry non-NULL defaults instead of NULLs (F4 unverified part) | Low | Decision 6 excludes `is_deleted` rows from the join regardless of their values |
| R3 | Snapshot `ts_ms` semantics differ from the docs' reading (F6) | Low | Backfill rule tolerates both orders (simulation `i0`) |
| R4 | Bronze watermark skips a late-landing row, so AT-004 fails | Low | Real Bronze defect; investigate with the event view; `warn` in the pipeline (Decision 8) |
| R5 | Re-snapshot in dev creates duplicate `op = 'r'` versions | Medium in dev | A-001 query on Day 12; REQ-09 trigger (Decision 3) |
| R6 | Plan slip: Day 12 build finds dialect issues, Validation slips to Day 14 | Medium | Simulation pins logic; Day 15 is buffer |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-11-23 | design-agent (Claude Code) | Initial version. F1 (no history in dbt Bronze) redirected the source to the raw table; the simulation found and fixed a backfill bug (Decision 6). Decisions 8 and 9 need owner review. |
| 1.0.1 | 2026-11-23 | Christian (with Claude) | Owner approved Decisions 8 and 9; `_index.md` 15-day plan updated for Decision 9. No design change. |

---

## Next Step

**Ready for:** an independent review in a **new chat**: `/sdd-review SCD2_RESTAURANTS`.
Build only after the review is recorded in this table, and only as Decision 9 allows (offline until
2026-11-29).
