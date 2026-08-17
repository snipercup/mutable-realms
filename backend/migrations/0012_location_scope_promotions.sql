CREATE TABLE location_scope_promotions (
    world_id TEXT NOT NULL,
    scope_location_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    PRIMARY KEY (world_id, scope_location_id, location_id),
    CHECK (scope_location_id <> location_id),
    FOREIGN KEY (world_id, scope_location_id)
        REFERENCES locations(world_id, id) ON DELETE CASCADE,
    FOREIGN KEY (world_id, location_id)
        REFERENCES locations(world_id, id) ON DELETE CASCADE
) STRICT;

CREATE INDEX idx_location_scope_promotions_location
    ON location_scope_promotions(world_id, location_id, scope_location_id);
