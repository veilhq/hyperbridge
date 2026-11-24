"""Entry detail, field edits and discard for the library."""

import base64
import json
import re
import shutil
from datetime import datetime

from bridge.core import db
from bridge.core import storage
from bridge.core import thumbserver
from bridge.ingest import capture
from bridge.library import fingerprints
from bridge.library import swatches

EDITABLE_FIELDS = ("creator", "publisher", "title", "type", "year", "description")
_MAX_FIELD = 500
MAX_DESCRIPTION = 1000
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
    return [name for name in value if name in EDITABLE_FIELDS or name == "tags"] if isinstance(value, list) else []


def _clean_field(name: str, value) -> str:
    """Trim an edited value and cap its length; descriptions keep their line breaks."""
    text = str(value or "").replace("\r\n", "\n").strip()
    return text[:MAX_DESCRIPTION] if name == "description" else text[:_MAX_FIELD]


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
        failure = ""
        if row["state"] == "failed":
            job = conn.execute("SELECT error FROM jobs WHERE entry_id = ? ORDER BY id DESC LIMIT 1", (entry_id,)).fetchone()
            failure = capture.failure_reason(job["error"] if job else "")
        return {
            "id": row["id"],
            "state": row["state"],
            "failure": failure,
            "source_url": row["source_url"],
            "domain": row["domain"],
            "manual": _manual(row["manual_fields"]),
            "assets": _display_assets(conn, entry_id),
            "tags": tags,
            "sets": sets,
            "duplicates": fingerprints.duplicates(conn, entry_id),
            "swatches": swatches.parse(row["swatches"]),
            "source": {name: row[name] for name in ("source_service", "source_ref", "collection", "posted_at")},
            **{name: row[name] for name in EDITABLE_FIELDS},
        }
    finally:
        conn.close()


def get_asset_uri(asset_id: int) -> str | None:
    """Return a loopback URL (else a data URI) for a stored asset, or None when the row or file is missing."""
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
    url = thumbserver.url_for(row["path"])
    if url:
        return url
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


def known_terms(conn, raw_tags) -> list[str]:
    """Return the names that match a tag already in the library, as that tag is spelled; a plural matches its singular and back.

    Number-only names are dropped, and a name with no matching tag never creates one.
    """
    names = []
    for word in parse_tags(raw_tags):
        if NUMBER_ONLY.fullmatch(word):
            continue
        for form in tag_forms(word):
            row = conn.execute("SELECT name FROM tags WHERE name = ?", (form,)).fetchone()
            if row and row["name"] not in names:
                names.append(row["name"])
                break
    return names


def apply_known_tags(conn, entry_id: int, raw_tags) -> list[str]:
    """Add to one entry only the names that match an existing tag; returns the tags added."""
    names = known_terms(conn, raw_tags)
    add_entry_tags(conn, entry_id, names)
    return names


def _set_tags(conn, entry_id: int, names: list[str]) -> None:
    """Replace an entry's tags with the given names; tags nothing uses stay in the vocabulary."""
    conn.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,))
    for name in names:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
        conn.execute(
            "INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) SELECT ?, id FROM tags WHERE name = ?",
            (entry_id, name),
        )


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
        changed = set()
        for name in names if ids else []:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
            for entry_id in ids:
                if conn.execute(
                    "INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) SELECT ?, id FROM tags WHERE name = ?",
                    (entry_id, name),
                ).rowcount:
                    changed.add(entry_id)
        _retag(conn, sorted(changed))
    finally:
        conn.close()
    return len(ids)


def remove_tags(entry_ids, name: str) -> int:
    """Take one tag off every listed entry, keeping the tag in the vocabulary; returns how many entries lost it."""
    ids = [int(i) for i in entry_ids or []]
    conn = db.connect()
    try:
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (str(name),)).fetchone()
        if row is None or not ids:
            return 0
        held = [entry_id for entry_id in _tag_entries(conn, row["id"]) if entry_id in ids]
        if held:
            conn.execute(f"DELETE FROM entry_tags WHERE tag_id = ? AND entry_id IN ({','.join('?' * len(held))})",
                         (row["id"], *held))
            _retag(conn, held)
    finally:
        conn.close()
    return len(held)


