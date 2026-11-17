-- Each stored image keeps the URL it was fetched from and its frame count, animation length and transparency.
ALTER TABLE assets ADD COLUMN source_url TEXT NOT NULL DEFAULT '';
ALTER TABLE assets ADD COLUMN frames INTEGER;
ALTER TABLE assets ADD COLUMN duration_ms INTEGER;
ALTER TABLE assets ADD COLUMN has_alpha INTEGER;
