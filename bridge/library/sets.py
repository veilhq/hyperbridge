"""Sets: named groups of entries. Placing an entry in a set never copies or moves its files."""

import sqlite3
from datetime import datetime

from bridge.core import db

MAX_NAME = 100
MAX_DESCRIPTION = 200


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _clean(name) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME]


def _clean_description(text) -> str:
    return " ".join(str(text or "").split())[:MAX_DESCRIPTION]


def _row(conn, set_id: int) -> dict | None:
    row = conn.execute(
        "SELECT s.id, s.name, s.description, (SELECT COUNT(*) FROM set_entries se WHERE se.set_id = s.id) AS count"
        " FROM sets s WHERE s.id = ?", (set_id,)
    ).fetchone()
    return dict(row) if row else None


def list_sets() -> list[dict]:
    """Return every set with its entry count, ordered by name."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT s.id, s.name, s.description, COUNT(se.entry_id) AS count FROM sets s"
            " LEFT JOIN set_entries se ON se.set_id = s.id GROUP BY s.id ORDER BY s.name COLLATE NOCASE"
        ).fetchall()
        return [dict(row) for row in rows]
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
                conn.execute("UPDATE sets SET name = ? WHERE id = ?", (name, set_id))
            else:
                conn.execute(
                    "UPDATE sets SET name = ?, description = ? WHERE id = ?",
                    (name, _clean_description(description), set_id),
                )
        except sqlite3.IntegrityError:
            return {"ok": False, "error": "That set exists."}
        return {"ok": True, "set": _row(conn, set_id)}
    finally:
        conn.close()


def delete_set(set_id: int) -> bool:
    """Delete a set; its entries stay in the library. Returns False when the set is missing."""
    conn = db.connect()
    try:
        return conn.execute("DELETE FROM sets WHERE id = ?", (set_id,)).rowcount > 0
    finally:
        conn.close()


def place(entry_id: int, set_id: int) -> bool:
    """Place an entry in a set; placing twice is a no-op. False when either is missing."""
    conn = db.connect()
    try:
        has_entry = conn.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if not has_entry or _row(conn, set_id) is None:
            return False
        conn.execute(
            "INSERT OR IGNORE INTO set_entries (set_id, entry_id, placed_at) VALUES (?, ?, ?)",
            (set_id, entry_id, _now()),
        )
        return True
    finally:
        conn.close()


def remove(entry_id: int, set_id: int) -> bool:
    """Take an entry out of a set; the entry stays in the library."""
    conn = db.connect()
    try:
        return conn.execute(
            "DELETE FROM set_entries WHERE set_id = ? AND entry_id = ?", (set_id, entry_id)
        ).rowcount > 0
    finally:
        conn.close()
