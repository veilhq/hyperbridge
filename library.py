"""Entry detail, field edits and discard for the library."""

import base64
import json
import re
import shutil
from datetime import datetime

import db
import storage
import swatches

EDITABLE_FIELDS = ("creator", "publisher", "title", "type", "year")
_MAX_FIELD = 500
_MIME = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}
_DISPLAY_ORDER = {"original": 0, "screenshot": 1, "thumbnail": 2}


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _manual(raw) -> list[str]:
    """Parse the stored manual_fields JSON, tolerating bad data."""
    try:
        value = json.loads(raw or "[]")
    except ValueError:
        return []
    return [name for name in value if name in EDITABLE_FIELDS] if isinstance(value, list) else []


def _display_assets(conn, entry_id: int) -> list[dict]:
    """Return one asset per position, preferring original, then screenshot, then thumbnail."""
    rows = conn.execute(
        "SELECT id, position, kind, width, height FROM assets WHERE entry_id = ? ORDER BY position", (entry_id,)
    ).fetchall()
    best: dict[int, dict] = {}
    for row in rows:
        current = best.get(row["position"])
        if current is None or _DISPLAY_ORDER[row["kind"]] < _DISPLAY_ORDER[current["kind"]]:
            best[row["position"]] = dict(row)
    return [
        {"id": item["id"], "kind": item["kind"], "width": item["width"], "height": item["height"]}
        for _, item in sorted(best.items())
    ]


def get_entry(entry_id: int) -> dict | None:
    """Return one entry's fields, manual field names, assets, tags and sets, or None when missing."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            return None
        tags = [
            r[0] for r in conn.execute(
                "SELECT t.name FROM entry_tags et JOIN tags t ON t.id = et.tag_id"
                " WHERE et.entry_id = ? ORDER BY t.name COLLATE NOCASE", (entry_id,)
            )
        ]
        sets = [
            {"id": r["id"], "name": r["name"]} for r in conn.execute(
                "SELECT s.id, s.name FROM set_entries se JOIN sets s ON s.id = se.set_id"
                " WHERE se.entry_id = ? ORDER BY s.name COLLATE NOCASE", (entry_id,)
            )
        ]
        return {
            "id": row["id"],
            "state": row["state"],
            "source_url": row["source_url"],
            "domain": row["domain"],
            "manual": _manual(row["manual_fields"]),
            "assets": _display_assets(conn, entry_id),
            "tags": tags,
            "sets": sets,
            "swatches": swatches.parse(row["swatches"]),
            **{name: row[name] for name in EDITABLE_FIELDS},
        }
    finally:
        conn.close()


def get_asset_uri(asset_id: int) -> str | None:
    """Return a data URI for a stored asset, or None when the row or file is missing."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT path FROM assets WHERE id = ?", (asset_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    root = db.data_dir().resolve()
    path = (root / row["path"]).resolve()
    if root not in path.parents:
        return None
    try:
        raw = path.read_bytes()
    except OSError:
        return None
    mime = _MIME.get(path.suffix.lower(), "application/octet-stream")
    return f"data:{mime};base64,{base64.b64encode(raw).decode('ascii')}"


def update_entry(entry_id: int, fields: dict) -> dict | None:
    """Save edited fields, mark changed ones manual, and lift a failed entry to captured."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            return None
        manual = _manual(row["manual_fields"])
        changes = {}
        for name in EDITABLE_FIELDS:
            if name not in fields:
                continue
            value = str(fields[name] or "").strip()[:_MAX_FIELD]
            if value != row[name]:
                changes[name] = value
                if name not in manual:
                    manual.append(name)
        state = "captured" if row["state"] == "failed" else row["state"]
        if changes or state != row["state"]:
            assignments = ", ".join(f"{name} = ?" for name in changes)
            conn.execute(
                f"UPDATE entries SET {assignments + ', ' if assignments else ''}"
                "manual_fields = ?, state = ?, updated_at = ? WHERE id = ?",
                (*changes.values(), json.dumps(manual), state, _now(), entry_id),
            )
    finally:
        conn.close()
    return get_entry(entry_id)


def discard_entry(entry_id: int) -> bool:
    """Delete an entry, its queued jobs and its asset folder; returns False when it is missing."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT uid FROM entries WHERE id = ?", (entry_id,)).fetchone()
        if row is None:
            return False
        conn.execute("DELETE FROM jobs WHERE entry_id = ?", (entry_id,))
        conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
        uid = row["uid"]
    finally:
        conn.close()
    shutil.rmtree(storage.entry_dir(uid), ignore_errors=True)
    return True


def _slug(text: str) -> str:
    """Return a short filename-safe slug, or 'entry' when nothing usable remains."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", text or "").strip("-")[:60]
    return slug or "entry"


def _inside_data(relative: str):
    """Resolve a stored relative path, refusing anything outside the data folder."""
    root = db.data_dir().resolve()
    path = (root / relative).resolve()
    return path if root in path.parents and path.is_file() else None


def asset_file(asset_id: int):
    """Return (source path, suggested file name) for one asset, or None when unavailable."""
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT a.path, a.position, e.title, e.domain FROM assets a JOIN entries e ON e.id = a.entry_id"
            " WHERE a.id = ?", (asset_id,)
        ).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    path = _inside_data(row["path"])
    if path is None:
        return None
    return path, f"{_slug(row['title'] or row['domain'])}-{row['position'] + 1}{path.suffix.lower()}"


def entry_files(entry_id: int) -> list:
    """Return (source path, suggested file name) for each displayed asset of an entry."""
    entry = get_entry(entry_id)
    if entry is None:
        return []
    return [found for found in (asset_file(item["id"]) for item in entry["assets"]) if found]


def entries_files(entry_ids) -> list:
    """Return the downloadable (source path, file name) pairs for several entries."""
    files = []
    for entry_id in entry_ids:
        files.extend(entry_files(int(entry_id)))
    return files


def copy_files(files, folder) -> int:
    """Copy files into a folder, adding a numeric suffix rather than overwriting; returns the count."""
    from pathlib import Path

    target = Path(folder)
    if not target.is_dir():
        return 0
    count = 0
    for source, name in files:
        dest = target / name
        stem, suffix, n = Path(name).stem, Path(name).suffix, 1
        while dest.exists():
            n += 1
            dest = target / f"{stem}-{n}{suffix}"
        shutil.copyfile(source, dest)
        count += 1
    return count
