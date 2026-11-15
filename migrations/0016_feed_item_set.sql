-- Marks feed images found by searching for one set, so they show in that set's Find similar and not in Discover.
ALTER TABLE feed_items ADD COLUMN set_id INTEGER REFERENCES sets (id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_feed_items_set ON feed_items (set_id, state);
