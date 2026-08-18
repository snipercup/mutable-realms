ALTER TABLE location_metadata ADD COLUMN geography_role TEXT NOT NULL DEFAULT 'local'
    CHECK (geography_role IN ('local', 'boundary', 'route'));
ALTER TABLE location_metadata ADD COLUMN direction TEXT
    CHECK (direction IS NULL OR direction IN (
        'north', 'northeast', 'east', 'southeast',
        'south', 'southwest', 'west', 'northwest'
    ));
ALTER TABLE location_metadata ADD COLUMN range_band TEXT
    CHECK (range_band IS NULL OR range_band IN ('short', 'mid', 'long'));
