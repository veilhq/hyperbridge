-- Carries a feed image's description and source site onto the entry it becomes, and remembers which entries a source lookup has already read.
ALTER TABLE feed_items ADD COLUMN description TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN publisher TEXT NOT NULL DEFAULT '';
CREATE TABLE IF NOT EXISTS entry_checks (
    entry_id   INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    step       TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    PRIMARY KEY (entry_id, step)
);
