-- Numbers every entry change and deletion in local order, so a paired machine can ask only for what changed since its last sync.
CREATE TABLE change_counter (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    value INTEGER NOT NULL,
    epoch TEXT NOT NULL
);
INSERT INTO change_counter (id, value, epoch) VALUES (1, (SELECT COALESCE(MAX(id), 0) FROM entries), lower(hex(randomblob(8))));
ALTER TABLE entries ADD COLUMN change_seq INTEGER NOT NULL DEFAULT 0;
UPDATE entries SET change_seq = id;
ALTER TABLE entry_deletions ADD COLUMN change_seq INTEGER NOT NULL DEFAULT 0;
CREATE INDEX IF NOT EXISTS entries_change_seq ON entries (change_seq);
CREATE INDEX IF NOT EXISTS entry_deletions_change_seq ON entry_deletions (change_seq);
CREATE TRIGGER entries_change_insert AFTER INSERT ON entries
BEGIN
    UPDATE change_counter SET value = value + 1 WHERE id = 1;
    UPDATE entries SET change_seq = (SELECT value FROM change_counter WHERE id = 1) WHERE id = new.id;
END;
CREATE TRIGGER entries_change_update AFTER UPDATE OF updated_at, state ON entries
BEGIN
    UPDATE change_counter SET value = value + 1 WHERE id = 1;
    UPDATE entries SET change_seq = (SELECT value FROM change_counter WHERE id = 1) WHERE id = new.id;
END;
CREATE TRIGGER entry_deletions_change AFTER INSERT ON entry_deletions
BEGIN
    UPDATE change_counter SET value = value + 1 WHERE id = 1;
    UPDATE entry_deletions SET change_seq = (SELECT value FROM change_counter WHERE id = 1) WHERE uid = new.uid;
END;
