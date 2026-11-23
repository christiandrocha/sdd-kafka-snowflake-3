-- ========================================================================
-- docs/measurement/queries.sql — DRAFT for the owner to edit
-- COST_GOVERNANCE manifest item 15 (author: Christian; DESIGN, Agent
-- Assignment). Drafted by the build agent on 2026-11-18 at the owner's
-- request: the queries only, none of the protocol prose. Every "TODO(owner)"
-- is a decision the draft does not make for you. Nothing here has run yet.
--
-- REQ-07 / AT-008. DESIGN: Measurement plan, Decisions 7 and 13, F3.
--
-- HOW TO RUN
--   * After the windows, from >= 2026-11-29 10:00 UTC (ACCOUNT_USAGE latency).
--   * Never on CDC_WH while a window is open (validity rules). TODO(owner):
--     CDC_GOVERNANCE_RO only has USAGE on CDC_WH today — either grant it
--     COMPUTE_WH (Terraform PR) or run these only after the idle window ends.
--   * All bucketing is in UTC: ACCOUNT_USAGE returns TIMESTAMP_LTZ, so every
--     timestamp goes through CONVERT_TIMEZONE('UTC', ...) before DATE_TRUNC.
-- ========================================================================

USE ROLE CDC_GOVERNANCE_RO;
USE WAREHOUSE COMPUTE_WH;  -- TODO(owner): see HOW TO RUN

-- Windows (UTC) — DESIGN, Measurement plan. Edit here if a window is rerun.
SET a_start    = '2026-11-25 00:00:00'::TIMESTAMP_NTZ;
SET a_end      = '2026-11-27 00:00:00'::TIMESTAMP_NTZ;
SET b_start    = '2026-11-27 00:00:00'::TIMESTAMP_NTZ;
SET b_end      = '2026-11-29 00:00:00'::TIMESTAMP_NTZ;
SET idle_start = '2026-11-29 00:00:00'::TIMESTAMP_NTZ;
SET idle_end   = '2026-11-29 06:00:00'::TIMESTAMP_NTZ;


-- ------------------------------------------------------------------------
-- Q1. Warehouse credits per UTC day and window — CDC_WH only
--     (CDC_CI_WH and COMPUTE_WH are excluded from the analysis).
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
-- ------------------------------------------------------------------------
SELECT
    DATE_TRUNC('day', CONVERT_TIMEZONE('UTC', start_time))::DATE AS utc_day,
    task_name,
    ROUND(SUM(credits_used), 6)                                  AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.SERVERLESS_TASK_HISTORY
WHERE database_name = 'CDC_POC'
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  $idle_end
GROUP BY 1, 2
ORDER BY 1, 2;


-- ------------------------------------------------------------------------
-- Q3. Cross-check: everything the account was billed, by service type
--     METERING_DAILY_HISTORY is daily and already in UTC days. Cloud services
--     are shown before and after the daily 10% adjustment, because the
--     adjustment changes when warehouse use drops (DESIGN). They are not part
--     of the DEFINE's "total cost".
--     TODO(owner): which SERVICE_TYPE the TIER_1H budget refresh is billed
--     under (O13), and where the nominal WHEN charge appears (F3: check both
--     this view and Q2 for the idle window).
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
-- Q4. CDC_WH resumes per UTC day (hypothesis H2)
--     TODO(owner): confirm the exact EVENT_NAME in the dry run (DESIGN Risks);
--     the ILIKE is a placeholder until then.
-- ------------------------------------------------------------------------
SELECT
    DATE_TRUNC('day', CONVERT_TIMEZONE('UTC', timestamp))::DATE AS utc_day,
    event_name,
    event_state,
    COUNT(*)                                                   AS events
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_EVENTS_HISTORY
WHERE warehouse_name = 'CDC_WH'
  AND event_name ILIKE '%RESUME%'
  AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ >= $a_start
  AND CONVERT_TIMEZONE('UTC', timestamp)::TIMESTAMP_NTZ <  $idle_end
GROUP BY 1, 2, 3
ORDER BY 1, 2, 3;


