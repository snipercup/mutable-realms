-- Worlds become instances: they can carry their own description and remember
-- the scenario they were instanced from. The scenario reference is
-- informational — the world owns its copied content and survives the
-- scenario's removal (ON DELETE SET NULL).

ALTER TABLE worlds ADD COLUMN description TEXT;
ALTER TABLE worlds ADD COLUMN source_scenario_id TEXT REFERENCES scenarios(id) ON DELETE SET NULL;
