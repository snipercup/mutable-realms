ALTER TABLE location_metadata ADD COLUMN map_form TEXT
    CHECK (map_form IS NULL OR map_form IN (
        'building', 'street', 'district', 'city',
        'mine', 'forest', 'water', 'landmark'
    ));
