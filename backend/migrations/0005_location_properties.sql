CREATE TABLE location_properties (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    location_id TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    property TEXT NOT NULL CHECK (length(trim(property)) > 0),
    value INTEGER NOT NULL CHECK (value BETWEEN 0 AND 100),
    updated_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    PRIMARY KEY (world_id, location_id, property)
) STRICT;

CREATE INDEX idx_location_properties_location ON location_properties(world_id, location_id);
