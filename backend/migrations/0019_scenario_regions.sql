-- Scenario region framework: the reusable, scenario-authored geography of a
-- world (kingdoms -> provinces -> cities, or whatever levels a scenario uses).
-- Regions are knowledge, not playable nodes: a world instances a copy of its
-- scenario's regions and the narrator materializes them as real locations on
-- demand. Levels are free-form so a school scenario can have one top-level
-- "school grounds" and an interplanetary scenario can treat planets as
-- top-level regions.

CREATE TABLE scenario_regions (
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
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
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scenario_id, region_id),
    FOREIGN KEY (scenario_id, parent_region_id)
        REFERENCES scenario_regions(scenario_id, region_id)
        ON DELETE CASCADE,
    CHECK (parent_region_id IS NULL OR parent_region_id <> region_id)
) STRICT;

CREATE INDEX idx_scenario_regions_parent
    ON scenario_regions(scenario_id, parent_region_id);
