# Measurement protocol — v2 configuration (A) vs v3 configuration (B)

COST_GOVERNANCE, manifest item 15 · REQ-06, REQ-07 · AT-007, AT-008 · DESIGN 1.4, *Measurement plan*,
Decisions 2, 5, 6, 7, 13.

> Draft written by the build agent on 2026-11-23 with the owner's defaults, for the owner to edit.
> It was fixed **before** any measurement ran. Changing it after a window has started is allowed
> only if the change is recorded in §9, with the reason and the window it affects.

This protocol states what is measured, under which load, in which windows, what makes a window
void, and how the numbers are read. It does not state the expected result. The predictions are
in the DESIGN and are copied unchanged into [`RESULTS_TEMPLATE.md`](RESULTS_TEMPLATE.md), so they
cannot be adjusted after the fact.

## 1. What is measured

| Metric | Definition | Source | Query |
|--------|------------|--------|-------|
| **Total cost** (H1) | `CDC_WH` compute credits + serverless task credits in `CDC_POC`, per UTC day | `WAREHOUSE_METERING_HISTORY`, `SERVERLESS_TASK_HISTORY` | Q1 + Q2 |
| **Resumes** (H2) | `RESUME_WAREHOUSE` events of `CDC_WH`, per UTC day | `WAREHOUSE_EVENTS_HISTORY` | Q4 |
| **Freshness** (guardrail) | Per burst: Gold `FINISHED_AT` of the run that consumed it − source commit (Decision 7); p95 per window | `commits.csv`, `CONFIG.PENDING_RUNS`, `CONFIG.PROCESSING_LOG` | Q6 |
| **Idle property** | Over the 6 h idle window: 0 `CDC_WH` credits, < 0.01 serverless task credits, only skipped gate evaluations | as above + `TASK_HISTORY` | Q1, Q2, Q7 |
| Cloud services, Snowpipe Streaming, budget | Reported apart, **not** part of total cost | `METERING_DAILY_HISTORY` | Q3 |
| Attribution | Estimated split of the saving into Gen1 / gate tasks / batching | see [`ATTRIBUTION.md`](ATTRIBUTION.md) | Q8 |

H1: total credits/day of B ≤ 75% of A. H2: resumes/day of B ≤ 50% of A. Freshness guardrail:
p95 ≤ *N* + 5 = **15 min** in B. All are from the DEFINE, *Success Criteria*. A failed
hypothesis ships with its number.

## 2. Windows

All times in UTC. Vitória = UTC − 3.

| Window | Start (UTC) | End (UTC) | Vitória | Profile | `BATCH_WINDOW_MINUTES` | Load |
|--------|-------------|-----------|---------|---------|------------------------|------|
| Dry run A | 2026-11-24 12:00 | 2026-11-24 15:00 | 09:00–12:00 | `baseline` | 0 | on |
| Dry run B | 2026-11-24 15:00 | 2026-11-24 18:00 | 12:00–15:00 | `optimized` | 10 | on |
| **A** | **2026-11-25 00:00** | **2026-11-27 00:00** | 24/11 21:00 – 26/11 21:00 | `baseline` | 0 | on |
| **B** | **2026-11-27 00:00** | **2026-11-29 00:00** | 26/11 21:00 – 28/11 21:00 | `optimized` | 10 | on |
| **Idle** | 2026-11-29 00:00 | 2026-11-29 06:00 | 28/11 21:00 – 29/11 03:00 | `optimized` | 10 | **off** |
| Read results | ≥ 2026-11-29 10:00 | — | ≥ 07:00 | — | — | — |

The dry run measures what the DESIGN leaves open (§7). Its numbers are not part of the A/B.

## 3. Load

