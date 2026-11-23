"""Simulation of the SCD2_RESTAURANTS design logic (sketch, sqlite window functions).

Covers: redelivered duplicate, same-millisecond tie, tombstone, delete (PK-only before image),
snapshot rows captured after the items, ambiguous restaurant_id, unregistered restaurant,
item after delete. Checks REQ-06 properties, version counts, attribution and sum preservation.
"""
import sqlite3

db = sqlite3.connect(":memory:")
db.executescript("""
CREATE TABLE raw_restaurants (uuid TEXT, restaurant_id INT, cuisine_type TEXT, city TEXT,
  op TEXT, source_ts_ms INT, kafka_partition INT, kafka_offset INT, kafka_created_at INT);
CREATE TABLE raw_order_items (order_item_id TEXT, restaurant_id INT, subtotal REAL,
  op TEXT, source_ts_ms INT, kafka_offset INT);
""")
R = [
 # snapshot (op r) at t=1000, AFTER items i0 were snapshotted at t=990
 ("A", 1, "Italian",  "SP", "r", 1000, 0, 10, 1000),
 ("A", 1, "Japanese", "SP", "u", 2000, 0, 11, 2000),
 ("A", 1, "Japanese", "SP", "u", 2000, 0, 11, 2000),   # redelivered duplicate of offset 11
 ("A", 1, "Vegan",    "SP", "u", 2000, 0, 12, 2001),   # same-ms tie, later offset
 ("B", 2, "Arabic",   "RJ", "r", 1000, 1, 5, 1000),
 ("B", None, None,    None, "d", 3000, 1, 6, 3000),    # delete: PK-only before image
 (None, None, None,   None, None, None, 1, 7, 3000),   # tombstone
 ("C", 3, "Burgers",  "BH", "r", 1000, 2, 1, 1000),    # C and D share restaurant_id 3
 ("D", 3, "Burgers",  "CU", "c", 2500, 3, 1, 2500),
 ("E", 9, "Late",     "XX", "c", 9000, 0, 99, 9999),   # beyond the Bronze horizon
]
db.executemany("INSERT INTO raw_restaurants VALUES (?,?,?,?,?,?,?,?,?)", R)
I = [
 ("i0", 1, 10.0, "r", 990, 1), ("i1", 1, 20.0, "c", 1500, 2), ("i1", 1, 20.0, "u", 4000, 3),
 ("i2", 1, 30.0, "c", 2000, 4), ("i3", 1, 40.0, "c", 2500, 5),
 ("i4", 2, 50.0, "c", 2000, 6), ("i5", 2, 60.0, "c", 3500, 7),   # i5 after B deleted
 ("i6", 3, 70.0, "c", 2000, 8), ("i7", 3, 80.0, "c", 2600, 9),   # i7 ambiguous (C and D)
 ("i8", 77, 90.0, "c", 2000, 10),                                 # unregistered
]
db.executemany("INSERT INTO raw_order_items VALUES (?,?,?,?,?,?)", I)
HORIZON = 3000  # MAX(kafka_created_at) in bronze_restaurants at run time

db.executescript(f"""
CREATE VIEW events AS
SELECT * FROM raw_restaurants
WHERE kafka_created_at <= {HORIZON};

-- scd2 strategy (sketch of the macro branch)
CREATE VIEW history AS
WITH dedup AS (
  SELECT * FROM (
    SELECT *, ROW_NUMBER() OVER (PARTITION BY uuid, kafka_partition, kafka_offset, source_ts_ms
                                 ORDER BY kafka_created_at) AS _rn
    FROM events WHERE uuid IS NOT NULL) WHERE _rn = 1),
ordered AS (
  SELECT *,
    ROW_NUMBER() OVER w AS version_number,
    source_ts_ms AS valid_from,
    LEAD(source_ts_ms) OVER w AS valid_to,
    (op = 'd') AS is_deleted
  FROM dedup
  WINDOW w AS (PARTITION BY uuid ORDER BY source_ts_ms, kafka_offset))
SELECT *, (valid_to IS NULL AND NOT is_deleted) AS is_current FROM ordered;

-- upsert strategy over the same horizon (silver_restaurants)
CREATE VIEW current_state AS
SELECT * FROM (
  SELECT *, ROW_NUMBER() OVER (PARTITION BY uuid ORDER BY source_ts_ms DESC, kafka_offset DESC) rn
  FROM events WHERE uuid IS NOT NULL) WHERE rn = 1 AND op IS NOT 'd';

CREATE VIEW items AS   -- silver_order_items (upsert) + first-seen event time from raw
SELECT s.order_item_id, s.restaurant_id, s.subtotal, f.event_ts
FROM (SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY order_item_id
        ORDER BY source_ts_ms DESC, kafka_offset DESC) rn FROM raw_order_items) WHERE rn = 1) s
JOIN (SELECT order_item_id, MIN(source_ts_ms) event_ts FROM raw_order_items
      GROUP BY order_item_id) f USING (order_item_id)
WHERE s.restaurant_id IS NOT NULL;

CREATE VIEW attribution AS
WITH cand AS (
  SELECT i.order_item_id, h.uuid, h.version_number, h.valid_from, h.kafka_offset,
         h.cuisine_type
  FROM items i JOIN history h
    ON h.restaurant_id = i.restaurant_id
   AND NOT h.is_deleted
   AND i.event_ts >= CASE WHEN h.version_number = 1 AND h.op = 'r' THEN -1e18 ELSE h.valid_from END
   AND i.event_ts <  COALESCE(h.valid_to, 1e18)),
ranked AS (
  SELECT *, COUNT(*) OVER (PARTITION BY order_item_id) AS candidates,
         ROW_NUMBER() OVER (PARTITION BY order_item_id
                            ORDER BY valid_from DESC, kafka_offset DESC) AS rn
  FROM cand)
SELECT i.order_item_id, i.restaurant_id, i.subtotal, i.event_ts, r.uuid, r.version_number,
       r.cuisine_type, COALESCE(r.candidates, 0) AS candidates,
       CASE WHEN r.uuid IS NULL AND EXISTS (SELECT 1 FROM history h
                 WHERE h.restaurant_id = i.restaurant_id) THEN 'no_version_at_event_time'
            WHEN r.uuid IS NULL THEN 'unregistered'
            WHEN r.candidates > 1 THEN 'ambiguous_resolved'
            WHEN r.version_number = 1 AND i.event_ts < r.valid_from THEN 'before_first_capture'
            ELSE 'matched' END AS attribution_status
FROM items i LEFT JOIN (SELECT * FROM ranked WHERE rn = 1) r USING (order_item_id);
""")

