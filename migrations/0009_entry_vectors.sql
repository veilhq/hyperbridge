-- Image embeddings per entry (model id and dimension kept so a model swap is a re-index) and a similarity score per feed item.
CREATE TABLE IF NOT EXISTS entry_vectors (
    entry_id   INTEGER PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    model      TEXT NOT NULL,
    dim        INTEGER NOT NULL,
    vector     BLOB NOT NULL,
    created_at TEXT NOT NULL
);

ALTER TABLE feed_items ADD COLUMN score REAL;
