-- People behind images, their handles across sources, and suggested matches the Operator turned down.
CREATE TABLE IF NOT EXISTS creators (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS creator_handles (
    creator_id INTEGER NOT NULL REFERENCES creators (id) ON DELETE CASCADE,
    kind       TEXT NOT NULL,
    value      TEXT NOT NULL,
    url        TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (kind, value)
);
CREATE INDEX IF NOT EXISTS idx_creator_handles_creator ON creator_handles (creator_id);

CREATE TABLE IF NOT EXISTS creator_rejects (
    name  TEXT NOT NULL,
    kind  TEXT NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (name, kind, value)
);
