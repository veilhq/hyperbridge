"""Saved colors: hex values kept on this machine for later, each with an optional name and source image.

A hex is saved once; saving it again returns the existing color and fills in a missing source or name.
Deleting the source image keeps the color and drops the link.
"""

import re
from datetime import datetime

from bridge.core import db

MAX_NAME = 60
_HEX = re.compile(r"^#?([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")


def normalize(value) -> str | None:
    """Return a hex color as uppercase #RRGGBB, expanding #RGB, or None when it is not a hex color."""
    match = _HEX.match(str(value or "").strip())
    if not match:
        return None
    digits = match.group(1)
    if len(digits) == 3:
        digits = "".join(ch * 2 for ch in digits)
    return "#" + digits.upper()


def _clean(name) -> str:
    return " ".join(str(name or "").split())[:MAX_NAME]


def _row(row) -> dict:
    return {"id": row["id"], "hex": row["hex"], "name": row["name"], "entry_id": row["entry_id"], "created_at": row["created_at"]}


def list_colors() -> list:
    """Return every saved color, newest first."""
    conn = db.connect()
    try:
        rows = conn.execute("SELECT * FROM saved_colors ORDER BY created_at DESC, id DESC").fetchall()
    finally:
        conn.close()
    return [_row(row) for row in rows]


def save_color(hex_value, name="", entry_id=None) -> dict:
    """Save a color; returns {"ok": True, "color": {...}, "created": bool} or {"ok": False, "error": "..."}."""
    hex_color = normalize(hex_value)
    if hex_color is None:
        return {"ok": False, "error": "That is not a hex color."}
    name = _clean(name)
    conn = db.connect()
    try:
        if entry_id is not None and conn.execute("SELECT 1 FROM entries WHERE id = ?", (entry_id,)).fetchone() is None:
            entry_id = None
        row = conn.execute("SELECT * FROM saved_colors WHERE hex = ?", (hex_color,)).fetchone()
        created = row is None
        if created:
            cursor = conn.execute(
                "INSERT INTO saved_colors (hex, name, entry_id, created_at) VALUES (?, ?, ?, ?)",
                (hex_color, name, entry_id, datetime.now().isoformat(timespec="seconds")),
            )
            row_id = cursor.lastrowid
        else:
            row_id = row["id"]
            conn.execute(
                "UPDATE saved_colors SET entry_id = COALESCE(entry_id, ?), name = CASE WHEN name = '' THEN ? ELSE name END WHERE id = ?",
                (entry_id, name, row_id),
            )
        saved = conn.execute("SELECT * FROM saved_colors WHERE id = ?", (row_id,)).fetchone()
    finally:
        conn.close()
    return {"ok": True, "color": _row(saved), "created": created}


def rename_color(color_id: int, name) -> dict:
    """Set or clear a saved color's name."""
    conn = db.connect()
    try:
        changed = conn.execute("UPDATE saved_colors SET name = ? WHERE id = ?", (_clean(name), color_id)).rowcount
        row = conn.execute("SELECT * FROM saved_colors WHERE id = ?", (color_id,)).fetchone()
    finally:
        conn.close()
    if not changed:
        return {"ok": False, "error": "That color is gone."}
    return {"ok": True, "color": _row(row)}


def delete_color(color_id: int) -> bool:
    """Delete a saved color. Returns False when it is missing."""
    conn = db.connect()
    try:
        return conn.execute("DELETE FROM saved_colors WHERE id = ?", (color_id,)).rowcount > 0
    finally:
        conn.close()
