CREATE TABLE narration_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    world_id TEXT NOT NULL REFERENCES worlds(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL CHECK (revision >= 0),
    role TEXT NOT NULL CHECK (role IN ('player', 'agent')),
    content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 20000),
    occurred_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
) STRICT;

CREATE INDEX idx_narration_history_world
    ON narration_history(world_id, id DESC);
