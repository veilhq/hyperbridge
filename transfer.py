"""Library export and import: one zip holds every entry's fields, tags, sets and image files."""

import json
import re
import shutil
import zipfile
from datetime import datetime
from pathlib import Path

import db
import storage

FORMAT = 1
MANIFEST = "library.json"
MAX_MEMBER_BYTES = 200_000_000
_MEMBER = re.compile(r"^assets/[0-9a-f]{2}/([0-9a-f]{32})/(original|thumbnail|screenshot)-(\d+)\.([a-z0-9]{1,8})$")
_FIELDS = (
    "uid", "title", "source_url", "source_key", "domain", "description", "creator", "publisher", "type", "year",
    "manual_fields", "state", "created_at", "updated_at", "swatches", "source_service", "source_ref", "collection",
    "posted_at",
)


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
    """Return the uid and source key of every captured or failed entry, for deciding what another library lacks."""
    return [
        {"uid": row["uid"], "source_key": row["source_key"]}
        for row in conn.execute("SELECT uid, source_key FROM entries WHERE state != 'pending' ORDER BY id")
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
    for row in conn.execute("SELECT id, name, description, created_at FROM sets ORDER BY id"):
        placed = [
            item for item in conn.execute(
                "SELECT e.uid, se.placed_at FROM set_entries se JOIN entries e ON e.id = se.entry_id"
                " WHERE se.set_id = ? AND e.state != 'pending' ORDER BY se.placed_at", (row["id"],),
            ) if item["uid"] in included
        ]
        if only_uids is not None and not placed:
            continue
        sets.append({"name": row["name"], "description": row["description"], "created_at": row["created_at"],
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


def import_library(conn, source) -> dict:
    """Merge a library zip into this library; entries already here (same id or source) are kept, not duplicated."""
    try:
        archive = zipfile.ZipFile(source)
    except (zipfile.BadZipFile, OSError) as err:
        raise TransferError("That file is not a Hyperbridge library.") from err
    with archive:
        manifest = _read_manifest(archive)
        local = {}
        added = skipped = 0
        for record in manifest["entries"]:
            if not isinstance(record, dict) or not re.fullmatch(r"[0-9a-f]{32}", str(record.get("uid", ""))):
                continue
            found = conn.execute("SELECT id FROM entries WHERE uid = ?", (record["uid"],)).fetchone()
            if found is None and record.get("source_key"):
                found = conn.execute("SELECT id FROM entries WHERE source_key = ?", (record["source_key"],)).fetchone()
            if found is not None:
                local[record["uid"]] = found["id"]
                skipped += 1
                continue
            if record.get("state") not in ("captured", "failed"):
                continue
            rows = _copy_assets(archive, record)
            conn.execute("BEGIN IMMEDIATE")
            try:
                local[record["uid"]] = _insert_entry(conn, record, rows)
                conn.execute("COMMIT")
            except Exception:
                conn.execute("ROLLBACK")
                shutil.rmtree(storage.entry_dir(record["uid"]), ignore_errors=True)
                raise
            added += 1
        sets_touched = _merge_sets(conn, manifest.get("sets", []), local)
        _merge_followed(conn, manifest.get("followed", []))
    return {"added": added, "skipped": skipped, "sets": sets_touched}


def _merge_sets(conn, sets: list, local: dict) -> int:
    """Create missing sets by name and place the matching entries in them; returns how many sets were touched."""
    touched = 0
    for item in sets:
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        conn.execute("INSERT OR IGNORE INTO sets (name, description, created_at) VALUES (?, ?, ?)",
                     (name, str(item.get("description", "")), item.get("created_at") or datetime.now().isoformat(timespec="seconds")))
        set_id = conn.execute("SELECT id FROM sets WHERE name = ?", (name,)).fetchone()[0]
        for placed in item.get("entries", []):
            entry_id = local.get(placed.get("uid"))
            if entry_id is not None:
                conn.execute("INSERT OR IGNORE INTO set_entries (set_id, entry_id, placed_at) VALUES (?, ?, ?)",
                             (set_id, entry_id, placed.get("placed_at") or datetime.now().isoformat(timespec="seconds")))
        touched += 1
    return touched


def _merge_followed(conn, followed: list) -> None:
    """Add followed sources this library does not have yet."""
    for item in followed:
        if item.get("url") and item.get("kind"):
            conn.execute("INSERT OR IGNORE INTO followed_sources (kind, url, label, created_at) VALUES (?, ?, ?, ?)",
                         (item["kind"], item["url"], item.get("label", ""),
                          item.get("created_at") or datetime.now().isoformat(timespec="seconds")))
