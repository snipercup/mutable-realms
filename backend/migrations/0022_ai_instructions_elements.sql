-- Add a dedicated narrator-instruction element to scenario and world content.
-- Rebuild the two fixed-type tables because SQLite cannot alter a CHECK list.
PRAGMA foreign_keys = OFF;

ALTER TABLE scenario_elements RENAME TO scenario_elements_old;
CREATE TABLE scenario_elements (
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    element_type TEXT NOT NULL CHECK (
        element_type IN ('ai_instructions', 'author_note', 'plot_essentials', 'opening_scene')
    ),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 20000),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scenario_id, element_type)
) STRICT;
INSERT INTO scenario_elements(scenario_id, element_type, content, updated_at)
SELECT scenario_id, element_type, content, updated_at FROM scenario_elements_old;
DROP TABLE scenario_elements_old;

ALTER TABLE world_elements RENAME TO world_elements_old;
CREATE TABLE world_elements (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    element_type TEXT NOT NULL CHECK (
        element_type IN ('ai_instructions', 'author_note', 'plot_essentials', 'opening_scene')
    ),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 20000),
    updated_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    PRIMARY KEY (world_id, element_type)
) STRICT;
INSERT INTO world_elements(world_id, element_type, content, updated_event_id)
SELECT world_id, element_type, content, updated_event_id FROM world_elements_old;
DROP TABLE world_elements_old;

CREATE INDEX idx_world_elements_world ON world_elements(world_id);
PRAGMA foreign_keys = ON;
