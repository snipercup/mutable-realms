-- Add gate to the fixed map-form allowlist while preserving location metadata.
PRAGMA foreign_keys = OFF;

ALTER TABLE location_metadata RENAME TO location_metadata_old;
CREATE TABLE location_metadata (
    world_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    kind TEXT,
    is_map_scope INTEGER NOT NULL DEFAULT 0 CHECK (is_map_scope IN (0, 1)),
    is_default_scope INTEGER NOT NULL DEFAULT 0 CHECK (is_default_scope IN (0, 1)),
    geography_role TEXT NOT NULL DEFAULT 'local'
        CHECK (geography_role IN ('local', 'boundary', 'route')),
    direction TEXT CHECK (direction IS NULL OR direction IN (
        'north', 'northeast', 'east', 'southeast',
        'south', 'southwest', 'west', 'northwest'
    )),
    range_band TEXT CHECK (range_band IS NULL OR range_band IN ('short', 'mid', 'long')),
    map_form TEXT CHECK (map_form IS NULL OR map_form IN (
        'building', 'street', 'district', 'city',
        'mine', 'forest', 'water', 'gate', 'landmark'
    )),
    PRIMARY KEY (world_id, location_id),
    CHECK (kind IS NULL OR length(trim(kind)) > 0),
    CHECK (is_default_scope = 0 OR is_map_scope = 1),
    FOREIGN KEY (world_id, location_id)
        REFERENCES locations(world_id, id) ON DELETE CASCADE
) STRICT;
INSERT INTO location_metadata(
    world_id, location_id, kind, is_map_scope, is_default_scope,
    geography_role, direction, range_band, map_form
)
SELECT world_id, location_id, kind, is_map_scope, is_default_scope,
       geography_role, direction, range_band, map_form
FROM location_metadata_old;
DROP TABLE location_metadata_old;
CREATE INDEX idx_location_metadata_scope
    ON location_metadata(world_id, is_map_scope, is_default_scope, location_id);

PRAGMA foreign_keys = ON;
