-- Scenarios: reusable authoring templates from which worlds are instanced.
-- Scenarios are administrative data, not playable world state: they carry a
-- title, optional description, and long-form story elements. Instancing copies
-- this content into a world; scenarios themselves never change after that.

CREATE TABLE scenarios (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL CHECK (length(trim(title)) > 0),
    description TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE TABLE scenario_elements (
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    element_type TEXT NOT NULL CHECK (
        element_type IN ('author_note', 'plot_essentials', 'opening_scene')
    ),
    content TEXT NOT NULL CHECK (length(trim(content)) BETWEEN 1 AND 20000),
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scenario_id, element_type)
) STRICT;

-- Traceability and exact idempotency for scenario mutations. Scenarios have no
-- revision counter, so the caller operation ID is the only concurrency anchor.
CREATE TABLE scenario_operations (
    scenario_id TEXT NOT NULL REFERENCES scenarios(id) ON DELETE CASCADE,
    operation_id TEXT NOT NULL,
    operation_type TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (scenario_id, operation_id)
) STRICT;
