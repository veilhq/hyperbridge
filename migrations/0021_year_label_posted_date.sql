-- Year labels fall back to the date the source posted an entry before the date it was saved.
DROP TRIGGER IF EXISTS entries_year_insert;
DROP TRIGGER IF EXISTS entries_year_update;
UPDATE entries SET year_label = hb_entry_year(year, created_at, posted_at);
CREATE TRIGGER entries_year_insert AFTER INSERT ON entries
BEGIN
    UPDATE entries SET year_label = hb_entry_year(new.year, new.created_at, new.posted_at) WHERE id = new.id;
END;
CREATE TRIGGER entries_year_update AFTER UPDATE OF year, created_at, posted_at ON entries
BEGIN
    UPDATE entries SET year_label = hb_entry_year(new.year, new.created_at, new.posted_at) WHERE id = new.id;
END;
