CREATE TABLE entities_generalized (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    kind TEXT NOT NULL CHECK (length(trim(kind)) > 0),
    name TEXT NOT NULL CHECK (length(trim(name)) > 0),
    UNIQUE (world_id, id)
) STRICT;

CREATE TABLE entity_locations_generalized (
    entity_id TEXT PRIMARY KEY REFERENCES entities_generalized(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES locations(id) ON DELETE RESTRICT
) STRICT;

CREATE TABLE characters_generalized (
    entity_id TEXT PRIMARY KEY REFERENCES entities_generalized(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (length(trim(role)) > 0),
    condition TEXT,
    disposition TEXT NOT NULL DEFAULT 'active' CHECK (length(trim(disposition)) > 0)
) STRICT;

CREATE TABLE beds_generalized (
    entity_id TEXT PRIMARY KEY REFERENCES entities_generalized(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES locations(id) ON DELETE RESTRICT,
    occupant_entity_id TEXT UNIQUE REFERENCES characters_generalized(entity_id) ON DELETE RESTRICT,
    CHECK (occupant_entity_id IS NULL OR occupant_entity_id <> entity_id)
) STRICT;

CREATE TABLE events_generalized (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    event_type TEXT NOT NULL CHECK (length(trim(event_type)) > 0),
    actor_entity_id TEXT REFERENCES entities_generalized(id) ON DELETE SET NULL,
    summary TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(payload_json)),
    world_revision INTEGER NOT NULL CHECK (world_revision > 0),
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (world_id, world_revision),
    FOREIGN KEY (world_id, operation_id)
        REFERENCES operations(world_id, operation_id)
) STRICT;

INSERT INTO entities_generalized(id, world_id, kind, name)
SELECT id, world_id, kind, name FROM entities;

INSERT INTO entity_locations_generalized(entity_id, location_id)
SELECT entity_id, location_id FROM entity_locations;

INSERT INTO characters_generalized(entity_id, role, condition, disposition)
SELECT entity_id, role, condition, disposition FROM characters;

INSERT INTO beds_generalized(entity_id, location_id, occupant_entity_id)
SELECT entity_id, location_id, occupant_entity_id FROM beds;

INSERT INTO events_generalized(
    id, world_id, operation_id, event_type, actor_entity_id,
    summary, payload_json, world_revision, occurred_at
)
SELECT id, world_id, operation_id, event_type, actor_entity_id,
       summary, payload_json, world_revision, occurred_at
FROM events;

DROP TABLE events;
DROP TABLE beds;
DROP TABLE entity_locations;
DROP TABLE characters;
DROP TABLE entities;

ALTER TABLE entities_generalized RENAME TO entities;
ALTER TABLE entity_locations_generalized RENAME TO entity_locations;
ALTER TABLE characters_generalized RENAME TO characters;
ALTER TABLE beds_generalized RENAME TO beds;
ALTER TABLE events_generalized RENAME TO events;

CREATE INDEX idx_entities_world ON entities(world_id);
CREATE INDEX idx_entity_locations_location ON entity_locations(location_id);
CREATE INDEX idx_beds_location ON beds(location_id);
CREATE INDEX idx_events_world_revision ON events(world_id, world_revision DESC);
