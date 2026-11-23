-- ========================================================================
-- docs/measurement/queries.sql — measurement queries for the A/B
-- COST_GOVERNANCE manifest item 15; REQ-07 / AT-008.
-- DESIGN_COST_GOVERNANCE 1.4: Measurement plan, Decisions 7 and 13, F3.
-- Method in prose: PROTOCOL.md (how and when) and ATTRIBUTION.md (Q8).
--
-- Drafted by the build agent (2026-11-18, finished 2026-11-23) with the
-- owner's defaults; the owner edits it. Nothing here has run on the account
-- yet. "TODO(dry run)" marks a value the 2026-11-24 dry run must confirm —
-- PROTOCOL.md §7 lists them. None is a decision left open.
--
-- HOW TO RUN (PROTOCOL.md §6)
--   * Final reading from >= 2026-11-29 10:00 UTC: WAREHOUSE_EVENTS_HISTORY
--     and METERING_DAILY_HISTORY have up to 3 h of latency (Snowflake docs).
--   * Warehouse: CDC_WH, and ONLY when no window is open (the dry-run
--     evening before 2026-11-25 00:00 UTC, or after the idle window). The
--     queries' own CDC_WH credits then fall outside every window. Never run
--     them on CDC_WH during A, B or idle: that voids the window.
--   * Roles: CDC_GOVERNANCE_RO reads SNOWFLAKE.ACCOUNT_USAGE (Q0–Q5, Q7, Q8);
--     it has no SELECT on CDC_POC.CONFIG, so Q6 and Q0.2 switch to CDC_ROLE_RO.
--   * All bucketing is in UTC. ACCOUNT_USAGE returns TIMESTAMP_LTZ, so every
--     timestamp goes through CONVERT_TIMEZONE('UTC', ...) first.
--   * "Total cost" (DEFINE, Success Criteria) = CDC_WH compute credits (Q1)
--     + serverless task credits (Q2). Cloud services are reported apart (Q3).
-- ========================================================================

USE ROLE CDC_GOVERNANCE_RO;
USE WAREHOUSE CDC_WH;  -- only outside the windows (HOW TO RUN)

-- Windows (UTC) — DESIGN, Measurement plan. A rerun moves these (PROTOCOL.md §5).
-- a_start must be at an EVEN hour: Q5 buckets clusters in 2 h steps from it.
SET a_start    = '2026-11-25 00:00:00'::TIMESTAMP_NTZ;
SET a_end      = '2026-11-27 00:00:00'::TIMESTAMP_NTZ;
SET b_start    = '2026-11-27 00:00:00'::TIMESTAMP_NTZ;
SET b_end      = '2026-11-29 00:00:00'::TIMESTAMP_NTZ;
SET idle_start = '2026-11-29 00:00:00'::TIMESTAMP_NTZ;
SET idle_end   = '2026-11-29 06:00:00'::TIMESTAMP_NTZ;

-- Dry run (2026-11-24): replace the block above with
--   SET a_start = '2026-11-24 12:00:00'::TIMESTAMP_NTZ;  SET a_end = '2026-11-24 15:00:00'::TIMESTAMP_NTZ;
--   SET b_start = '2026-11-24 15:00:00'::TIMESTAMP_NTZ;  SET b_end = '2026-11-24 18:00:00'::TIMESTAMP_NTZ;
--   SET idle_start = $b_end;  SET idle_end = $b_end;     -- no idle window in the dry run

-- Time zone of the wall clock stored in CONFIG.PENDING_RUNS.DETECTED_AT.
-- The gate procedure writes CURRENT_TIMESTAMP() (TIMESTAMP_LTZ, session time
-- zone) into a TIMESTAMP_NTZ column, so the stored value is the task
-- session's wall clock. TIMEZONE defaults to America/Los_Angeles (Snowflake
-- docs, Parameters) and nothing in this repo sets it. TODO(dry run): confirm
-- with Q0.1 + Q0.2, and set 'UTC' here if the account or tasks run in UTC.
-- (PROCESSING_LOG.FINISHED_AT is dbt's UTC timestamp: an offset in a string
-- cast to NTZ is not applied, so that column is already UTC.)
SET detected_at_tz = 'America/Los_Angeles';