def q(sql):
    return db.execute(sql).fetchall()

fail = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        fail.append(name)

print("history:")
for r in q("SELECT uuid, version_number, op, cuisine_type, valid_from, valid_to, is_current, "
           "is_deleted FROM history ORDER BY uuid, version_number"):
    print("  ", r)
check("REQ-06 at most one current per key",
      q("SELECT MAX(c) FROM (SELECT SUM(is_current) c FROM history GROUP BY uuid)")[0][0] <= 1)
check("REQ-06 no overlaps (half-open)", q("""SELECT COUNT(*) FROM history a JOIN history b
      ON a.uuid=b.uuid AND a.version_number<b.version_number
      AND b.valid_from < COALESCE(a.valid_to,1e18) AND a.valid_from < COALESCE(b.valid_to,1e18)
      AND a.valid_from < COALESCE(a.valid_to,1e18) AND b.valid_from < COALESCE(b.valid_to,1e18)
      """)[0][0] == 0)
check("REQ-06 contiguous", q("""SELECT COUNT(*) FROM history a JOIN history b
      ON a.uuid=b.uuid AND b.version_number=a.version_number+1
      WHERE a.valid_to IS NOT b.valid_from""")[0][0] == 0)
check("duplicate redelivery collapsed: A has 3 versions",
      q("SELECT COUNT(*) FROM history WHERE uuid='A'")[0][0] == 3)
check("delete closes B", q("SELECT is_deleted, is_current FROM history WHERE uuid='B' "
      "ORDER BY version_number DESC LIMIT 1")[0] == (1, 0))
check("tombstone excluded", q("SELECT COUNT(*) FROM history WHERE uuid IS NULL")[0][0] == 0)
check("horizon excludes E", q("SELECT COUNT(*) FROM history WHERE uuid='E'")[0][0] == 0)
check("AT-004 reconciliation", q("""SELECT COUNT(*) FROM (
      SELECT uuid, restaurant_id, cuisine_type, city FROM history WHERE is_current
      EXCEPT SELECT uuid, restaurant_id, cuisine_type, city FROM current_state)""")[0][0] == 0
      and q("SELECT COUNT(*) FROM history WHERE is_current")[0][0]
      == q("SELECT COUNT(*) FROM current_state")[0][0])
print("attribution:")
for r in q("SELECT order_item_id, event_ts, uuid, version_number, cuisine_type, candidates, "
           "attribution_status FROM attribution ORDER BY order_item_id"):
    print("  ", r)
check("one row per item (no double match)",
      q("SELECT COUNT(*), COUNT(DISTINCT order_item_id) FROM attribution")[0]
      == (len({i[0] for i in I}),) * 2)
check("AT-005 i1 and i3 attributed to different versions", q(
      "SELECT COUNT(DISTINCT version_number) FROM attribution WHERE order_item_id IN ('i1','i3')"
      )[0][0] == 2)
check("i1 uses FIRST event time (Italian), not its later update",
      q("SELECT cuisine_type FROM attribution WHERE order_item_id='i1'")[0][0] == "Italian")
check("i0 captured before snapshot -> first version",
      q("SELECT attribution_status FROM attribution WHERE order_item_id='i0'")[0][0]
      == "before_first_capture")
check("i5 after delete flagged", q("SELECT attribution_status FROM attribution "
      "WHERE order_item_id='i5'")[0][0] == "no_version_at_event_time")
check("i6 (before D was created) matches only C", q("SELECT uuid, attribution_status "
      "FROM attribution WHERE order_item_id='i6'")[0] == ("C", "matched"))
check("i7 ambiguous resolved to the later version (D)", q("SELECT uuid, attribution_status "
      "FROM attribution WHERE order_item_id='i7'")[0] == ("D", "ambiguous_resolved"))
check("AT-006 sum preserved", q("SELECT SUM(subtotal) FROM attribution")[0][0]
      == q("SELECT SUM(subtotal) FROM items")[0][0])
print("\nRESULT:", "all checks passed" if not fail else f"{len(fail)} failed: {fail}")
