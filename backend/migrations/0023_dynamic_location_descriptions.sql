-- Preserve the generated discovery description while allowing durable state updates.
ALTER TABLE locations ADD COLUMN current_description TEXT
    CHECK (current_description IS NULL OR length(trim(current_description)) BETWEEN 1 AND 5000);