-- User name under which task-run queries appear in QUERY_HISTORY (Q8b).
-- TODO(dry run): confirm (PROTOCOL.md §7). Expected 'SYSTEM'.
SET task_user = 'SYSTEM';


-- ------------------------------------------------------------------------
-- Q0. Sanity checks — run in the dry run, before trusting Q6.
-- ------------------------------------------------------------------------
-- Q0.1 Account-level TIMEZONE (the default tasks inherit unless set on them).
SHOW PARAMETERS LIKE 'TIMEZONE' IN ACCOUNT;

-- Q0.2 Empirical check (role CDC_ROLE_RO): the latest gate detection vs now.
--      After the last burst of a cluster, the gap must be minutes, not ~8 h.
--      If it is ~ -8 h, DETECTED_AT is Los Angeles wall clock (keep the SET above).
USE ROLE CDC_ROLE_RO;
SELECT MAX(detected_at)                                                 AS last_detected_raw,
       CONVERT_TIMEZONE('UTC', CURRENT_TIMESTAMP())::TIMESTAMP_NTZ      AS now_utc,
       DATEDIFF('minute', now_utc, last_detected_raw)                   AS raw_minus_utc_min
FROM CDC_POC.CONFIG.PENDING_RUNS;
USE ROLE CDC_GOVERNANCE_RO;


-- ------------------------------------------------------------------------
-- Q1. Warehouse credits per UTC day and window — CDC_WH only
--     (CDC_CI_WH and COMPUTE_WH are excluded from the analysis).
--     compute_credits is the warehouse term of "total cost".
-- ------------------------------------------------------------------------
SELECT
    CASE
        WHEN CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ < $a_end THEN 'A'
        WHEN CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $b_start AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ < $b_end THEN 'B'
        WHEN CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $idle_start AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ < $idle_end THEN 'IDLE'
    END                                                            AS run_window,
    DATE_TRUNC('day', CONVERT_TIMEZONE('UTC', start_time))::DATE   AS utc_day,
    ROUND(SUM(credits_used_compute), 4)                            AS compute_credits,
    ROUND(SUM(credits_used_cloud_services), 4)                     AS cloud_services_credits,  -- reported separately (DESIGN)
    ROUND(SUM(credits_used), 4)                                    AS total_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'CDC_WH'
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  $idle_end
GROUP BY 1, 2
ORDER BY 2;


-- ------------------------------------------------------------------------
-- Q2. Serverless gate-task credits per UTC day — database CDC_POC
--     The serverless term of "total cost"; IDLE rows feed the idle criterion
--     (< 0.01 credits over the 6 h).
-- ------------------------------------------------------------------------
SELECT
    CASE
        WHEN CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ < $a_end THEN 'A'
        WHEN CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $b_start AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ < $b_end THEN 'B'
        WHEN CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $idle_start AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ < $idle_end THEN 'IDLE'
    END                                                          AS run_window,
    DATE_TRUNC('day', CONVERT_TIMEZONE('UTC', start_time))::DATE AS utc_day,
    task_name,
    ROUND(SUM(credits_used), 6)                                  AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY
WHERE database_name = 'CDC_POC'
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  $idle_end
GROUP BY 1, 2, 3
ORDER BY 2, 3;


