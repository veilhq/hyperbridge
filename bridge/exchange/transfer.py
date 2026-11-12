"""Library export and import: one zip holds every entry's fields, tags, sets and image files."""

import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

from bridge.core import db
from bridge.core import storage

FORMAT = 1
MANIFEST = "library.json"
MAX_MEMBER_BYTES = 200_000_000
_MEMBER = re.compile(r"^assets/[0-9a-f]{2}/([0-9a-f]{32})/(original|thumbnail|screenshot)-(\d+)\.([a-z0-9]{1,8})$")
_FIELDS = (
    "uid", "title", "source_url", "source_key", "domain", "description", "creator", "publisher", "type", "year",
    "manual_fields", "state", "created_at", "updated_at", "swatches", "source_service", "source_ref", "collection",
    "posted_at",
)


_EDITED = ("title", "description", "creator", "publisher", "type", "year", "manual_fields")


class TransferError(Exception):
    """A library file that cannot be read or does not fit this version."""


def _entry_record(conn, row) -> dict:
    """Return one entry as a plain record with its tags and the asset files that exist on disk."""
    record = {name: row[name] for name in _FIELDS}
    record["tags"] = [
        item[0] for item in conn.execute(
            "SELECT t.name FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE et.entry_id = ? ORDER BY t.name",
            (row["id"],),
        )
    ]
    record["assets"] = []
    for asset in conn.execute(
        "SELECT position, kind, path, width, height, bytes FROM assets WHERE entry_id = ? ORDER BY position, kind",
        (row["id"],),
    ):
        if (db.data_dir() / asset["path"]).is_file():
            record["assets"].append({name: asset[name] for name in ("position", "kind", "path", "width", "height", "bytes")})
    return record


def list_keys(conn) -> list[dict]:
    """Return the uid, source key and last edit time of every captured or failed entry, for deciding what another library lacks or has newer."""
    return [
        {"uid": row["uid"], "source_key": row["source_key"], "updated_at": row["updated_at"]}
        for row in conn.execute("SELECT uid, source_key, updated_at FROM entries WHERE state != 'pending' ORDER BY id")
    ]


def export_library(conn, dest, only_uids=None) -> dict:
    """Write captured entries (all, or only_uids), their sets, tags and followed sources plus images to a zip."""
    entries = [
        _entry_record(conn, row)
        for row in conn.execute(f"SELECT id, {', '.join(_FIELDS)} FROM entries WHERE state != 'pending' ORDER BY id")
        if only_uids is None or row["uid"] in only_uids
    ]
    included = {record["uid"] for record in entries}
    sets = []
    for row in conn.execute("SELECT id, uid, name, description, created_at, updated_at FROM sets ORDER BY id"):
        placed = [
            item for item in conn.execute(
                "SELECT e.uid, se.placed_at FROM set_entries se JOIN entries e ON e.id = se.entry_id"
                " WHERE se.set_id = ? AND e.state != 'pending' ORDER BY se.placed_at", (row["id"],),
            ) if item["uid"] in included
        ]
        if only_uids is not None and not placed:
            continue
        sets.append({"uid": row["uid"], "name": row["name"], "description": row["description"], "created_at": row["created_at"],
                     "updated_at": row["updated_at"],
                     "entries": [{"uid": item["uid"], "placed_at": item["placed_at"]} for item in placed]})
    followed = [
        dict(item) for item in conn.execute("SELECT kind, url, label, created_at FROM followed_sources ORDER BY id")
    ]
    manifest = {"format": FORMAT, "schema": db.schema_version(conn), "exported_at": datetime.now().isoformat(timespec="seconds"),
                "entries": entries, "sets": sets, "followed": followed}
    target = Path(dest)
    partial = target.with_name(target.name + ".partial")
    try:
        with zipfile.ZipFile(partial, "w") as archive:
            archive.writestr(MANIFEST, json.dumps(manifest), compress_type=zipfile.ZIP_DEFLATED)
            for record in entries:
                for asset in record["assets"]:
                    archive.write(db.data_dir() / asset["path"], asset["path"], compress_type=zipfile.ZIP_STORED)
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)
    return {"entries": len(entries), "sets": len(sets)}


