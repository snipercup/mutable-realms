CREATE TABLE relationships (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    subject_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    object_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    category TEXT NOT NULL CHECK (length(trim(category)) > 0),
    score INTEGER NOT NULL DEFAULT 0 CHECK (score BETWEEN -100 AND 100),
    updated_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    PRIMARY KEY (world_id, subject_entity_id, object_entity_id),
    CHECK (subject_entity_id <> object_entity_id)
) STRICT;

CREATE TABLE memories (
    id TEXT PRIMARY KEY,
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 500),
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE INDEX idx_relationships_subject ON relationships(world_id, subject_entity_id);
CREATE INDEX idx_relationships_object ON relationships(world_id, object_entity_id);
CREATE INDEX idx_memories_entity ON memories(world_id, entity_id, created_at DESC);
