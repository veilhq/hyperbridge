"""People behind saved images: one creator links handles on Are.na, Tumblr, X, Instagram and sites, matched only on the Operator's yes."""

import re
from datetime import datetime
from urllib.parse import urlsplit

MIN_KEY = 4
_SOCIAL = {"x.com": "x", "twitter.com": "x", "instagram.com": "instagram"}


def key(text) -> str:
    """Return text lowercased with everything but letters and digits removed, for comparing names and handles."""
    return re.sub(r"[^a-z0-9]", "", str(text or "").lower())


def handle_of(url) -> dict | None:
    """Return {kind, value, url} for a profile link: an Are.na user, a Tumblr blog, an X or Instagram account, or a site."""
    parts = urlsplit(str(url or "").strip())
    host = re.sub(r"^www\.", "", (parts.hostname or "").lower())
    if parts.scheme not in ("http", "https") or "." not in host:
        return None
    segments = [part for part in parts.path.split("/") if part]
    if host == "are.na":
        return {"kind": "arena", "value": segments[0].lower(), "url": f"https://www.are.na/{segments[0]}"} if segments else None
    if host in _SOCIAL:
        service = _SOCIAL[host]
        base = "https://x.com/" if service == "x" else "https://www.instagram.com/"
        return {"kind": service, "value": segments[0].lower(), "url": base + segments[0]} if segments else None
    if host.endswith(".tumblr.com"):
        return {"kind": "tumblr", "value": host, "url": f"https://{host}/"}
    return {"kind": "site", "value": host, "url": f"https://{host}/"}


def _name_key(handle) -> str:
    """Return the part of a handle that reads as a name: the slug, the blog name, or the site name without its suffix."""
    value = handle["value"]
    if handle["kind"] in ("tumblr", "site"):
        value = value.removesuffix(".tumblr.com").rsplit(".", 1)[0] if "." in value else value
    return key(value)


def _row(conn, creator_id) -> dict | None:
    row = conn.execute("SELECT id, name FROM creators WHERE id = ?", (int(creator_id),)).fetchone()
    if not row:
        return None
    handles = [dict(item) for item in conn.execute(
        "SELECT kind, value, url FROM creator_handles WHERE creator_id = ? ORDER BY kind, value", (row["id"],))]
    return {"id": row["id"], "name": row["name"], "handles": handles}


def for_handle(conn, url) -> dict | None:
    """Return the confirmed creator a profile link belongs to, or None."""
    handle = handle_of(url)
    if not handle:
        return None
    row = conn.execute("SELECT creator_id FROM creator_handles WHERE kind = ? AND value = ?",
                       (handle["kind"], handle["value"])).fetchone()
    return _row(conn, row[0]) if row else None


def for_name(conn, name) -> dict | None:
    """Return the confirmed creator whose name or handle matches free-text creator credit, or None."""
    wanted = key(name)
    if len(wanted) < MIN_KEY:
        return None
    for row in conn.execute("SELECT id, name FROM creators"):
        if key(row["name"]) == wanted:
            return _row(conn, row["id"])
    for row in conn.execute("SELECT creator_id, kind, value FROM creator_handles"):
        if _name_key(dict(row)) == wanted:
            return _row(conn, row["creator_id"])
    return None


def _rejected(conn, name, handle) -> bool:
    return bool(conn.execute("SELECT 1 FROM creator_rejects WHERE name = ? AND kind = ? AND value = ?",
                             (key(name), handle["kind"], handle["value"])).fetchone())


def suggest(conn, url) -> dict | None:
    """Return {name, creator_id} when a not yet linked profile link reads like a known creator or a saved credit, else None.

    A known creator is matched first, then the creator credit on saved images; a match the Operator turned down is skipped.
    """
    handle = handle_of(url)
    if not handle or handle["kind"] == "site" or for_handle(conn, url):
        return None
    wanted = _name_key(handle)
    if len(wanted) < MIN_KEY:
        return None
    for row in conn.execute("SELECT id, name FROM creators ORDER BY id"):
        if key(row["name"]) == wanted and not _rejected(conn, row["name"], handle):
            return {"name": row["name"], "creator_id": row["id"]}
    for row in conn.execute("SELECT creator, COUNT(*) AS saved FROM entries WHERE creator != '' GROUP BY creator ORDER BY saved DESC"):
        if key(row["creator"]) == wanted and not _rejected(conn, row["creator"], handle):
            return {"name": row["creator"], "creator_id": None}
    return None


def confirm(conn, name, url, creator_id=None) -> dict | None:
    """Link a profile link to a creator, making the creator from the name when there is none yet; returns the creator."""
    handle = handle_of(url)
    if not handle:
        return None
    if creator_id is None:
        found = for_name(conn, name)
        creator_id = found["id"] if found else conn.execute(
            "INSERT INTO creators (name, created_at) VALUES (?, ?)",
            (str(name).strip()[:200], datetime.now().isoformat(timespec="seconds"))).lastrowid
    conn.execute("INSERT OR REPLACE INTO creator_handles (creator_id, kind, value, url) VALUES (?, ?, ?, ?)",
                 (int(creator_id), handle["kind"], handle["value"], handle["url"]))
    return _row(conn, creator_id)


def reject(conn, name, url) -> bool:
    """Remember that a profile link is not the named creator, so the match is not suggested again."""
    handle = handle_of(url)
    if not handle:
        return False
    conn.execute("INSERT OR IGNORE INTO creator_rejects (name, kind, value) VALUES (?, ?, ?)",
                 (key(name), handle["kind"], handle["value"]))
    return True


def entry_ids(conn, creator, limit=200) -> list:
    """Return saved entry ids credited to a creator by name or handle, or carrying one of their profile links, newest first."""
    names = {key(creator["name"])} | {_name_key(handle) for handle in creator["handles"]}
    urls = {handle["url"] for handle in creator["handles"]}
    found = []
    for row in conn.execute("SELECT id, creator, creator_handle FROM entries ORDER BY created_at DESC, id DESC"):
        credited = key(row["creator"]) in names and len(key(row["creator"])) >= MIN_KEY
        linked = (handle_of(row["creator_handle"]) or {}).get("url") in urls
        if credited or linked:
            found.append(row["id"])
            if len(found) >= limit:
                break
    return found