def _read_manifest(archive) -> dict:
    """Return the parsed manifest, or raise TransferError when the zip is not a Hyperbridge library."""
    try:
        manifest = json.loads(archive.read(MANIFEST))
    except (KeyError, ValueError) as err:
        raise TransferError("That file is not a Hyperbridge library.") from err
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT or not isinstance(manifest.get("entries"), list):
        raise TransferError("That file is not a Hyperbridge library.")
    if int(manifest.get("schema") or 0) > len(db.list_migrations()):
        raise TransferError("That library comes from a newer Hyperbridge. Update this copy first.")
    return manifest


def _copy_assets(archive, record: dict) -> list[dict]:
    """Copy an entry's files out of the zip into storage; returns the asset rows to insert."""
    uid, rows, written = record["uid"], [], []
    try:
        for asset in record.get("assets", []):
            match = _MEMBER.match(str(asset.get("path", "")))
            if not match or match.group(1) != uid or match.group(2) != asset.get("kind"):
                continue
            try:
                info = archive.getinfo(asset["path"])
            except KeyError:
                continue
            if info.file_size > MAX_MEMBER_BYTES:
                continue
            target = storage.asset_path(uid, match.group(2), int(match.group(3)), match.group(4))
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, open(target, "wb") as out:
                shutil.copyfileobj(source, out)
            written.append(target)
            rows.append({"position": int(match.group(3)), "kind": match.group(2), "path": storage.relative_path(target),
                         "width": asset.get("width"), "height": asset.get("height"), "bytes": info.file_size})
    except Exception:
        for path in written:
            path.unlink(missing_ok=True)
        raise
    return rows


def list_deletions(conn) -> list[dict]:
    """Return the uid and deletion time of every entry deleted here, for telling another library what to remove."""
    return [{"uid": row["uid"], "deleted_at": row["deleted_at"]}
            for row in conn.execute("SELECT uid, deleted_at FROM entry_deletions ORDER BY deleted_at")]


def apply_deletions(conn, deletions: list) -> int:
    """Delete entries another library deleted, unless they were edited here after that; returns how many were removed.

    Every deletion is remembered so it keeps travelling to a third machine.
    """
    removed = 0
    for item in deletions if isinstance(deletions, list) else []:
        uid, when = (str(item.get("uid", "")), str(item.get("deleted_at") or "")) if isinstance(item, dict) else ("", "")
        if not re.fullmatch(r"[0-9a-f]{32}", uid) or not when:
            continue
        row = conn.execute("SELECT id, updated_at FROM entries WHERE uid = ?", (uid,)).fetchone()
        if row is not None:
            if (row["updated_at"] or "") > when:
                continue
            conn.execute("DELETE FROM jobs WHERE entry_id = ?", (row["id"],))
            conn.execute("DELETE FROM entries WHERE id = ?", (row["id"],))
            shutil.rmtree(storage.entry_dir(uid), ignore_errors=True)
            removed += 1
        known = conn.execute("SELECT deleted_at FROM entry_deletions WHERE uid = ?", (uid,)).fetchone()
        if known is None or known["deleted_at"] < when:
            conn.execute("INSERT OR REPLACE INTO entry_deletions (uid, deleted_at) VALUES (?, ?)", (uid, when))
    return removed


