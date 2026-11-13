"""Sets: named groups of entries. Placing an entry in a set never copies or moves its files."""

import sqlite3
from datetime import datetime

from bridge.core import db
from bridge.library import swatches

MAX_NAME = 100
MAX_DESCRIPTION = 200
PALETTE_SIZE = 5


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(name) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME]


def _clean_description(text) -> str:
    return " ".join(str(text or "").split())[:MAX_DESCRIPTION]


def _row(conn, set_id: int) -> dict | None:
    row = conn.execute(
        "SELECT s.id, s.name, s.description, s.pinned, (SELECT COUNT(*) FROM set_entries se WHERE se.set_id = s.id) AS count"
        " FROM sets s WHERE s.id = ?", (set_id,)
    ).fetchone()
    return dict(row) if row else None


def _palette(rows) -> list[str]:
    """Pick up to PALETTE_SIZE colors: the lead swatch of each newest entry, topped up from the newest entry's own."""
    colors: list[str] = []
    for row in rows:
        values = swatches.parse(row["swatches"])
        if values and values[0] not in colors:
            colors.append(values[0])
    if rows and len(colors) < PALETTE_SIZE:
        for value in swatches.parse(rows[0]["swatches"]):
            if value not in colors:
                colors.append(value)
    return colors[:PALETTE_SIZE]


def list_sets() -> list[dict]:
    """Return every set, ordered by name, with its entry count, pin, last-change time, cover thumbnail path and palette."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT s.id, s.name, s.description, s.pinned, s.updated_at, COUNT(se.entry_id) AS count,"
            " MAX(se.placed_at) AS placed_at FROM sets s"
            " LEFT JOIN set_entries se ON se.set_id = s.id GROUP BY s.id ORDER BY s.name COLLATE NOCASE"
        ).fetchall()
        result = []
        for row in rows:
            newest = conn.execute(
                "SELECT e.swatches, a.path AS thumb_path FROM set_entries se JOIN entries e ON e.id = se.entry_id"
                " LEFT JOIN assets a ON a.entry_id = e.id AND a.kind = 'thumbnail' AND a.position = 0"
                " WHERE se.set_id = ? ORDER BY se.placed_at DESC, e.id DESC LIMIT ?", (row["id"], PALETTE_SIZE)
            ).fetchall()
            cover = next((item["thumb_path"] for item in newest if item["thumb_path"]), None)
            result.append({
                "id": row["id"], "name": row["name"], "description": row["description"], "count": row["count"],
                "pinned": bool(row["pinned"]), "updated": max(row["updated_at"] or "", row["placed_at"] or ""),
                "cover_path": cover, "palette": _palette(newest),
            })
        return result
    finally:
        conn.close()


def create_set(name, description="") -> dict:
    """Create a set; returns {"ok": True, "set": {...}} or {"ok": False, "error": "..."}."""
    name = _clean(name)
    if not name:
        return {"ok": False, "error": "Name the set."}
    conn = db.connect()
    try:
        try:
            cursor = conn.execute(
                "INSERT INTO sets (name, description, created_at) VALUES (?, ?, ?)",
                (name, _clean_description(description), _now()),
            )
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "That set exists."}
        return {"ok": True, "set": _row(conn, cursor.lastrowid)}
    finally:
        conn.close()


def rename_set(set_id: int, name, description=None) -> dict:
    """Rename a set and, when given, replace its description; same result shape as create_set."""
    name = _clean(name)
    if not name:
        return {"ok": False, "error": "Name the set."}
    conn = db.connect()
    try:
        if _row(conn, set_id) is None:
            return {"ok": False, "error": "Set not found."}
        try:
            if description is None:
                conn.execute("UPDATE sets SET name = ?, updated_at = ? WHERE id = ?", (name, _now(), set_id))
            else:
                conn.execute(
                    "UPDATE sets SET name = ?, description = ?, updated_at = ? WHERE id = ?",
                    (name, _clean_description(description), _now(), set_id),
                )
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "That set exists."}
        return {"ok": True, "set": _row(conn, set_id)}
    finally:
        conn.close()


def set_pinned(set_id: int, pinned: bool) -> bool:
    """Pin or unpin a set as a tab on this machine. Returns False when the set is missing."""
    conn = db.connect()
    try:
        return conn.execute("UPDATE sets SET pinned = ? WHERE id = ?", (1 if pinned else 0, set_id)).rowcount > 0
    finally:
        conn.close()


def delete_set(set_id: int) -> bool:
    """Delete a set, noting the deletion for sync; its entries stay in the library. Returns False when the set is missing."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT uid FROM sets WHERE id = ?", (set_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM sets WHERE id = ?", (set_id,))
        conn.execute("INSERT OR REPLACE INTO set_deletions (uid, deleted_at) VALUES (?, ?)", (row["uid"], _now()))
        return True
    finally:
        conn.close()


def place(entry_id: int, set_id: int) -> bool:
    """Place an entry in a set; placing twice is a no-op. False when either is missing."""
    conn = db.connect()
    try:
        has_entry = conn.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not has_entry or _row(conn, set_id) is None:
            return False
        added = conn.execute(
            "INSERT OR IGNORE INTO set_entries (set_id, entry_id, placed_at) VALUES (?, ?, ?)",
            (set_id, entry_id, _now()),
        ).rowcount
        if added:
            conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (_now(), entry_id))
        return True
    finally:
        conn.close()


def remove(entry_id: int, set_id: int) -> bool:
    """Take an entry out of a set; the entry stays in the library."""
    conn = db.connect()
    try:
        removed = conn.execute(
            "DELETE FROM set_entries WHERE set_id = ? AND entry_id = ?", (set_id, entry_id)
        ).rowcount > 0
        if removed:
            conn.execute("UPDATE entries SET updated_at = ? WHERE id = ?", (_now(), entry_id))
        return removed
    finally:
        conn.close()
