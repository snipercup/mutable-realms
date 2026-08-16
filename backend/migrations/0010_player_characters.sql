-- Reusable player-character definitions and copied world instances.
-- Definitions are administrative templates. Instances copy the definition's
-- name/basic info and then evolve independently inside one world.

CREATE TABLE player_character_definitions (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    basic_info TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE TABLE player_character_operations (
    character_id TEXT NOT NULL REFERENCES player_character_definitions(id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (character_id, operation_id)
) STRICT;

CREATE TABLE player_character_instances (
    world_id TEXT PRIMARY KEY REFERENCES worlds(id) ON DELETE CASCADE,
    character_definition_id TEXT REFERENCES player_character_definitions(id) ON DELETE SET NULL,
    entity_id TEXT NOT NULL UNIQUE REFERENCES entities(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    basic_info TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE INDEX idx_player_character_instances_definition
    ON player_character_instances(character_definition_id);
