-- ------------------------------------------------------------------------
-- seed_config.sql — TABLE_METADATA seed (COST_GOVERNANCE manifest item 5).
--
-- Data, not objects: the CONFIG tables are created by terraform/platform
-- (config_tables.tf). This file only inserts the ten Tier-1 domains. Renamed
-- from bootstrap_config.sql, whose DDL and grants moved to Terraform.
--
-- RUN BY: CI, after every apply on `main` (DESIGN Decision 11), as
-- TERRAFORM_SVC:
--   snow sql -f scripts/seed_config.sql
-- Warehouse CDC_CI_WH, never CDC_WH (validity rules).
--
-- IDEMPOTENT: insert-only MERGE. Existing rows are never changed here — later
-- changes go through scripts/sync_metadata.py, which records them in
-- METADATA_HISTORY.
-- ------------------------------------------------------------------------

USE ROLE SYSADMIN;
USE WAREHOUSE CDC_CI_WH;

MERGE INTO CDC_POC.CONFIG.TABLE_METADATA AS tgt
USING (
    SELECT table_name, topic, table_type, cdc_strategy, unique_key, source, changed_by, notes
    FROM VALUES
        ('payment_events',  'pg.public.payment_events',  'fact',   'upsert', 'event_id',      'manual', 'seed_config', 'Payment lifecycle events. Nested JSONB field `event`.'),
        ('search_events',   'pg.public.search_events',   'fact',   'upsert', 'search_id',     'manual', 'seed_config', 'User searches. Append-only at the source.'),
        ('recommendations', 'pg.public.recommendations', 'fact',   'upsert', 'event_id',      'manual', 'seed_config', 'ML recommendation events. Append-only at the source.'),
        ('orders',          'pg.public.orders',          'entity', 'upsert', 'order_id',      'manual', 'seed_config', 'Hub table. Links the domains via *_key (CPF, CNPJ, driver_id).'),
        ('driver_shifts',   'pg.public.driver_shifts',   'entity', 'upsert', 'shift_id',      'manual', 'seed_config', 'Per-shift driver performance.'),
        ('users_mongo',     'pg.public.users_mongo',     'entity', 'upsert', 'uuid',          'manual', 'seed_config', 'Users (simulated MongoDB origin). CPF = user_key in orders.'),
        ('users_mssql',     'pg.public.users_mssql',     'entity', 'upsert', 'uuid',          'manual', 'seed_config', 'Extended profile (simulated MSSQL origin). Same CPF.'),
        ('restaurants',     'pg.public.restaurants',     'entity', 'upsert', 'uuid',          'manual', 'seed_config', 'Restaurants (simulated MySQL origin). CNPJ = restaurant_key in orders.'),
        ('drivers',         'pg.public.drivers',         'entity', 'upsert', 'uuid',          'manual', 'seed_config', 'Drivers. driver_id = driver_key in orders.'),
        ('order_items',     'pg.public.order_items',     'fact',   'upsert', 'order_item_id', 'manual', 'seed_config', 'Order line items. Largest table in the project.')
    AS src (table_name, topic, table_type, cdc_strategy, unique_key, source, changed_by, notes)
) AS src
ON tgt.table_name = src.table_name
WHEN NOT MATCHED THEN INSERT (table_name, topic, table_type, cdc_strategy, unique_key, source, changed_by, notes)
    VALUES (src.table_name, src.topic, src.table_type, src.cdc_strategy, src.unique_key, src.source, src.changed_by, src.notes);

-- Read-back (expected: 10 active domains) -------------------------------------
SELECT active, COUNT(*) AS domains
FROM CDC_POC.CONFIG.TABLE_METADATA
GROUP BY active
ORDER BY active DESC;
