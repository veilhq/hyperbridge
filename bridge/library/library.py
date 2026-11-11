"""Entry detail, field edits and discard for the library."""

import base64
import json
import re
import shutil
from datetime import datetime

from bridge.core import db
from bridge.core import storage
from bridge.library import swatches

EDITABLE_FIELDS = ("creator", "publisher", "title", "type", "year")
_MAX_FIELD = 500
MAX_TAGS = 20
MAX_TAG_LENGTH = 40
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
            "source": {name: row[name] for name in ("source_service", "source_ref", "collection", "posted_at")},
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


def parse_tags(raw) -> list[str]:
    """Return clean, de-duplicated tag names from a list or a comma-separated string."""
    items = raw.split(",") if isinstance(raw, str) else list(raw or [])
    names, seen = [], set()
    for item in items:
        name = re.sub(r"\s+", " ", str(item)).strip().lstrip("#")[:MAX_TAG_LENGTH].strip()
        if name and name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    return names[:MAX_TAGS]


def add_entry_tags(conn, entry_id: int, raw_tags) -> None:
    """Add tags to one entry on an open connection, keeping the tags it already has."""
    for name in parse_tags(raw_tags):
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        conn.execute(
            "INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) SELECT ?, id FROM tags WHERE name = ?", (entry_id, name))


def _set_tags(conn, entry_id: int, names: list[str]) -> None:
    """Replace an entry's tags with the given names and drop tags nothing uses."""
    conn.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,))
    for name in names:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        conn.execute(
            "INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) SELECT ?, id FROM tags WHERE name = ?",
            (entry_id, name),
        )
    conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM entry_tags)")


def list_tags() -> list[dict]:
    """Return every tag with the number of entries using it, most used first."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT t.name, COUNT(et.entry_id) AS count FROM tags t LEFT JOIN entry_tags et ON et.tag_id = t.id"
            " GROUP BY t.id ORDER BY count DESC, t.name COLLATE NOCASE"
        ).fetchall()
    finally:
        conn.close()
    return [{"name": row["name"], "count": row["count"]} for row in rows]


def add_tags(entry_ids, raw_tags) -> int:
    """Add tags to every listed entry without touching their other tags; returns how many entries exist."""
    names = parse_tags(raw_tags)
    conn = db.connect()
    try:
        ids = [row["id"] for row in conn.execute(
            f"SELECT id FROM entries WHERE id IN ({','.join('?' * len(entry_ids))})", [int(i) for i in entry_ids]
        )] if entry_ids else []
        for name in names if ids else []:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            for entry_id in ids:
                conn.execute(
                    "INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) SELECT ?, id FROM tags WHERE name = ?",
                    (entry_id, name),
                )
    finally:
        conn.close()
    return len(ids)


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
        if "tags" in fields:
            _set_tags(conn, entry_id, parse_tags(fields["tags"]))
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
