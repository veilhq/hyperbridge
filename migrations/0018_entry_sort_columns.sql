-- Stores each entry's color sort position, hue family and year label so color order and grouping page in SQL.
ALTER TABLE entries ADD COLUMN color_rank REAL NOT NULL DEFAULT 2000;
ALTER TABLE entries ADD COLUMN color_family INTEGER NOT NULL DEFAULT 9;
ALTER TABLE entries ADD COLUMN year_label TEXT NOT NULL DEFAULT '';
UPDATE entries SET year_label = hb_entry_year(year, created_at);
UPDATE entries SET color_rank = hb_color_rank(swatches), color_family = hb_color_family(swatches) WHERE swatches != '[]';
CREATE INDEX IF NOT EXISTS entries_color ON entries (color_rank, created_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS entries_color_family ON entries (color_family, color_rank, created_at DESC, id DESC);
CREATE TRIGGER entries_color_insert AFTER INSERT ON entries WHEN new.swatches != '[]'
BEGIN
    UPDATE entries SET color_rank = hb_color_rank(new.swatches), color_family = hb_color_family(new.swatches) WHERE id = new.id;
END;
CREATE TRIGGER entries_color_update AFTER UPDATE OF swatches ON entries WHEN new.swatches IS NOT old.swatches
BEGIN
    UPDATE entries SET color_rank = hb_color_rank(new.swatches), color_family = hb_color_family(new.swatches) WHERE id = new.id;
END;
CREATE TRIGGER entries_year_insert AFTER INSERT ON entries
BEGIN
    UPDATE entries SET year_label = hb_entry_year(new.year, new.created_at) WHERE id = new.id;
END;
CREATE TRIGGER entries_year_update AFTER UPDATE OF year, created_at ON entries
BEGIN
    UPDATE entries SET year_label = hb_entry_year(new.year, new.created_at) WHERE id = new.id;
END;
