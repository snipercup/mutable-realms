CREATE TABLE location_links (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    location_a TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    location_b TEXT NOT NULL REFERENCES locations(id) ON DELETE CASCADE,
    PRIMARY KEY (world_id, location_a, location_b),
    CHECK (location_a < location_b)
) STRICT;

CREATE INDEX idx_location_links_a ON location_links(world_id, location_a);
CREATE INDEX idx_location_links_b ON location_links(world_id, location_b);