Generator: `tests/load/generate_load.py` (item 14). One cluster every 120 min starting at :30,
with bursts at offsets 0, 2, 4, 10 and 12 min and 200 rows per burst, seed 42. The defaults are
`LOAD_SEED=42`, `LOAD_CLUSTER_MINUTES=120`, `LOAD_BURST_OFFSETS=0,2,4,10,12`,
`LOAD_ROWS_PER_BURST=200`. They must be **identical** in A and B; set none of them unless the
dry run recalibrates them, and in that case record the change in §9 before A.

One process per window, started before the window and running until `--end`:

```bash
# check the plan first (touches no database)
python3 tests/load/generate_load.py --window A \
    --start 2026-11-25T00:00Z --end 2026-11-27T00:00Z --out docs/measurement/runs/A --plan-only
# then run it for real (same arguments without --plan-only)
```

| Window | `--window` | `--start` | `--end` | `--out` |
|--------|-----------|-----------|---------|---------|
| Dry run | `dry-run` | `2026-11-24T12:00Z` | `2026-11-24T18:00Z` | `docs/measurement/runs/dry-run` |
| A | `A` | `2026-11-25T00:00Z` | `2026-11-27T00:00Z` | `docs/measurement/runs/A` |
| B | `B` | `2026-11-27T00:00Z` | `2026-11-29T00:00Z` | `docs/measurement/runs/B` |

There is no generator during the idle window. The B process exits at 00:00 on its own.

The generator writes these files to `--out`:
- `commits.csv`: `burst_id, committed_at_utc, rows, source`.
- `skipped.csv`: bursts more than 60 s late, which are never run late.
- `task_states.csv`: the gate-task check at start-up and 20 min after each cluster, with a
  cumulative `window_valid` column.

Exit codes: `0` valid · `1` window not valid (a skip, or a task not `started`) · `3` the task
check does not see exactly ten gate tasks, in which case it stops before the first burst.

A crash is restarted with the **same command**. Bursts already in `commits.csv` are not re-run;
a burst committed but not logged is recovered and never replayed (item 14). Prerequisites
(BUILD_REPORT O35, O38): the machine or VM, `psycopg2-binary`, `snowflake-connector-python`,
`cryptography`, and the `CDC_ROLE_RO` key-pair user.

## 4. Profile switch

A profile is two settings that change together. Anything else changing is a validity breach.

| Setting | Where | Changed by |
|---------|-------|-----------|
| `cost_profile` | `terraform/env/dev.tfvars` | One-line PR, merged and apply-approved through CI (Decision 2) |
| `BATCH_WINDOW_MINUTES` | local `.env` read by `dagster` and `dagster-daemon` (`env_file`) | Edit `.env`, then `docker compose up -d --force-recreate dagster dagster-daemon` |

Switches:

| # | When (UTC) | To | PR also carries |
|---|------------|----|-----------------|
| S0 | before 2026-11-24 12:00 | `baseline`, N = 0 | — |
| S1 | 2026-11-24 15:00 | `optimized`, N = 10 | — |
| S2 | **2026-11-25 00:00** | `baseline`, N = 0 | dry-run recalibrations, if any (§7) |
| S3 | **2026-11-27 00:00** | `optimized`, N = 10 | `gate_task_timeout_ms` from the dry run (O21), since only profile B applies it |

Steps for each switch. Prepare the PR in advance. Never apply locally (Constitution R1).
1. At the switch time, merge the prepared PR and approve `apply (main)` in the `snowflake-dev`
   environment.
2. In the same minute, set `BATCH_WINDOW_MINUTES` in `.env` and recreate both Dagster containers.
3. Wait for the apply job to finish. It must show a clean second plan for **both roots**
   (`platform`, `pipeline`), followed by a successful `verify_governance.sql`. A switch that
   applied only one root voids the window (B1).
4. Append one line per step to `docs/measurement/runs/switch.log`, all times in UTC:

```text
at_utc,switch,step,ref
2026-11-25T00:00:40Z,S2,pr_merged,#NN
2026-11-25T00:01:10Z,S2,dagster_recreated,BATCH_WINDOW_MINUTES=0
2026-11-25T00:03:05Z,S2,apply_approved,run 1234567890
2026-11-25T00:09:30Z,S2,verify_ok,run 1234567890
```

