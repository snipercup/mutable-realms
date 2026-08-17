CREATE TABLE location_metadata (
    world_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    kind TEXT,
    is_map_scope INTEGER NOT NULL DEFAULT 0 CHECK (is_map_scope IN (0, 1)),
    is_default_scope INTEGER NOT NULL DEFAULT 0 CHECK (is_default_scope IN (0, 1)),
    PRIMARY KEY (world_id, location_id),
    CHECK (kind IS NULL OR length(trim(kind)) > 0),
    CHECK (is_default_scope = 0 OR is_map_scope = 1),
    FOREIGN KEY (world_id, location_id)
        REFERENCES locations(world_id, id) ON DELETE CASCADE
) STRICT;

CREATE TABLE location_containment (
    world_id TEXT NOT NULL,
    child_location_id TEXT NOT NULL,
    parent_location_id TEXT NOT NULL,
    PRIMARY KEY (world_id, child_location_id),
    CHECK (child_location_id <> parent_location_id),
    FOREIGN KEY (world_id, child_location_id)
        REFERENCES locations(world_id, id) ON DELETE CASCADE,
    FOREIGN KEY (world_id, parent_location_id)
        REFERENCES locations(world_id, id) ON DELETE RESTRICT
) STRICT;

CREATE INDEX idx_location_containment_parent
    ON location_containment(world_id, parent_location_id, child_location_id);
CREATE INDEX idx_location_metadata_scope
    ON location_metadata(world_id, is_map_scope, is_default_scope, location_id);
