CREATE TABLE feed_sources (
    source_id TEXT PRIMARY KEY,
    enabled INTEGER NOT NULL DEFAULT 0,
    api_key TEXT NOT NULL DEFAULT ''
);