The minutes between the window start and `verify_ok` ran in the previous profile. They are
reported in RESULTS, never hidden. The apply must finish **within 30 min** of the window start
(the first cluster starts at :30). Otherwise the window is void.

Known effect (O32): the first B run after S3 can be held for up to *N* by `last_run_at`, which
the sensor cursor carries over from profile A. It is reported, not corrected.

## 5. Validity rules and reruns

A window is **void** if any of these happens inside it:

1. Someone uses `CDC_WH` by hand. Ad-hoc work goes to `COMPUTE_WH`, and the CI SQL steps run on
   `CDC_CI_WH`. Both are excluded from the analysis. This includes running these queries on
   `CDC_WH` while the window is open.
2. `commits.csv` has a gap of more than one cluster, for example because the machine slept.
3. `task_states.csv` has `window_valid = false`: a gate task was not `started` at a check.
4. The switch missed the 30-minute limit, or applied only one root (§4).
5. Any change to Terraform, `.env`, the generator or Dagster code reaches the stack, other than
   the switch PR itself.

Results are reported **per cluster** as well as per UTC day (Q5). A window with one missing
cluster stays comparable; Q5 shows it.

These are reported but **do not void** a window: skipped bursts (they appear in
`commits.csv`/`skipped.csv` and are counted); failed dbt runs and the Decision 7 residual case
(they show up as freshness gaps); minutes in the wrong profile after a switch.

**Rerun policy (B5).**
- Each void window (A or B) may be rerun **once**, as a whole 48 h window starting at the next
  00:00 UTC after the void is noticed, with the same load and the same profile.
- **Last start for a rerun: 2026-11-29 00:00 UTC.** In that case the idle window moves to
  directly after the rerun, and reading moves to ≥ 2026-12-01 10:00 UTC. That still leaves
  Day 15 (2026-12-02). After that date nothing is rerun: the void window is reported as void, and
  the A/B is reported from whatever valid data exists, per cluster.
- If the dry run is void, it is not rerun. Its §7 checks are re-read from the first hours of A.
- **If the rerun needs more credits**, raise `cdc_wh_monitor_quota` in `terraform/env/dev.tfvars`
  by a PR through CI, before the rerun starts. Keep the Decision 8 rule: the worst case
  must stay under ~50% of the trial balance. Never raise it with `ALTER RESOURCE MONITOR` by hand.
- A rerun also extends the SCD2_RESTAURANTS embargo (its DESIGN Decision 9: nothing SCD2 on the
  account until B ends). Tell that feature's owner the new end date.
- Edit the `SET` window block in `queries.sql` to the rerun's dates, and record the rerun in §9.

## 6. Reading the results

- **When:** ≥ 2026-11-29 10:00 UTC. `WAREHOUSE_EVENTS_HISTORY` and `METERING_DAILY_HISTORY`
  have up to 3 h of latency. The dry run is read on the evening of 2026-11-24, before 00:00 UTC.
- **Where:** Snowsight, `docs/measurement/queries.sql` top to bottom. Role `CDC_GOVERNANCE_RO`;
  Q6 and Q0.2 switch to `CDC_ROLE_RO` themselves. Warehouse `CDC_WH`, **only outside the windows**
  (rule 1).
- **Freshness input (Q6):** turn each window's `commits.csv` into the `VALUES` rows and paste them
  over the example rows in Q6:

```bash
awk -F, -v q="'" 'NR>1 {printf "%s(%s%s%s, %s%s%s::TIMESTAMP_NTZ, %s)\n", (NR>2 ? "," : " "), q,$1,q, q,$2,q, $3}' \
    docs/measurement/runs/B/commits.csv
```

