-- Gives each set a stable id and edit time, and remembers deleted sets, so a sync can rename or delete a set instead of duplicating it.
ALTER TABLE sets ADD COLUMN uid TEXT NOT NULL DEFAULT '';
ALTER TABLE sets ADD COLUMN updated_at TEXT NOT NULL DEFAULT '';
UPDATE sets SET uid = lower(hex(randomblob(16))), updated_at = created_at;
CREATE UNIQUE INDEX sets_uid ON sets (uid);
CREATE TRIGGER sets_identity AFTER INSERT ON sets WHEN NEW.uid = ''
BEGIN
    UPDATE sets SET uid = lower(hex(randomblob(16))), updated_at = CASE WHEN NEW.updated_at = '' THEN NEW.created_at ELSE NEW.updated_at END WHERE id = NEW.id;
END;
CREATE TABLE set_deletions (
    uid TEXT PRIMARY KEY,
    deleted_at TEXT NOT NULL
);