-- ------------------------------------------------------------------------
-- Q3. Cross-check: everything the account was billed, by service type
--     METERING_DAILY_HISTORY is daily and already in UTC days. Cloud services
--     are shown before and after the daily 10% adjustment, because the
--     adjustment changes when warehouse use drops (DESIGN). They are not part
--     of the DEFINE's "total cost". Documented SERVICE_TYPE values include
--     WAREHOUSE_METERING, SERVERLESS_TASK and SNOWPIPE_STREAMING.
--     TODO(dry run): under which SERVICE_TYPE the TIER_1H budget refresh is
--     billed (O13), and where the nominal WHEN charge appears (F3) — read the
--     dry-run day here and in Q2 (PROTOCOL.md §7).
-- ------------------------------------------------------------------------
SELECT
    usage_date,
    service_type,
    ROUND(SUM(credits_used_compute), 4)              AS compute,
    ROUND(SUM(credits_used_cloud_services), 4)       AS cloud_services,
    ROUND(SUM(credits_adjustment_cloud_services), 4) AS cloud_services_adjustment,
    ROUND(SUM(credits_billed), 4)                    AS billed
FROM SNOWFLAKE.ACCOUNT_USAGE.METERING_DAILY_HISTORY
WHERE usage_date BETWEEN $a_start::DATE AND $idle_end::DATE
GROUP BY 1, 2
ORDER BY 1, 2;


-- ------------------------------------------------------------------------
-- Q4. CDC_WH resumes per UTC day and window (hypothesis H2)
--     Snowflake docs list RESUME_WAREHOUSE / SUSPEND_WAREHOUSE with event
--     state STARTED only; cluster-level events (RESUME_CLUSTER, …) are not
--     counted, so a resume is counted once. TODO(dry run): confirm that one
--     resume of CDC_WH produces exactly one RESUME_WAREHOUSE row (§7).
-- ------------------------------------------------------------------------
SELECT
    CASE
        WHEN CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ >= $a_start AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ < $a_end THEN 'A'
        WHEN CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ >= $b_start AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ < $b_end THEN 'B'
        WHEN CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ >= $idle_start AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ < $idle_end THEN 'IDLE'
    END                                                        AS run_window,
    DATE_TRUNC('day', CONVERT_TIMEZONE('UTC', timestamp))::DATE AS utc_day,
    COUNT(*)                                                   AS resumes
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
WHERE warehouse_name = 'CDC_WH'
  AND event_name = 'RESUME_WAREHOUSE'
  AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ >= $a_start
  AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ <  $idle_end
GROUP BY 1, 2
ORDER BY 2;


-- ------------------------------------------------------------------------
-- Q4b. Billed seconds per resume (needed by Q8)
--      Billing: per second, 60 s minimum each time the warehouse resumes
--      (Snowflake docs, Understanding compute cost). Each RESUME_WAREHOUSE is
--      paired with the next event; an interval counts only if that event is a
--      SUSPEND_WAREHOUSE. Approximation: SUSPEND_WAREHOUSE is the moment the
--      suspension starts. Self-check in Q8a: B's credits ÷ billed hours ≈ 1.0.
-- ------------------------------------------------------------------------
--      The same CTE is repeated inside Q8 (the role creates no objects).
-- ------------------------------------------------------------------------
WITH ev AS (
    SELECT CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ AS ts, event_name
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
    WHERE warehouse_name = 'CDC_WH'
      AND event_name IN ('RESUME_WAREHOUSE', 'SUSPEND_WAREHOUSE')
      AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ >= $a_start
      AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ <  DATEADD('hour', 2, $idle_end)
),
paired AS (
    SELECT ts AS resumed_at,
           LEAD(ts)         OVER (ORDER BY ts) AS next_at,
           LEAD(event_name) OVER (ORDER BY ts) AS next_event,
           event_name
    FROM ev
)
SELECT
    CASE
        WHEN resumed_at >= $a_start    AND resumed_at < $a_end    THEN 'A'
        WHEN resumed_at >= $b_start    AND resumed_at < $b_end    THEN 'B'
        WHEN resumed_at >= $idle_start AND resumed_at < $idle_end THEN 'IDLE'
    END                                                                     AS run_window,
    COUNT(*)                                                                AS resumes,
    COUNT_IF(next_event IS DISTINCT FROM 'SUSPEND_WAREHOUSE')               AS unpaired,   -- must be 0
    ROUND(SUM(GREATEST(60, DATEDIFF('millisecond', resumed_at, next_at) / 1000)), 0) AS billed_seconds
