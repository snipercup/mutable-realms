CREATE TABLE location_memories (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    memory_key TEXT NOT NULL CHECK (length(trim(memory_key)) BETWEEN 1 AND 100),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 300),
    occurrence_count INTEGER NOT NULL DEFAULT 1 CHECK (occurrence_count >= 1),
    updated_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    PRIMARY KEY (world_id, location_id, memory_key)
) STRICT;

CREATE INDEX idx_location_memories_location
    ON location_memories(world_id, location_id);
