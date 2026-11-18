-- When each followed source was last read for its newest posts, and small named marks such as the last Latest visit.
ALTER TABLE followed_sources ADD COLUMN checked_at TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS feed_marks (
    name  TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
