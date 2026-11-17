-- Each feed image records the AI-generation label found in its file ('' when none) and whether it has been checked.
ALTER TABLE feed_items ADD COLUMN ai_label TEXT NOT NULL DEFAULT '';
ALTER TABLE feed_items ADD COLUMN ai_checked INTEGER NOT NULL DEFAULT 0;
