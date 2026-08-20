-- World region framework: the play-side copy of a scenario's region hierarchy
-- (kingdoms -> provinces -> cities, or whatever levels the scenario uses).
-- Copied from scenario_regions when a world is instanced, so every world from
-- a scenario carries the same framework knowledge while the narrator may
-- materialize different locations in each world. Regions are knowledge, not
-- playable nodes; `location_id` binds a region to the location the narrator
-- materializes for it (set by expansion later), and is NULL until then.

CREATE TABLE world_regions (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    region_id TEXT NOT NULL CHECK (
        length(trim(region_id)) BETWEEN 1 AND 100
    ),
    parent_region_id TEXT,
    level TEXT NOT NULL CHECK (
        length(trim(level)) BETWEEN 1 AND 50
    ),
    title TEXT NOT NULL CHECK (
        length(trim(title)) BETWEEN 1 AND 200
    ),
    description TEXT NOT NULL CHECK (
        length(trim(description)) BETWEEN 1 AND 2000
    ),
    attributes_json TEXT NOT NULL DEFAULT '{}' CHECK (
        length(attributes_json) <= 10000
    ),
    location_id TEXT REFERENCES locations(id) ON DELETE SET NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (world_id, region_id),
    FOREIGN KEY (world_id, parent_region_id)
        REFERENCES world_regions(world_id, region_id)
        ON DELETE CASCADE,
    CHECK (parent_region_id IS NULL OR parent_region_id <> region_id)
) STRICT;

CREATE INDEX idx_world_regions_parent
    ON world_regions(world_id, parent_region_id);