def create_tag(name: str) -> dict:
    """Add a term to the tag vocabulary; an existing tag of the same name (any case) is reused."""
    names = parse_tags([name])
    if not names or NUMBER_ONLY.fullmatch(names[0]):
        return {"ok": False, "error": "Enter a tag name."}
    conn = db.connect()
    try:
        existed = conn.execute("SELECT name FROM tags WHERE name = ?", (names[0],)).fetchone()
        if existed is None:
            conn.execute("INSERT INTO tags (name) VALUES (?)", (names[0],))
    finally:
        conn.close()
    return {"ok": True, "name": existed["name"] if existed else names[0], "existed": existed is not None}


def tag_counts(entry_ids) -> dict:
    """Return how many of the listed entries carry each tag, for tags at least one of them has."""
    ids = [int(i) for i in entry_ids or []]
    if not ids:
        return {}
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT t.name, COUNT(*) AS count FROM entry_tags et JOIN tags t ON t.id = et.tag_id"
            f" WHERE et.entry_id IN ({','.join('?' * len(ids))}) GROUP BY t.id", ids).fetchall()
    finally:
        conn.close()
    return {row["name"]: row["count"] for row in rows}


def _retag(conn, entry_ids) -> None:
    """Stamp entries whose tags just changed so a sync carries the change, and mark their tags as hand-managed."""
    now = _now()
    for entry_id in entry_ids:
        row = conn.execute("SELECT manual_fields FROM entries WHERE id = ?", (entry_id,)).fetchone()
        manual = _manual(row["manual_fields"])
        if "tags" not in manual:
            manual.append("tags")
        conn.execute("UPDATE entries SET manual_fields = ?, updated_at = ? WHERE id = ?", (json.dumps(manual), now, entry_id))


def _tag_entries(conn, tag_id) -> list[int]:
    """Return the ids of the entries carrying a tag."""
    return [row[0] for row in conn.execute("SELECT entry_id FROM entry_tags WHERE tag_id = ?", (tag_id,))]


def rename_tag(old: str, new: str) -> dict:
    """Rename a tag everywhere; when the new name is another existing tag the two merge into it."""
    names = parse_tags([new])
    if not names:
        return {"ok": False, "error": "Enter a tag name."}
    name = names[0]
    conn = db.connect()
    try:
        source = conn.execute("SELECT id, name FROM tags WHERE name = ?", (str(old),)).fetchone()
        if source is None:
            return {"ok": False, "error": "That tag no longer exists."}
        target = conn.execute("SELECT id FROM tags WHERE name = ?", (name,)).fetchone()
        entry_ids = _tag_entries(conn, source["id"])
        merged = target is not None and target["id"] != source["id"]
        if merged:
            conn.execute(
                "INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) SELECT entry_id, ? FROM entry_tags WHERE tag_id = ?",
                (target["id"], source["id"]))
            conn.execute("DELETE FROM entry_tags WHERE tag_id = ?", (source["id"],))
            conn.execute("DELETE FROM tags WHERE id = ?", (source["id"],))
        elif source["name"] != name:
            conn.execute("UPDATE tags SET name = ? WHERE id = ?", (name, source["id"]))
        _retag(conn, entry_ids)
    finally:
        conn.close()
    return {"ok": True, "merged": merged, "count": len(entry_ids)}


def delete_tag(name: str) -> int:
    """Remove a tag from every entry and return how many entries had it."""
    conn = db.connect()
    try:
        row = conn.execute("SELECT id FROM tags WHERE name = ?", (str(name),)).fetchone()
        if row is None:
            return 0
        entry_ids = _tag_entries(conn, row["id"])
        conn.execute("DELETE FROM entry_tags WHERE tag_id = ?", (row["id"],))
        conn.execute("DELETE FROM tags WHERE id = ?", (row["id"],))
        _retag(conn, entry_ids)
    finally:
        conn.close()
    return len(entry_ids)