FROM paired
WHERE event_name = 'RESUME_WAREHOUSE'
  AND resumed_at < $idle_end
GROUP BY 1
ORDER BY 1;


-- ------------------------------------------------------------------------
-- Q5. Per-cluster credits (validity rules: report per cluster as well as per day)
--     Clusters start every 2 h at :30 UTC. WAREHOUSE_METERING_HISTORY is
--     hourly, so the bucket [hh:00, hh+2:00) with hh even holds exactly one
--     cluster (bursts :30–:42, runs to ~:50) and its tails — exact, not an
--     approximation, as long as no cluster's activity crosses hh+2:00. Q5b
--     checks that; a cluster that fails it is flagged in RESULTS.md.
-- ------------------------------------------------------------------------
SELECT
    DATEADD('minute', 30,
        DATEADD('hour', 2 * FLOOR(DATEDIFF('hour', $a_start,
            CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ) / 2), $a_start)) AS cluster_start_utc,
    ROUND(SUM(credits_used_compute), 4) AS compute_credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'CDC_WH'
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  $b_end
GROUP BY 1
ORDER BY 1;

-- Q5b. Clusters whose CDC_WH activity crosses the bucket end (expected: no rows).
SELECT
    DATEADD('minute', 30,
        DATEADD('hour', 2 * FLOOR(DATEDIFF('hour', $a_start,
            CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ) / 2), $a_start)) AS cluster_start_utc,
    MAX(CONVERT_TIMEZONE('UTC', end_time)::TIMESTAMP_NTZ)                       AS last_query_end_utc
FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
WHERE warehouse_name = 'CDC_WH'
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  $b_end
GROUP BY 1
HAVING last_query_end_utc >= DATEADD('second', 5400 - 60, cluster_start_utc)  -- bucket end minus the 60 s suspend tail
ORDER BY 1;


-- ------------------------------------------------------------------------
-- Q6. Freshness — the run that actually consumed the burst (Decision 7)
--     Role CDC_ROLE_RO (SELECT on CDC_POC.CONFIG). commits.csv is pasted in
--     as a VALUES list — no stage, no table, nothing created. Generate the
--     rows with the awk line in PROTOCOL.md §6 and paste them over the
--     example rows below. Run once per window (A, B).
--
--     Definition (Decision 7): the FIRST PENDING_RUNS row detected after the
--     burst's committed_at → the run_key that consumed it → MAX(FINISHED_AT)
--     of that run's Gold models − committed_at. A first row with no consuming
--     key, a run with no Gold row, or > 120 min is a GAP (reported, not
--     dropped). The guardrail (p95 ≤ N + 5) applies to B only; A is indicative.
-- ------------------------------------------------------------------------
USE ROLE CDC_ROLE_RO;