-- ------------------------------------------------------------------------
-- Q5. Per-cluster normalisation (validity rules)
--     Clusters start every 2 h at :30 UTC (00:30, 02:30, ...). An hour bucket
--     belongs to the cluster that started at or before it. Credits are hourly
--     in WAREHOUSE_METERING_HISTORY (buckets start at hh:00), so each hour is
--     assigned whole: the hh:00 bucket holds the cluster that starts at hh:30
--     (bursts at :30-:42, runs to ~:50), and the hh+1:00 bucket its tails.
--     Cluster k = FLOOR(minutes since a_start / 120); start = a_start + 2k h + 30 min.
--     TODO(owner): accept the hourly approximation, or use QUERY_HISTORY
--     execution time for per-cluster uptime instead.
-- ------------------------------------------------------------------------
SELECT
    DATEADD('minute', 30,
        DATEADD('hour', 2 * FLOOR(DATEDIFF('minute', $a_start,
            CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ) / 120), $a_start)) AS cluster_start_utc,
    ROUND(SUM(credits_used), 4) AS credits
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'CDC_WH'
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $a_start
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  $b_end
GROUP BY 1
ORDER BY 1;


-- ------------------------------------------------------------------------
-- Q6. Freshness — the run that actually consumed the burst (Decision 7)
--     commits.csv lives in docs/measurement/runs/<window>/ (generator,
--     item 14). TODO(owner): how it gets into Snowflake. Options:
--     (a) a TEMPORARY table + PUT/COPY from Snowsight, gone at session end;
--     (b) compute freshness outside Snowflake (pandas) from commits.csv plus
--         an export of the two CONFIG tables below.
--     The join, assuming (a) as TMP_COMMITS(burst_id, committed_at_utc, rows):
-- ------------------------------------------------------------------------
-- WITH first_detection AS (
--     SELECT c.burst_id, c.committed_at_utc,
--            MIN_BY(p.consumed_run_key, p.detected_at) AS run_key
--     FROM TMP_COMMITS c
--     JOIN CDC_POC.CONFIG.PENDING_RUNS p
--       ON p.detected_at >= c.committed_at_utc           -- TODO(owner): PENDING_RUNS.detected_at is
--      AND p.consumed_run_key IS NOT NULL                 --   CURRENT_TIMESTAMP() in the session TZ
--     GROUP BY 1, 2                                        --   (TIMESTAMP_NTZ); confirm it is UTC
-- ),
-- run_finish AS (
--     SELECT run_key, MAX(finished_at) AS gold_finished_at
--     FROM CDC_POC.CONFIG.PROCESSING_LOG
--     WHERE layer = 'gold'                                 -- TODO(owner): confirm the layer value
--     GROUP BY 1
-- )
-- SELECT f.burst_id,
--        DATEDIFF('second', f.committed_at_utc, r.gold_finished_at) / 60.0 AS freshness_min
-- FROM first_detection f
-- LEFT JOIN run_finish r USING (run_key)                  -- NULL = gap (> 2 h: report, Decision 7)
-- ORDER BY 1;
-- p95 per window: PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY freshness_min).


-- ------------------------------------------------------------------------
-- Q7. Idle window (F3) — gate-task evaluations with streams empty
--     Expected: only skipped evaluations (AT-004). Read the cost side in Q2
--     and Q3 for the same 6 hours.
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
-- Q8. Attribution (Decision 13) — estimated shares, not measurements
--     Gen1 share: (B billed warehouse seconds / 3600) x (Gen2 rate - 1.0).
--     TODO(owner): the Gen2 rate — B3 says source 1.35 from the consumption
--     table, or derive it from window A as credits / billed hours; say which.
--     The serverless-task and batching shares need the resume intervals that
--     contain only task queries (QUERY_HISTORY between resume and suspend):
--     left for ATTRIBUTION.md, which defines the method in prose first.
-- ------------------------------------------------------------------------
SELECT
    'B' AS run_window,
    ROUND(SUM(credits_used_compute), 4) AS b_compute_credits
    -- TODO(owner): billed seconds — WAREHOUSE_METERING_HISTORY is hourly
    -- credits; billed seconds come from WAREHOUSE_EVENTS_HISTORY resume/suspend
    -- pairs (60 s minimum per resume).
FROM SNOWFLAKE.ACCOUNT_USAGE.WAREHOUSE_METERING_HISTORY
WHERE warehouse_name = 'CDC_WH'
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ >= $b_start
  AND CONVERT_TIMEZONE('UTC', start_time)::TIMESTAMP_NTZ <  $b_end;
