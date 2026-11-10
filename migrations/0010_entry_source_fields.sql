-- Where and when a saved image was posted, and the collection it came from, carried over from the discovery sources.
ALTER TABLE entries ADD COLUMN source_service TEXT NOT NULL DEFAULT '';
ALTER TABLE entries ADD COLUMN source_ref TEXT NOT NULL DEFAULT '';
ALTER TABLE entries ADD COLUMN collection TEXT NOT NULL DEFAULT '';
ALTER TABLE entries ADD COLUMN posted_at TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN source_ref TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN collection TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN posted_at TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN tags TEXT NOT NULL DEFAULT '[]';
CREATE INDEX IF NOT EXISTS idx_entries_source_ref ON entries (source_service, source_ref);
