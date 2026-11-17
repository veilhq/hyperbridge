-- Are.na channels that also hold a set's images, with how many of the set's blocks each shares and its size.
CREATE TABLE IF NOT EXISTS set_neighbors (
    set_id     INTEGER NOT NULL REFERENCES sets (id) ON DELETE CASCADE,
    slug       TEXT NOT NULL,
    url        TEXT NOT NULL,
    title      TEXT NOT NULL DEFAULT '',
    shared     INTEGER NOT NULL DEFAULT 0,
    length     INTEGER NOT NULL DEFAULT 0,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (set_id, slug)
);
