-- Saved colors: hex values kept for later, each with an optional name and the library image it came from.
CREATE TABLE IF NOT EXISTS saved_colors (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    hex        TEXT NOT NULL UNIQUE,
    name       TEXT NOT NULL DEFAULT '',
    entry_id   INTEGER REFERENCES entries(id) ON DELETE SET NULL,
    created_at TEXT NOT NULL
);
