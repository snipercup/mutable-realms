CREATE TABLE resources (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    owner_entity_id TEXT NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    resource_type TEXT NOT NULL CHECK (length(trim(resource_type)) > 0),
    quantity INTEGER NOT NULL DEFAULT 0 CHECK (quantity >= 0),
    updated_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    PRIMARY KEY (world_id, owner_entity_id, resource_type)
) STRICT;

CREATE INDEX idx_resources_owner ON resources(world_id, owner_entity_id);
