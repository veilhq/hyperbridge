-- Scratch boards: freeform canvases kept on this machine only, each stored as one JSON Canvas document.
CREATE TABLE IF NOT EXISTS boards (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    name       TEXT NOT NULL,
    doc        TEXT NOT NULL DEFAULT '{"nodes": [], "edges": []}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