WITH commits (burst_id, committed_at_utc, rows_affected) AS (
    SELECT * FROM VALUES
     ('c20261127T0030-b0', '2026-11-27T00:30:00.412+00:00'::TIMESTAMP_NTZ, 200)   -- example rows:
    ,('c20261127T0030-b1', '2026-11-27T00:32:00.101+00:00'::TIMESTAMP_NTZ, 200)   -- replace them
),
detections AS (
    SELECT CONVERT_TIMEZONE($detected_at_tz, 'UTC', detected_at) AS detected_at_utc,
           consumed_run_key
    FROM CDC_POC.CONFIG.PENDING_RUNS
),
first_detection AS (
    SELECT c.burst_id, c.committed_at_utc,
           MIN_BY(d.consumed_run_key, d.detected_at_utc) AS run_key,  -- NULL key = never consumed = gap
           MIN(d.detected_at_utc)                        AS first_detected_at_utc
    FROM commits c
    LEFT JOIN detections d
      ON d.detected_at_utc >= c.committed_at_utc
     AND d.detected_at_utc <  DATEADD('minute', 120, c.committed_at_utc)
    GROUP BY 1, 2
),
run_finish AS (
    SELECT run_key, MAX(finished_at) AS gold_finished_at_utc   -- dbt timestamp, already UTC
    FROM CDC_POC.CONFIG.PROCESSING_LOG
    WHERE layer = 'gold'                                        -- value written by assets.py
      AND status = 'success'
    GROUP BY 1
),
per_burst AS (
    SELECT f.burst_id, f.committed_at_utc, f.first_detected_at_utc, f.run_key, r.gold_finished_at_utc,
           DATEDIFF('millisecond', f.committed_at_utc, r.gold_finished_at_utc) / 60000.0 AS freshness_min
    FROM first_detection f
    LEFT JOIN run_finish r ON r.run_key = f.run_key
)
SELECT
    COUNT(*)                                                         AS bursts,
    COUNT_IF(freshness_min IS NULL OR freshness_min > 120)           AS gaps,
    ROUND(PERCENTILE_CONT(0.50) WITHIN GROUP (ORDER BY IFF(freshness_min <= 120, freshness_min, NULL)), 2) AS p50_min,
    ROUND(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY IFF(freshness_min <= 120, freshness_min, NULL)), 2) AS p95_min,
    ROUND(MAX(IFF(freshness_min <= 120, freshness_min, NULL)), 2)    AS max_min
FROM per_burst;
-- Per-burst detail: replace the final SELECT with
--   SELECT * FROM per_burst ORDER BY burst_id;
-- and save it as runs/<window>/freshness.csv.

USE ROLE CDC_GOVERNANCE_RO;


-- ------------------------------------------------------------------------
-- Q7. Idle window (F3, AT-004) — gate-task evaluations with streams empty
--     Expected: only skipped evaluations, no SUCCEEDED run of the body.
--     Cost side for the same 6 h: Q1 (IDLE must be 0), Q2 (IDLE < 0.01), Q3.
-- ------------------------------------------------------------------------
SELECT name, state, COUNT(*) AS runs
FROM SNOWFLAKE.ACCOUNT_USAGE.TASK_HISTORY
WHERE database_name = 'CDC_POC'
  AND ENDSWITH(name, '_GATE_TASK')
  AND CONVERT_TIMEZONE('UTC', scheduled_time)::TIMESTAMP_NTZ >= $idle_start
  AND CONVERT_TIMEZONE('UTC', scheduled_time)::TIMESTAMP_NTZ <  $idle_end
GROUP BY 1, 2
ORDER BY 1, 2;


