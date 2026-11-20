-- Counts how many times in a row a source lookup has failed for an entry, so a failing entry waits longer before the next try.
ALTER TABLE entry_checks ADD COLUMN failures INTEGER NOT NULL DEFAULT 0;
