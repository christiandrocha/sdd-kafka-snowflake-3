# DEFINE: SCD Type 2 for Restaurants — reference case (SCD2_RESTAURANTS)

> Keep the full history of each restaurant, derived from the CDC event log already stored in
> Bronze, and prove it matters with a Gold model that attributes each sale to the restaurant as
> it was at the time.

## Metadata

| Attribute | Value |
|-----------|-------|
| **Feature** | SCD2_RESTAURANTS |
| **Date** | 2026-11-17 |
| **Author** | Christian (with Claude) |
| **Status** | Approved — in Design (DESIGN 1.0.1, awaiting independent review) |
| **Clarity Score** | 13/15 |
| **Approved by** | Christian, 2026-11-17 |

---

## Problem Statement

`silver_restaurants` keeps only the current state of each restaurant (`upsert` strategy in
`resolve_cdc`). `gold_revenue_per_restaurant` aggregates **all historical sales** against that
current state, so when a restaurant changes city, cuisine or rating, its past revenue is silently
re-labelled with today's attributes. Nobody can answer "what did this restaurant look like when
this sale happened", or "when did it leave the platform". The information is not lost: Bronze is
append-only (ADR-0025) and keeps every CDC event with `op`, `source_ts_ms` and `kafka_offset`.
It is just never modelled.

This is a **single reference case by design**: one domain, one Gold consumer, one ADR that any
other domain can follow when a business need appears.

---

## Target Users

| User | Role | Pain point |
|------|------|------------|
| Analyst | Reads Gold | Revenue by attribute (city, cuisine) is wrong for any restaurant that changed |
| Auditor / client | Needs traceability | Cannot reconstruct a restaurant's state at a past date |
| Reviewer / hiring manager | Reads the repo | Wants to see SCD2 done from CDC, with tests that prove it |

---

## Goals

| Priority | Goal |
|----------|------|
| **MUST** | Full version history of restaurants, rebuilt deterministically from Bronze |
| **MUST** | No change for existing consumers of `silver_restaurants` |
| **MUST** | A Gold model that uses the history (point-in-time attribution), with an enforced contract |
| **MUST** | Tests that prove the history is well-formed and agrees with the current state |
| **COULD** | Collapse versions that differ only in untracked columns |

---

## Requirements

| ID | Requirement | Priority | Verified by |
|----|-------------|----------|-------------|
| REQ-01 | `resolve_cdc` gains a fourth strategy, `scd2`, alongside `upsert`, `append` and `log`, without changing the behaviour of the other three. Output: one row per CDC event per key, with `valid_from`, `valid_to` (NULL = open), `is_current`, `is_deleted`. Ordering uses the existing tie-break (`source_ts_ms`, then `kafka_offset`), ascending. Tombstones (null key) are excluded; a delete event closes the history (`is_deleted = TRUE`, not current). | MUST | AT-001, AT-002, AT-003 |
| REQ-02 | New model `silver_restaurants_history`, versioned by the CDC key (`uuid`), using the `scd2` strategy. | MUST | AT-001 |
| REQ-03 | `silver_restaurants` keeps its current columns and grain (one row per `uuid`, deleted rows absent). Whether it becomes a view over the history or stays an `upsert` table is a DESIGN decision; either way a test proves the two agree. | MUST | AT-004 |
| REQ-04 | New model `gold_revenue_by_restaurant_version`: each order item is attributed to the restaurant version valid at the item's event time. `gold_revenue_per_restaurant` stays unchanged. | MUST | AT-005, AT-006 |
| REQ-05 | The new Gold model has an **enforced dbt model contract** (named, typed columns), as the repo's reference data contract. | MUST | AT-007 |
| REQ-06 | Tests on the history: at most one `is_current` row per key; no overlapping intervals per key; consecutive versions are contiguous (`valid_to` = next `valid_from`). | MUST | AT-002 |
| REQ-07 | A deterministic fixture issues known changes to restaurants in Postgres (attribute updates on ≥ 3 restaurants, ≥ 1 delete) and the changes travel the full CDC path. | MUST | AT-001, AT-003 |
| REQ-08 | ADR: "SCD2 derived from the CDC event log, not from dbt snapshots — applied to one domain as the reference". | MUST | AT-008 |
| REQ-09 | Versions whose tracked columns hash identically to the previous version are collapsed. | COULD | — |

---

## Success Criteria

- [ ] For the fixture, every changed restaurant has exactly (number of applied changes + 1)
      versions in `silver_restaurants_history`, and the deleted one ends with `is_deleted = TRUE`.
- [ ] 100% of order items in `gold_revenue_by_restaurant_version` match exactly one restaurant
      version, or carry an explicit `unmatched` flag. Zero items match two versions.
- [ ] Total revenue in `gold_revenue_by_restaurant_version` equals total revenue in
      `gold_revenue_per_restaurant`: history changes **attribution**, never the sum.
- [ ] The three history tests (REQ-06) and the reconciliation test (REQ-03) pass on a full
      rebuild, run twice with identical results (determinism).

---

## Acceptance Tests

