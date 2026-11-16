-- Originals carry an exact content hash and a perceptual difference hash so duplicate images can be found across entries.
ALTER TABLE assets ADD COLUMN sha256 TEXT;
ALTER TABLE assets ADD COLUMN dhash INTEGER;