def _insert_entry(conn, record: dict, rows: list[dict]) -> int:
    """Insert an entry with its tags and asset rows; returns the new id."""
    cursor = conn.execute(
        f"INSERT INTO entries ({', '.join(_FIELDS)}) VALUES ({', '.join('?' * len(_FIELDS))})",
        [record.get(name) if record.get(name) is not None else ("" if name != "source_key" else None) for name in _FIELDS],
    )
    entry_id = cursor.lastrowid
    for name in record.get("tags", []):
        clean = str(name).strip()
        if not clean:
            continue
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (clean,))
        tag_id = conn.execute("SELECT id FROM tags WHERE name = ?", (clean,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) VALUES (?, ?)", (entry_id, tag_id))
    for row in rows:
        conn.execute(
            "INSERT INTO assets (entry_id, position, kind, path, width, height, bytes) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry_id, row["position"], row["kind"], row["path"], row["width"], row["height"], row["bytes"]),
        )
    return entry_id


def import_library(conn, source, update=False) -> dict:
    """Merge a library zip into this library; entries already here (same id or source) are kept, not duplicated.

    With update, an entry that is newer in the zip also replaces its title and other fields, tags and sets here.
    """
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as err:
        raise TransferError("That file is not a Hyperbridge library.") from err
    with archive:
        manifest = _read_manifest(archive)
        local = {}
        added = skipped = updated = 0
        placed_sets = _merge_set_heads(conn, manifest.get("sets", []), update)
        member_of = {}
        for item, set_id in placed_sets:
            for placed in item.get("entries", []):
                member_of.setdefault(placed.get("uid"), set()).add(set_id)
        for record in manifest["entries"]:
            if not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{32}", str(record.get("uid", ""))):
                continue
            found = conn.execute("SELECT id FROM entries WHERE uid = ?", (record["uid"],)).fetchone()
            if found is None and record.get("source_key"):
                found = conn.execute("SELECT id FROM entries WHERE source_key = ?", (record["source_key"],)).fetchone()
            if found is not None:
                local[record["uid"]] = found["id"]
                if update and _apply_edits(conn, found["id"], record, member_of.get(record["uid"], set())):
                    updated += 1
                else:
                    skipped += 1
                continue
            if record.get("state") not in ("captured", "failed"):
                continue
            rows = _copy_assets(archive, record)
            conn.execute("BEGIN IMMEDIATE")
            try:
                local[record["uid"]] = _insert_entry(conn, record, rows)
                conn.execute("DELETE FROM entry_deletions WHERE uid = ?", (record["uid"],))
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                shutil.rmtree(storage.entry_dir(record["uid"]), ignore_errors=True)
                raise
            added += 1
        sets_touched = _place_in_sets(conn, placed_sets, local)
        _merge_followed(conn, manifest.get("followed", []))
    return {"added": added, "skipped": skipped, "updated": updated, "deleted": 0, "sets": sets_touched}


def _apply_edits(conn, entry_id: int, record: dict, set_ids: set) -> bool:
    """Replace an entry's editable fields, tags and set membership with a newer copy; returns False when this copy is as new."""
    current = conn.execute("SELECT updated_at FROM entries WHERE id = ?", (entry_id,)).fetchone()["updated_at"] or ""
    if str(record.get("updated_at") or "") <= current:
        return False
    values = [str(record.get(name) or "") for name in _EDITED]
    conn.execute(f"UPDATE entries SET {', '.join(f'{name} = ?' for name in _EDITED)}, updated_at = ? WHERE id = ?",
                 (*values, record["updated_at"], entry_id))
    conn.execute("DELETE FROM entry_tags WHERE entry_id = ?", (entry_id,))
    for name in record.get("tags", []):
        clean = str(name).strip()
        if clean:
            conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (clean,))
            conn.execute("INSERT OR IGNORE INTO entry_tags (entry_id, tag_id) SELECT ?, id FROM tags WHERE name = ?", (entry_id, clean))
    conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT tag_id FROM entry_tags)")
    conn.execute(f"DELETE FROM set_entries WHERE entry_id = ? AND set_id NOT IN ({','.join('?' * len(set_ids))})", (entry_id, *set_ids))
    return True


def list_set_heads(conn) -> list[dict]:
    """Return every set's id, name, description and last edit time, for telling another library how its sets differ."""
    return [dict(row) for row in conn.execute("SELECT uid, name, description, created_at, updated_at FROM sets ORDER BY id")]


def list_set_deletions(conn) -> list[dict]:
    """Return the id and deletion time of every set deleted here."""
    return [{"uid": row["uid"], "deleted_at": row["deleted_at"]} for row in conn.execute("SELECT uid, deleted_at FROM set_deletions")]


