-- Drops the image-embedding table, the per-source switch and key table, and the feed similarity score; none are used any more.
DROP TABLE IF EXISTS entry_vectors;
DROP TABLE IF EXISTS feed_sources;
ALTER TABLE feed_items DROP COLUMN score;
