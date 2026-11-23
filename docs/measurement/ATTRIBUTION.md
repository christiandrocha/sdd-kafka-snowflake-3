# Attribution — how the saving is split between the three changes

COST_GOVERNANCE, manifest item 15 · REQ-07 · DESIGN 1.4, Decision 13. Queries: Q8a–Q8c in
[`queries.sql`](queries.sql).

> Draft written by the build agent on 2026-11-23 with the owner's defaults, for the owner to edit.
> Written before the measurement ran.

## 1. What is measured and what is estimated

The A/B measures **one number**: the difference in total cost between A and B under the same load.
B changes three things at once, so that difference is the **combined** effect:

| Change | A (v2) | B (v3) |
|--------|--------|--------|
| Warehouse generation | Gen2 | Gen1 |
| Gate tasks | on `CDC_WH` | serverless |
| Dagster batching | none (`N = 0`) | settle + window `N = 10` |

The share of each change is **estimated** from the metering split, using the arithmetic below.
Every share in the README and in RESULTS carries the word "estimated". Only the total is called
measured.

Why not measure each change on its own? That would take four windows of 48 h, or more,
instead of two. The trial calendar has room for two (PROTOCOL §2).

## 2. Inputs

| Symbol | Meaning | Query |
|--------|---------|-------|
| `total(W)` | `CDC_WH` compute credits + serverless task credits in window W | Q1 + Q2 |
| `hours(W)` | Billed warehouse hours in W: each resume → its suspend, with a minimum of 60 s | Q4b / Q8a |
| `rate_A` | `CDC_WH` compute credits ÷ `hours(A)`: the **measured** Gen2 XSMALL rate | Q8a |
| `rate_B` | The same for B: the Gen1 rate, expected to be 1.0 | Q8a |
| `task_only_s` | Billed seconds of A's resume intervals that contain only gate-task queries | Q8b |
| `serverless(B)` | Serverless gate-task credits in B | Q2 |

## 3. Method

**Self-check first.** Gen1 XSMALL bills 1 credit per hour, so `rate_B` must be ≈ 1.0. If
|`rate_B` − 1.0| > 5%, the way `hours(W)` is built from resume/suspend events is wrong. The
shares are then not computed until Q4b is fixed. This check is what lets `rate_A` count as a
measurement.

**Gen1 share.** It is what B's uptime would have cost on Gen2, minus what it cost on Gen1:

```text
gen1_share = hours(B) × (rate_A − 1.0)
```

- `rate_A` is measured from window A. This is the owner's default for Build checklist B3.
- Snowflake's consumption table value (1.35 for XSMALL Gen2, per the DESIGN) is reported next to
  it as a reference and is **not** used. If the two differ by more than 5%, RESULTS says so.
- Assumption: B's uptime would be the same on Gen2. That ignores Gen2's faster execution, which
  would shorten dbt runs. The assumption **overstates** the Gen1 share, and RESULTS states it.

**Gate-task share.** It is what A paid to resume the warehouse for gate tasks alone, minus what
B paid for serverless:

```text
tasks_share = task_only_s / 3600 × rate_A − serverless(B)
```

- A resume interval is "task only" if every query on `CDC_WH` between the resume and the next
  suspend ran as the task user (`$task_user`, confirmed in dry-run item D4).
- Intervals in which the sensor or dbt also ran are **not** counted. Their cost is shared
  between causes, and it ends up in the batching remainder.

**Batching share.** It is the remainder:

```text
batching_share = total(A) − total(B) − gen1_share − tasks_share
```

## 4. Known bias, and how it is reported

In profile A the gate tasks fire in the same minutes as the sensor's queries and the dbt runs,
because they all react to the same burst. Intervals with **only** task queries will be rare, so:

- `tasks_share` is **underestimated**;
- `batching_share` is **inflated** by the same amount.

Reporting rule, fixed now:
- If `task_only_s` is less than 10% of `hours(A)` × 3600, RESULTS and the README report
  `tasks_share + batching_share` as **one** "orchestration" share, and say why.
- Otherwise the three shares are reported separately, each marked estimated, with this bias
  stated next to them.

A share can come out **negative**. For example, if serverless costs more in B than the task-only
resumes cost in A, `tasks_share` < 0. A negative share is reported as is. It is a result, not an
error.

## 5. Per day

Every figure is computed per window and then divided by the number of whole UTC days in the
window (2). If a cluster is missing (PROTOCOL §5), the per-cluster figures in Q5 are the ones
compared, and the per-day figures carry a note.