-- ------------------------------------------------------------------------
-- Q8. Attribution (Decision 13; method in ATTRIBUTION.md) — ESTIMATES
--     Only the total is measured. Every share below is labelled "estimated".
-- ------------------------------------------------------------------------
-- Q8a. Measured credit rates: credits ÷ billed hours, per window.
--      rate_A is the Gen2 rate used in Q8c (owner default for B3); the
--      consumption table's 1.35 is reported next to it, not used.
--      rate_B is the self-check of Q4b's pairing: Gen1 XSMALL = 1.0 credit/h,
--      so |rate_B − 1.0| > 5% means billed seconds are wrong — stop and fix Q4b.
WITH ev AS (
    SELECT CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ AS ts, event_name
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
    WHERE warehouse_name = 'CDC_WH'
      AND event_name IN ('RESUME_WAREHOUSE', 'SUSPEND_WAREHOUSE')
      AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ >= $a_start
      AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ <  DATEADD('hour', 2, $b_end)
),
paired AS (
    SELECT ts AS resumed_at, LEAD(ts) OVER (ORDER BY ts) AS next_at,
           LEAD(event_name) OVER (ORDER BY ts) AS next_event, event_name
    FROM ev
),
billed AS (
    SELECT IFF(resumed_at < $a_end, 'A', 'B') AS run_window,
           SUM(GREATEST(60, DATEDIFF('millisecond', resumed_at, next_at) / 1000)) / 3600.0 AS billed_hours
    FROM paired
    WHERE event_name = 'RESUME_WAREHOUSE' AND next_event = 'SUSPEND_WAREHOUSE'   -- Q4b unpaired must be 0
      AND resumed_at >= $a_start AND resumed_at < $b_end
      AND NOT (resumed_at >= $a_end AND resumed_at < $b_start)
    GROUP BY 1
),
credits AS (
    SELECT IFF(CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ < $a_end, 'A', 'B') AS run_window,
           SUM(credits_used_compute) AS compute_credits
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
    WHERE warehouse_name = 'CDC_WH'
      AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start
      AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  $b_end
      AND NOT (CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_end
               AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ < $b_start)
    GROUP BY 1
)
SELECT c.run_window,
       ROUND(c.compute_credits, 4)                 AS compute_credits,
       ROUND(b.billed_hours, 4)                    AS billed_hours,
       ROUND(c.compute_credits / b.billed_hours, 3) AS credits_per_hour
FROM credits c JOIN billed b USING (run_window)
ORDER BY 1;

-- Q8b. Window A: billed seconds of resume intervals that contain ONLY gate-task
--      queries (no query from a non-task user between resume and suspend).
--      Known bias (Decision 13): rare in A, because the sensor's queries overlap.
WITH ev AS (
    SELECT CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ AS ts, event_name
    FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
    WHERE warehouse_name = 'CDC_WH'
      AND event_name IN ('RESUME_WAREHOUSE', 'SUSPEND_WAREHOUSE')
      AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ >= $a_start
      AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ <  DATEADD('hour', 2, $a_end)
),
intervals AS (
    SELECT resumed_at, next_at AS suspended_at
    FROM (SELECT ts AS resumed_at, LEAD(ts) OVER (ORDER BY ts) AS next_at,
                 LEAD(event_name) OVER (ORDER BY ts) AS next_event, event_name FROM ev)
    WHERE event_name = 'RESUME_WAREHOUSE' AND next_event = 'SUSPEND_WAREHOUSE'
      AND resumed_at < $a_end
),
q AS (
    SELECT CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ AS started_at, user_name
    FROM SNOWFLAKE.ACCOUNT_USAGE.QUERY_HISTORY
    WHERE warehouse_name = 'CDC_WH'
      AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start
      AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  DATEADD('hour', 2, $a_end)
),
classified AS (
    SELECT i.resumed_at, i.suspended_at,
           COUNT_IF(q.user_name =  $task_user) AS task_queries,
           COUNT_IF(q.user_name <> $task_user) AS other_queries
    FROM intervals i
    LEFT JOIN q ON q.started_at >= i.resumed_at AND q.started_at < i.suspended_at
    GROUP BY 1, 2
)
SELECT COUNT(*)                                                         AS intervals_a,
       COUNT_IF(other_queries = 0 AND task_queries > 0)                  AS task_only_intervals,
       SUM(IFF(other_queries = 0 AND task_queries > 0,
               GREATEST(60, DATEDIFF('millisecond', resumed_at, suspended_at) / 1000), 0)) AS task_only_billed_seconds
FROM classified;

-- Q8c. Shares — computed in RESULTS.md from the numbers above (no SQL needed):
--   total(W)       = Q1 compute_credits(W) + Q2 credits(W)
--   gen1_share     = billed_hours(B) × (rate_A − 1.0)                        [Q8a]
--   tasks_share    = task_only_billed_seconds / 3600 × rate_A − Q2 credits(B) [Q8b, Q2]
--   batching_share = total(A) − total(B) − gen1_share − tasks_share
-- Per-day figures divide by the number of whole UTC days in each window (2).