NUMBER_ONLY = re.compile(r"[\d\s.,:/-]+")


def tag_forms(name) -> list[str]:
    """Return a tag name lowercased, then its singular when it ends in s, else its plural."""
    lower = str(name).lower()
    return [lower, lower[:-1] if lower.endswith("s") and len(lower) > 3 else lower + "s"]


def _tidy_plan(conn) -> dict:
    """List the number-only tags and the plural tags whose singular is also a tag, as [plural, singular] pairs."""
    names = [row["name"] for row in conn.execute("SELECT name FROM tags ORDER BY name COLLATE NOCASE")]
    present = {name.lower(): name for name in names}
    numbers, merges = [], []
    for name in names:
        if NUMBER_ONLY.fullmatch(name):
            numbers.append(name)
            continue
        singular = tag_forms(name)[1]
        if name.lower().endswith("s") and singular in present and not NUMBER_ONLY.fullmatch(singular):
            merges.append([name, present[singular]])
    return {"numbers": numbers, "merges": merges}


def tidy_tags(apply=False) -> dict:
    """Find, and with apply carry out, the tag cleanup: delete number-only tags and merge each plural into its singular.

    Returns the plan: {"numbers": [...], "merges": [[plural, singular], ...]}.
    """
    conn = db.connect()
    try:
        plan = _tidy_plan(conn)
    finally:
        conn.close()
    if apply:
        for name in plan["numbers"]:
            delete_tag(name)
        for plural, singular in plan["merges"]:
            rename_tag(plural, singular)
    return plan


def delete_single_use_tags() -> int:
    """Remove every tag that only one entry carries and return how many tags went."""
    conn = db.connect()
    try:
        rows = conn.execute(
            "SELECT tag_id FROM entry_tags GROUP BY tag_id HAVING COUNT(*) = 1").fetchall()
        for row in rows:
            entry_ids = _tag_entries(conn, row["tag_id"])
            conn.execute("DELETE FROM entry_tags WHERE tag_id = ?", (row["tag_id"],))
            conn.execute("DELETE FROM tags WHERE id = ?", (row["tag_id"],))
            _retag(conn, entry_ids)
    finally:
        conn.close()
    return len(rows)


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
            value = _clean_field(name, fields[name])
            if value != row[name]:
                changes[name] = value
                if name not in manual:
                    manual.append(name)
        tags_changed = False
        if "tags" in fields:
            before = {item[0] for item in conn.execute(
                "SELECT t.name FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE et.entry_id = ?", (entry_id,))}
            wanted = parse_tags(fields["tags"])
            tags_changed = before != set(wanted)
            if tags_changed and "tags" not in manual:
                manual.append("tags")
            _set_tags(conn, entry_id, wanted)
        state = "captured" if row["state"] == "failed" else row["state"]
        if changes or tags_changed or state != row["state"]:
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
    """Delete an entry, its queued jobs and its asset folder, noting the deletion for sync; returns False when it is missing."""
    return discard_entries([entry_id]) == [entry_id]


def discard_entries(entry_ids) -> list[int]:
    """Delete entries, their queued jobs and asset folders in one transaction, noting each deletion for sync; returns the ids deleted."""
    conn = db.connect()
    removed = []
    try:
        conn.execute("BEGIN IMMEDIATE")
        try:
            stamp = _now()
            for entry_id in entry_ids:
                row = conn.execute("SELECT uid, state FROM entries WHERE id = ?", (entry_id,)).fetchone()
                if row is None:
                    continue
                conn.execute("DELETE FROM jobs WHERE entry_id = ?", (entry_id,))
                conn.execute("DELETE FROM entries WHERE id = ?", (entry_id,))
                if row["state"] != "pending":
                    conn.execute("INSERT OR REPLACE INTO entry_deletions (uid, deleted_at) VALUES (?, ?)", (row["uid"], stamp))
                removed.append((entry_id, row["uid"]))
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise
    finally:
        conn.close()
    for _, uid in removed:
        shutil.rmtree(storage.entry_dir(uid), ignore_errors=True)
    return [entry_id for entry_id, _ in removed]


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
