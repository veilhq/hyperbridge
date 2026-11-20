-- Trail rows in feed_items, the places a trail has checked, and fields hops need, stored when images are pulled.
ALTER TABLE feed_items ADD COLUMN trail TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN source_link TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN creator_handle TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN reblog_from TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN reblog_root TEXT NOT NULL DEFAULT '';
ALTER TABLE entries ADD COLUMN source_link TEXT NOT NULL DEFAULT '';
ALTER TABLE entries ADD COLUMN creator_handle TEXT NOT NULL DEFAULT '';
ALTER TABLE entries ADD COLUMN reblog_from TEXT NOT NULL DEFAULT '';
ALTER TABLE entries ADD COLUMN reblog_root TEXT NOT NULL DEFAULT '';
CREATE INDEX IF NOT EXISTS idx_feed_items_trail ON feed_items (trail) WHERE trail != '';

CREATE TABLE IF NOT EXISTS trail_places (
    url        TEXT PRIMARY KEY,
    kind       TEXT NOT NULL,
    label      TEXT NOT NULL DEFAULT '',
    count      INTEGER NOT NULL DEFAULT 0,
    feed_url   TEXT NOT NULL DEFAULT '',
    next_page  TEXT NOT NULL DEFAULT '',
    images     TEXT NOT NULL DEFAULT '[]',
    extra      TEXT NOT NULL DEFAULT '[]',
    checked_at TEXT NOT NULL
);
