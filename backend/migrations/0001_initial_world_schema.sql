CREATE TABLE worlds (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    revision INTEGER NOT NULL DEFAULT 0 CHECK (revision >= 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE TABLE locations (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    description TEXT NOT NULL DEFAULT '',
    UNIQUE (world_id, id)
) STRICT;

CREATE TABLE entities (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (kind IN ('character', 'bed')),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    UNIQUE (world_id, id)
) STRICT;

CREATE TABLE entity_locations (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES locations(id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE characters (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('player', 'patient', 'npc')),
    condition TEXT,
    disposition TEXT NOT NULL DEFAULT 'active'
        CHECK (disposition IN ('active', 'admitted', 'discharged'))
) STRICT;

CREATE TABLE beds (
    entity_id TEXT PRIMARY KEY REFERENCES entities(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    occupant_entity_id TEXT UNIQUE REFERENCES characters(entity_id) ON DELETE RESTRICT,
    CHECK (occupant_entity_id IS NULL OR occupant_entity_id <> entity_id)
) STRICT;

CREATE TABLE operations (
    world_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    operation_type TEXT NOT NULL CHECK (length(trim(operation_type)) > 0),
    request_json TEXT NOT NULL CHECK (json_valid(request_json)),
    result_json TEXT NOT NULL CHECK (json_valid(result_json)),
    completed_revision INTEGER NOT NULL CHECK (completed_revision > 0),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (world_id, operation_id),
    UNIQUE (world_id, completed_revision),
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE
) STRICT;

CREATE TABLE events (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (length(trim(event_type)) > 0),
    actor_entity_id TEXT REFERENCES entities(id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
    world_revision INTEGER NOT NULL CHECK (world_revision > 0),
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (world_id, world_revision),
    FOREIGN KEY (world_id, operation_id)
        REFERENCES operations(world_id, operation_id)
) STRICT;

CREATE INDEX idx_locations_world ON locations(world_id);
CREATE INDEX idx_entities_world ON entities(world_id);
CREATE INDEX idx_entity_locations_location ON entity_locations(location_id);
CREATE INDEX idx_beds_location ON beds(location_id);
CREATE INDEX idx_events_world_revision ON events(world_id, world_revision DESC);
