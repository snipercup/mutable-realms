CREATE TABLE world_routes (
    world_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    origin_location_id TEXT NOT NULL,
    destination_location_id TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    route_kind TEXT NOT NULL DEFAULT 'route',
    is_active INTEGER NOT NULL DEFAULT 1 CHECK (is_active IN (0, 1)),
    PRIMARY KEY (world_id, route_id),
    CHECK (origin_location_id <> destination_location_id),
    CHECK (length(trim(name)) > 0),
    CHECK (length(trim(route_kind)) > 0),
    FOREIGN KEY (world_id) REFERENCES worlds(id) ON DELETE CASCADE,
    FOREIGN KEY (world_id, origin_location_id)
        REFERENCES locations(world_id, id) ON DELETE RESTRICT,
    FOREIGN KEY (world_id, destination_location_id)
        REFERENCES locations(world_id, id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX idx_world_routes_origin
    ON world_routes(world_id, origin_location_id, is_active, route_id);
CREATE INDEX idx_world_routes_destination
    ON world_routes(world_id, destination_location_id, route_id);
