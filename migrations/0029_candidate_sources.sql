-- Which source each feed image was pulled from, and the sources Discover finds on its own before the Operator follows them.
ALTER TABLE feed_items ADD COLUMN origin_url TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_feed_items_origin ON feed_items (origin_url, state);
CREATE TABLE IF NOT EXISTS candidate_sources (
    url       TEXT PRIMARY KEY,
    label     TEXT NOT NULL DEFAULT '',
    found_by  TEXT NOT NULL,
    strength  REAL NOT NULL DEFAULT 0,
    state     TEXT NOT NULL DEFAULT 'candidate',
    found_at  TEXT NOT NULL,
    pulled_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_candidate_sources_state ON candidate_sources (state);
