-- Remembers which entries were deleted and when, so a sync removes them from the other machine instead of bringing them back.
CREATE TABLE entry_deletions (
    uid TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL
);
