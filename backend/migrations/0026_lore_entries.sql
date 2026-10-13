-- Reusable scenario lore and mutable world-owned copies.
CREATE TABLE scenario_lore (
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    lore_id TEXT NOT NULL CHECK (length(trim(lore_id)) BETWEEN 1 AND 100),
    category TEXT NOT NULL CHECK (length(trim(category)) BETWEEN 1 AND 80),
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 20000),
    keywords_json TEXT NOT NULL DEFAULT '[]' CHECK (length(keywords_json) <= 10000),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scenario_id, lore_id)
) STRICT;
CREATE INDEX idx_scenario_lore_title ON scenario_lore(scenario_id, title);

CREATE TABLE world_lore (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    lore_id TEXT NOT NULL CHECK (length(trim(lore_id)) BETWEEN 1 AND 100),
    category TEXT NOT NULL CHECK (length(trim(category)) BETWEEN 1 AND 80),
    title TEXT NOT NULL CHECK (length(trim(title)) BETWEEN 1 AND 200),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 20000),
    keywords_json TEXT NOT NULL DEFAULT '[]' CHECK (length(keywords_json) <= 10000),
    updated_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    PRIMARY KEY (world_id, lore_id)
) STRICT;
CREATE INDEX idx_world_lore_title ON world_lore(world_id, title);

-- Existing worlds receive a one-time copy of their source scenario's lore.
-- Subsequent scenario edits do not alter world-owned copies.
INSERT INTO world_lore(
    world_id, lore_id, category, title, content, keywords_json, updated_event_id
)
SELECT
    w.id, sl.lore_id, sl.category, sl.title, sl.content, sl.keywords_json,
    e.id
FROM worlds w
JOIN scenario_lore sl ON sl.scenario_id = w.source_scenario_id
JOIN events e ON e.world_id = w.id AND e.operation_id = (
    SELECT operation_id FROM events
    WHERE world_id = w.id
    ORDER BY world_revision ASC, id ASC LIMIT 1
)
WHERE NOT EXISTS (
    SELECT 1 FROM world_lore wl
    WHERE wl.world_id = w.id AND wl.lore_id = sl.lore_id
);