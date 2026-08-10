-- World-owned copies of story elements. Instancing a world from a scenario
-- copies the scenario's elements here; afterwards the world and the scenario
-- diverge independently. Each row links to the event that created or updated
-- it, mirroring the resources / location_properties ledgers.

CREATE TABLE world_elements (
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    element_type TEXT NOT NULL CHECK (
        element_type IN ('author_note', 'plot_essentials', 'opening_scene')
    ),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 20000),
    updated_event_id TEXT NOT NULL REFERENCES events(id) ON DELETE RESTRICT,
    PRIMARY KEY (world_id, element_type)
) STRICT;

CREATE INDEX idx_world_elements_world ON world_elements(world_id);
