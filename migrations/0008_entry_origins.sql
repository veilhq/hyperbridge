-- Where a saved image came from on its source service: block, channel and the channel's own words.
CREATE TABLE IF NOT EXISTS entry_origins (
    entry_id      INTEGER PRIMARY KEY REFERENCES entries (id) ON DELETE CASCADE,
    block_id      INTEGER,
    channel_slug  TEXT NOT NULL DEFAULT '',
    channel_title TEXT NOT NULL DEFAULT '',
    channel_text  TEXT NOT NULL DEFAULT '',
    checked_at    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_entry_origins_block ON entry_origins (block_id);
