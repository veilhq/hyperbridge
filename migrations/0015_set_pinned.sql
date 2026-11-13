-- Lets a set be pinned as a tab in the top strip; the choice stays on this machine.
ALTER TABLE sets ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
