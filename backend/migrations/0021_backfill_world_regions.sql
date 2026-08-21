-- Backfill world_regions for worlds created before migration 0020.
-- Worlds created earlier copied story elements but no region framework. This
-- migration copies each world's source scenario regions into its world_regions
-- so pre-existing worlds (e.g. the live aerthalon world) get the same
-- framework as newly instanced ones. Idempotent by construction: migrations
-- run once, and the NOT EXISTS guard also protects against reruns.
INSERT INTO world_regions (
    world_id, region_id, parent_region_id, level, title, description,
    attributes_json
)
SELECT
    w.id,
    sr.region_id,
    sr.parent_region_id,
    sr.level,
    sr.title,
    sr.description,
    sr.attributes_json
FROM worlds w
JOIN scenario_regions sr ON sr.scenario_id = w.source_scenario_id
WHERE NOT EXISTS (
    SELECT 1 FROM world_regions wr
    WHERE wr.world_id = w.id AND wr.region_id = sr.region_id
);
