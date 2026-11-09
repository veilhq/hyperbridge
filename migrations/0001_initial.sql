-- Entries, assets, sets, tags, jobs and the full-text index.

CREATE TABLE entries (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    uid           TEXT NOT NULL UNIQUE,
    title         TEXT NOT NULL DEFAULT '',
    source_url    TEXT NOT NULL DEFAULT '',
    source_key    TEXT,
    domain        TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    creator       TEXT NOT NULL DEFAULT '',
    publisher     TEXT NOT NULL DEFAULT '',
    type          TEXT NOT NULL DEFAULT '',
    year          TEXT NOT NULL DEFAULT '',
    manual_fields TEXT NOT NULL DEFAULT '[]',
    state         TEXT NOT NULL DEFAULT 'pending'
                  CHECK (state IN ('pending', 'captured', 'failed')),
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX entries_source_key ON entries (source_key) WHERE source_key IS NOT NULL;
CREATE INDEX entries_created ON entries (created_at DESC);
CREATE INDEX entries_state ON entries (state);

CREATE TABLE assets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    entry_id   INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    position   INTEGER NOT NULL DEFAULT 0,
    kind       TEXT NOT NULL CHECK (kind IN ('original', 'thumbnail', 'screenshot')),
    path       TEXT NOT NULL,
    width      INTEGER,
    height     INTEGER,
    bytes      INTEGER,
    UNIQUE (entry_id, position, kind)
);
CREATE INDEX assets_entry ON assets (entry_id, position);

CREATE TABLE sets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL COLLATE NOCASE UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE set_entries (
    set_id    INTEGER NOT NULL REFERENCES sets (id) ON DELETE CASCADE,
    entry_id  INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    placed_at TEXT NOT NULL,
    PRIMARY KEY (set_id, entry_id)
);
CREATE INDEX set_entries_entry ON set_entries (entry_id);

CREATE TABLE tags (
    id   INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL COLLATE NOCASE UNIQUE
);

CREATE TABLE entry_tags (
    entry_id INTEGER NOT NULL REFERENCES entries (id) ON DELETE CASCADE,
    tag_id   INTEGER NOT NULL REFERENCES tags (id) ON DELETE CASCADE,
    PRIMARY KEY (entry_id, tag_id)
);
CREATE INDEX entry_tags_tag ON entry_tags (tag_id);

CREATE TABLE jobs (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    kind       TEXT NOT NULL,
    entry_id   INTEGER REFERENCES entries (id) ON DELETE CASCADE,
    payload    TEXT NOT NULL DEFAULT '{}',
    state      TEXT NOT NULL DEFAULT 'queued'
               CHECK (state IN ('queued', 'running', 'done', 'failed')),
    attempts   INTEGER NOT NULL DEFAULT 0,
    error      TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX jobs_state ON jobs (state, created_at);

-- Full-text index: one row per entry, rowid = entries.id, tags folded in.
CREATE VIRTUAL TABLE entries_fts USING fts5 (
    title, description, domain, creator, publisher, tags,
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TRIGGER entries_fts_insert AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts (rowid, title, description, domain, creator, publisher, tags)
    VALUES (new.id, new.title, new.description, new.domain, new.creator, new.publisher, '');
END;

CREATE TRIGGER entries_fts_update AFTER UPDATE OF title, description, domain, creator, publisher ON entries BEGIN
    UPDATE entries_fts
       SET title = new.title, description = new.description, domain = new.domain,
           creator = new.creator, publisher = new.publisher
     WHERE rowid = new.id;
END;

CREATE TRIGGER entries_fts_delete AFTER DELETE ON entries BEGIN
    DELETE FROM entries_fts WHERE rowid = old.id;
END;

CREATE TRIGGER entry_tags_fts_insert AFTER INSERT ON entry_tags BEGIN
    UPDATE entries_fts
       SET tags = (SELECT COALESCE(group_concat(t.name, ' '), '')
                     FROM entry_tags et JOIN tags t ON t.id = et.tag_id
                    WHERE et.entry_id = new.entry_id)
     WHERE rowid = new.entry_id;
END;

CREATE TRIGGER entry_tags_fts_delete AFTER DELETE ON entry_tags BEGIN
    UPDATE entries_fts
       SET tags = (SELECT COALESCE(group_concat(t.name, ' '), '')
                     FROM entry_tags et JOIN tags t ON t.id = et.tag_id
                    WHERE et.entry_id = old.entry_id)
     WHERE rowid = old.entry_id;
END;

-- Renaming a tag refreshes the index rows of every entry that carries it.
CREATE TRIGGER tags_fts_rename AFTER UPDATE OF name ON tags BEGIN
    UPDATE entries_fts
       SET tags = (SELECT COALESCE(group_concat(t.name, ' '), '')
                     FROM entry_tags et JOIN tags t ON t.id = et.tag_id
                    WHERE et.entry_id = entries_fts.rowid)
     WHERE rowid IN (SELECT entry_id FROM entry_tags WHERE tag_id = new.id);
END;