def apply_set_deletions(conn, deletions: list) -> int:
    """Delete sets another library deleted, unless they were edited here after that; returns how many were removed."""
    removed = 0
    for item in deletions if isinstance(deletions, list) else []:
        uid, when = (str(item.get("uid", "")), str(item.get("deleted_at") or "")) if isinstance(item, dict) else ("", "")
        if not re.fullmatch(r"[0-9a-f]{32}", uid) or not when:
            continue
        row = conn.execute("SELECT id, updated_at FROM sets WHERE uid = ?", (uid,)).fetchone()
        if row is not None:
            if (row["updated_at"] or "") > when:
                continue
            conn.execute("DELETE FROM sets WHERE id = ?", (row["id"],))
            removed += 1
        known = conn.execute("SELECT deleted_at FROM set_deletions WHERE uid = ?", (uid,)).fetchone()
        if known is None or known["deleted_at"] < when:
            conn.execute("INSERT OR REPLACE INTO set_deletions (uid, deleted_at) VALUES (?, ?)", (uid, when))
    return removed


def merge_set_heads(conn, sets: list, update=False) -> int:
    """Create missing sets and, with update, take a newer name and description; returns how many sets changed."""
    return sum(1 for _, _, changed in _merge_heads(conn, sets, update) if changed)


def _merge_set_heads(conn, sets: list, update=False) -> list:
    """Return (set record, local set id) for every set that exists here after merging the heads."""
    return [(item, set_id) for item, set_id, _ in _merge_heads(conn, sets, update)]


def _merge_heads(conn, sets: list, update: bool) -> list:
    """Match sets by id (or by name when this library has not seen the id), create the missing, rename the older."""
    gone = {row[0]: row[1] for row in conn.execute("SELECT uid, deleted_at FROM set_deletions")}
    merged = []
    for item in sets:
        if not isinstance(item, dict):
            continue
        name = " ".join(str(item.get("name", "")).split())[:100]
        uid = str(item.get("uid") or "")
        uid = uid if re.fullmatch(r"[0-9a-f]{32}", uid) else ""
        created = str(item.get("created_at") or datetime.now().isoformat(timespec="seconds"))
        stamp = str(item.get("updated_at") or created)
        if not name or (uid and uid in gone and stamp <= gone[uid]):
            continue
        row = conn.execute("SELECT id, uid, updated_at FROM sets WHERE uid = ?", (uid,)).fetchone() if uid else None
        if row is None:
            row = conn.execute("SELECT id, uid, updated_at FROM sets WHERE name = ?", (name,)).fetchone()
            if row is not None and uid:
                conn.execute("UPDATE sets SET uid = ? WHERE id = ?", (uid, row["id"]))
        changed = False
        if row is None:
            fields = (uid or storage.new_uid(), name, str(item.get("description", "")), created, stamp)
            set_id = conn.execute("INSERT INTO sets (uid, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", fields).lastrowid
            conn.execute("DELETE FROM set_deletions WHERE uid = ?", (fields[0],))
            changed = True
        else:
            set_id = row["id"]
            if update and stamp > (row["updated_at"] or ""):
                taken = conn.execute("SELECT 1 FROM sets WHERE name = ? AND id != ?", (name, set_id)).fetchone()
                if taken is None:
                    conn.execute("UPDATE sets SET name = ? WHERE id = ?", (name, set_id))
                conn.execute("UPDATE sets SET description = ?, updated_at = ? WHERE id = ?", (str(item.get("description", "")), stamp, set_id))
                changed = True
        merged.append((item, set_id, changed))
    return merged


def _place_in_sets(conn, placed_sets: list, local: dict) -> int:
    """Place the matching entries in each merged set; returns how many sets were touched."""
    for item, set_id in placed_sets:
        for placed in item.get("entries", []):
            entry_id = local.get(placed.get("uid"))
            if entry_id is not None:
                conn.execute("INSERT OR IGNORE INTO set_entries (set_id, entry_id, placed_at) VALUES (?, ?, ?)",
                             (set_id, entry_id, placed.get("placed_at") or datetime.now().isoformat(timespec="seconds")))
    return len(placed_sets)


def _merge_followed(conn, followed: list) -> None:
    """Add followed sources this library does not have yet."""
    for item in followed:
        if item.get("url") and item.get("kind"):
            conn.execute("INSERT OR IGNORE INTO followed_sources (kind, url, label, created_at) VALUES (?, ?, ?, ?)",
                         (item["kind"], item["url"], item.get("label", ""),
                          item.get("created_at") or datetime.now().isoformat(timespec="seconds")))
