# Results — A/B measurement, COST_GOVERNANCE

<!--
Copy to docs/measurement/runs/RESULTS.md after reading (PROTOCOL §6) and fill every «…».
Leave the "Predictions" section exactly as it is: it was written before measuring
(DESIGN 1.4, Measurement plan) and is the reference the results are compared to.
Every number below links to the CSV it came from in runs/<window>/.
-->

COST_GOVERNANCE · REQ-07 / AT-008 · protocol: [`PROTOCOL.md`](../PROTOCOL.md) · read on «date, UTC»
by «who».

## 1. Windows as run

| Window | Planned (UTC) | As run (UTC) | Valid? | Clusters run / planned | Skipped bursts | Minutes in wrong profile | Notes |
|--------|---------------|--------------|--------|------------------------|----------------|--------------------------|-------|
| A | 2026-11-25 00:00 → 11-27 00:00 | «…» | «yes / void: rule #» | «…» / 24 | «…» | «…» (`switch.log`) | «…» |
| B | 2026-11-27 00:00 → 11-29 00:00 | «…» | «…» | «…» / 24 | «…» | «…» | «…» |
| Idle | 2026-11-29 00:00 → 06:00 | «…» | «…» | — | — | — | «…» |

Reruns: «none / window, dates, reason (PROTOCOL §5)».

## 2. Predictions (written before measuring — do not edit)

| Metric per cluster | A | B | Hypothesis | Predicted outcome |
|--------------------|---|---|------------|-------------------|
| dbt runs | ~5 | 2 | — | — |
| Warehouse resumes | 1–2 | 2 | **H2: B ≤ 50% of A** | **Expected to fail** (B/A between 100% and 200%) |
| Billed warehouse minutes | ~18–20 | ~8 | — | — |
| Credits | ~0.45 (5.4/day) | ~0.13 (1.6/day) | **H1: B ≤ 75% of A** | Expected to pass (~30–40%) |

## 3. Hypotheses

| | A | B | B / A | Threshold | Result |
|--|---|---|-------|-----------|--------|
| **H1** total credits/day (Q1 compute + Q2) | «…» | «…» | «…%» | ≤ 75% | «PASS / FAIL» |
| **H2** resumes/day (Q4) | «…» | «…» | «…%» | ≤ 50% | «PASS / FAIL» |
| **Freshness** p95, min (Q6) — guardrail on B only | «…» (indicative) | «…» | — | ≤ 15 | «PASS / FAIL» |
| **Idle** `CDC_WH` credits (Q1, IDLE) | — | «…» | — | = 0 | «PASS / FAIL» |
| **Idle** serverless credits (Q2, IDLE) | — | «…» | — | < 0.01 | «PASS / FAIL» |
| **Idle** gate evaluations (Q7) | — | «states and counts» | — | only skipped | «PASS / FAIL» |

One sentence per failed hypothesis: what the number says, and why (no reinterpretation of the
threshold).

## 4. Per UTC day (Q1, Q2, Q4)

| UTC day | Window | `CDC_WH` compute credits | Serverless credits | Total | Resumes |
|---------|--------|--------------------------|--------------------|-------|---------|
| 2026-11-25 | A | «…» | «…» | «…» | «…» |
| 2026-11-26 | A | «…» | «…» | «…» | «…» |
| 2026-11-27 | B | «…» | «…» | «…» | «…» |
| 2026-11-28 | B | «…» | «…» | «…» | «…» |
| 2026-11-29 (00–06) | Idle | «…» | «…» | «…» | «…» |

## 5. Per cluster (Q5)

| | A | B |
|--|---|---|
| Compute credits per cluster: mean · min · max | «…» | «…» |
| Clusters crossing their 2 h bucket (Q5b) | «…» | «…» |
| Billed hours (Q4b) | «…» | «…» |

## 6. Freshness (Q6)

| | A (indicative) | B |
|--|----------------|---|
| Bursts | «…» | «…» |
| Gaps (no consuming run, or > 120 min) | «…» | «…» |
| p50 · p95 · max (min) | «…» | «…» |

## 7. Attribution — estimated (Q8, [`ATTRIBUTION.md`](../ATTRIBUTION.md))

| | Value |
|--|-------|
| `rate_A` measured (credits/h) · consumption table reference | «…» · 1.35 |
| `rate_B` self-check (must be 1.0 ± 5%) | «…» |
| Total saving, **measured**: total(A) − total(B), per day | «…» |
| Gen1 share, **estimated** | «…» |
| Gate-task share, **estimated** | «…» |
| Batching share, **estimated** | «…» |
| Reported as one "orchestration" share? (task-only < 10% of A's billed time) | «yes / no» |

## 8. Reported apart (not total cost) — Q3

| Service type | A | B | Idle | Note |
|--------------|---|---|------|------|
| Cloud services, before / after the 10% adjustment | «…» | «…» | «…» | |
| `SNOWPIPE_STREAMING` | «…» | «…» | «…» | identical load |
| Budget refresh (`TIER_1H`) | «…» | «…» | «…» | service type from dry-run D8 |
| Nominal `WHEN` charge (F3) | — | «…» | «…» | where it appeared: «…» |

## 9. Caveats

- One resume per run? Gap between the sensor's query and the job's start (dry-run D6): «…».
- Decision 7 residual cases (key with no run): «…».
- Effect of the cursor at S3 (O32): «…».
- «anything else that a reader needs to judge the numbers»
