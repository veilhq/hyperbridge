-- Gives each set its own tags (a JSON list of phrases) that Find similar searches for and ranks against,
-- and remembers which phrases were searched for a set and when, even when a search found nothing.
ALTER TABLE sets ADD COLUMN tags TEXT NOT NULL DEFAULT '[]';
CREATE TABLE set_searches (
    set_id      INTEGER NOT NULL REFERENCES sets (id) ON DELETE CASCADE,
    phrase      TEXT NOT NULL COLLATE NOCASE,
    searched_at TEXT NOT NULL,
    PRIMARY KEY (set_id, phrase)
);