| ID | Scenario | Given | When | Then |
|----|----------|-------|------|------|
| AT-001 | History is built | Fixture applied (≥ 3 restaurants updated) | `dbt build -s +silver_restaurants_history` | Each updated restaurant has one row per version, ordered, with correct `valid_from` |
| AT-002 | Well-formed intervals | History built | Tests run | One current row per key; no overlaps; contiguous intervals |
| AT-003 | Delete closes the history | Fixture deletes one restaurant | Build | Its last row has `is_deleted = TRUE`, `is_current = FALSE`; it is absent from `silver_restaurants` |
| AT-004 | Current state unchanged | History built | Reconciliation test | `history WHERE is_current` ≡ `silver_restaurants` (same keys, same values) |
| AT-005 | Point-in-time attribution | A restaurant changes `cuisine_type` between two of its sales | Build Gold | The two sales are attributed to different versions |
| AT-006 | Sum preserved | Gold built | Compare totals | New and existing Gold revenue totals are equal |
| AT-007 | Contract enforced | A column type in the new Gold model is changed in SQL | `dbt build` | Build fails on the contract |
| AT-008 | Decision recorded | Feature shipped | Read `docs/adr/` | ADR explains event-log SCD2 vs snapshots, and why only one domain |

---

## File Ownership (preliminary)

| Path | Access |
|------|--------|
| `dbt/macros/resolve_cdc.sql` | Owns |
| `dbt/models/silver/silver_restaurants.sql`, `silver_restaurants_history.sql` | Owns |
| `dbt/models/gold/gold_revenue_by_restaurant_version.sql` | Owns |
| `tests/fixtures/restaurant_changes.*`, `dbt/tests/assert_restaurants_history_*.sql` | Owns |
| `dbt/models/silver/schema.yml`, `dbt/models/gold/schema.yml`, `dbt/dbt_project.yml` | Shared — serialize |
| `README.md`, `CLAUDE.md`, `docs/adr/` | Shared — serialize |
| `dbt/models/bronze/**`, `dbt/models/silver/silver_order_items.sql`, `gold_revenue_per_restaurant.sql` | Reads |

## Build Skills / Context

| Agent role | Loads |
|------------|-------|
| Builder | v2 `resolve_cdc.sql` (full header — the tie-break and tombstone history matter), `silver_restaurants.sql`, `gold_revenue_per_restaurant.sql` header, ADR-0025; dbt docs on model contracts |
| Validator | This DEFINE, the fixture, the test SQL. No DESIGN, no build context. |

---

## Out of Scope

- SCD2 on any other domain. In particular **not on users**: version history of personal data
  conflicts with a future purge requirement (Constitution D3).
- dbt snapshots (rejected in the ADR, REQ-08).
- Incremental materialization of the history — full rebuild from Bronze is deterministic and,
  per v2's measurements, rebuild time is not the cost driver.
- Renaming the Portuguese column names of the existing `gold_revenue_per_restaurant` — that
  model is frozen. New models use English names.

---

## Constraints

| Type | Constraint | Impact |
|------|------------|--------|
| Timeline | ~2 days of Build inside the 15-day plan | One domain, one Gold consumer, REQ-09 cut first |
| Technical | `silver_restaurants` is unique by `uuid`, but items join on `restaurant_id`, which is **not** guaranteed unique (v2 resolves it with a `QUALIFY` in Gold) | The point-in-time join must define behaviour when two `uuid`s share a `restaurant_id` |
| Technical | Order items carry `source_ts_ms` of their **latest** CDC event, not a sale timestamp | The "event time" of an item must be defined in DESIGN (see open question 1) |

---

## Assumptions

| ID | Assumption | If wrong, impact | Validated? |
|----|------------|------------------|------------|
| A-001 | The seeded data has (almost) no restaurant changes, so history only becomes visible through the fixture | Without REQ-07 the feature would demo as empty | [ ] Day 3 — count versions per `uuid` in Bronze |
| A-002 | Debezium emits one event per committed update, so fixture changes map 1:1 to versions | Version counts in the success criteria need adjusting | [ ] Day 5 |
| A-003 | No consumer outside dbt reads `silver_restaurants` | A view replacement (REQ-03) could break it | [ ] Day 3 |

---

## Clarity Score Breakdown

| Element | Score (0-3) | Notes |
|---------|-------------|-------|
| Problem | 3 | Concrete wrong number (re-labelled revenue), concrete missing answer |
| Users | 2 | Analyst/auditor are archetypes until a client exists |
| Goals | 3 | Scoped to one reference case on purpose |
| Success | 3 | Counts, sum preservation, determinism |
| Scope | 2 | Item event time and the `restaurant_id` ambiguity are open for DESIGN |
| **Total** | **13/15** | |

---

## Open Questions

| # | Question | Blocking? | Owner | Default |
|---|----------|-----------|-------|---------|
| 1 | Which timestamp is an item's "event time" for the point-in-time join? | No (DESIGN) | Christian | The item's **first** CDC event in Bronze (`MIN(source_ts_ms)` per `order_item_id`) — the capture time of the sale, not of its last edit |
| 2 | Point-in-time join key: `restaurant_id` (as Gold does today) or resolve to `uuid` first? | No (DESIGN) | Christian | Join on `restaurant_id` within the validity interval; flag items that match more than one version |
| 3 | `silver_restaurants` as a view over the history, or kept as an `upsert` table? | No (DESIGN) | Christian | Keep the table, add the reconciliation test — no contract change for any consumer |
| 4 | Which columns are "tracked" for REQ-09? | No | — | Skip REQ-09 in this version |

---

## Revision History

| Version | Date | Author | Changes |
|---------|------|--------|---------|
| 1.0 | 2026-11-17 | Christian (with Claude) | Initial version |
| 1.1 | 2026-11-17 | Christian | Approved. Scope frozen. |

---

## Next Step

**Ready for:** `/sdd-design SCD2_RESTAURANTS`