- **Output:** save each query's result as CSV in `docs/measurement/runs/<window>/`. Use
  `q1_warehouse_credits.csv`, `q2_serverless_credits.csv`, `q3_metering_daily.csv`, `q4_resumes.csv`,
  `q4b_billed_seconds.csv`, `q5_per_cluster.csv`, `q6_freshness.csv` (plus the per-burst
  `freshness.csv`), `q7_idle_tasks.csv`, `q8a_rates.csv`, `q8b_task_only.csv`. Account-wide queries
  go to `runs/final/`. Then fill `RESULTS.md` from [`RESULTS_TEMPLATE.md`](RESULTS_TEMPLATE.md).
- The Validator (fresh session, AT-008) re-runs the same queries and must get the same numbers.

## 7. Dry-run checklist (2026-11-24)

Each item has a place where its answer is written. Record the answers in §9 and in the
BUILD_REPORT before S2.

| # | Question | How | Writes to |
|---|----------|-----|-----------|
| D1 | Which time zone is `PENDING_RUNS.DETECTED_AT` stored in? | Q0.1 + Q0.2 after a cluster | `SET detected_at_tz` in `queries.sql` |
| D2 | Does one resume give exactly one `RESUME_WAREHOUSE` row, and does every resume pair with a `SUSPEND_WAREHOUSE`? | Q4, Q4b (`unpaired = 0`) | Q4 comment |
| D3 | Does the pairing method hold? Dry run B's `credits_per_hour` ≈ 1.0 (Gen1) | Q8a on the dry-run windows | ATTRIBUTION §3 |
| D4 | Which `QUERY_HISTORY.user_name` do task-run queries have? | Profile A part: `QUERY_HISTORY` rows of the gate procedure's `INSERT`s | `SET task_user` |
| D5 | Gate-task timeout: p99 of serverless gate runs in `TASK_HISTORY`; set max(10 s, 5 × p99) (O21) | `TASK_HISTORY`, dry run B | S3 PR (`gate_task_timeout_ms`) |
| D6 | Gap between the sensor's `SELECT` and the job's first query. More than 60 s means two resumes per run (validity note) | Dagster run start vs `QUERY_HISTORY` | RESULTS caveats |
| D7 | Is `QUIET_CYCLES = 3` enough? Kafka activity → Bronze commit → gate tick, end to end | `commits.csv` vs `STREAM_CONSUMPTION_LOG.CONSUMED_AT` | §9; a change goes into the S2 PR |
| D8 | Where does the nominal `WHEN` charge appear (F3), and what does the `TIER_1H` budget refresh cost (O13)? | Q2, Q3 for 2026-11-24 | RESULTS, *Reported apart* |
| D9 | Does `CDC_ROLE_RO`'s task check resume `CDC_WH`? (O36) | `WAREHOUSE_EVENTS_HISTORY` around each check time | O36 |
| D10 | Does the switch move tasks warehouse ↔ serverless with a clean second plan, and does profile A read back `STANDARD_GEN_2`? (O20, O17) | S0/S1 apply jobs, `verify_governance.sql` | BUILD_REPORT |
| D11 | How often does the Decision 7 residual case happen? (O33) | `PENDING_RUNS` keys with no `PROCESSING_LOG` row | RESULTS caveats |
| D12 | Does dry-run A + B match the size estimate (~1 credit)? | Q1, Q2 | §9; lower the load in S2 if it is far above |

## 8. What is committed

Everything in `docs/measurement/runs/`: CSVs from the generator, `switch.log`, the query output
CSVs and `RESULTS.md`. Nothing in them is secret or personal: the load is synthetic (Constitution
D1), and no credential, key path or e-mail goes in a file. After the trial (2026-12-17) these files
are the only record of the result. `docs/runbooks/after-trial.md` (item 19) explains how to
redeploy and rerun the protocol on another account.

## 9. Change log of this protocol

| Date (UTC) | Change | Reason | Windows affected |
|------------|--------|--------|------------------|
| 2026-11-23 | First version, before the dry run | — | — |
