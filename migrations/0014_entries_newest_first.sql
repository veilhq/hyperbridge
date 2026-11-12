-- Serves the default newest-first grid order straight from the index, so a page never sorts the whole library.
CREATE INDEX IF NOT EXISTS entries_newest ON entries (created_at DESC, id DESC);
