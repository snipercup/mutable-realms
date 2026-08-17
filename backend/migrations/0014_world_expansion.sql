CREATE TABLE world_expansion_limits (
    world_id TEXT PRIMARY KEY REFERENCES worlds(id) ON DELETE CASCADE,
    max_locations INTEGER NOT NULL DEFAULT 100 CHECK (max_locations >= 0)
) STRICT;

CREATE TABLE world_expansion_proposals (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    proposal_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    location_id TEXT NOT NULL,
    anchor_location_id TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (world_id, proposal_id),
    UNIQUE (world_id, location_id),
    UNIQUE (world_id, operation_id),
    FOREIGN KEY (world_id, operation_id)
        REFERENCES operations(world_id, operation_id)
) STRICT;

CREATE INDEX idx_world_expansion_proposals_world
    ON world_expansion_proposals(world_id);
