"""Reads the Tumblr post or Pinterest pin a saved entry came from once, and fills the title, description, source site,
posted date and tags the entry is missing."""
from bridge.ingest import arena, capture, checks, enrich, pinterest, tumblr
from bridge.library import library

LIMIT = 40
STEP = "details"


def _replaceable_title(row) -> bool:
    """Whether an entry's title is empty, a link, a filename-style label or a placeholder, and was not edited by hand."""
    title = str(row["title"] or "").strip()
    if "title" in enrich.manual_fields(row):
        return False
    return arena.junk_title(title) or title.lower().startswith(("http", "www.")) or enrich.placeholder_title(row)


def _tumblr_details(fetcher, row) -> dict:
    match = tumblr._POST_LINK.search(row["source_url"] or "")
    host = tumblr.target(row["source_url"])
    if not match or not host:
        return {}
    post = (tumblr._read_post(fetcher, host, match.group(1)).get("posts") or [None])[0]
    return tumblr.post_details(post) if post else {}


def _pin_details(fetcher, row) -> dict:
    source = f"/pin/{row['source_ref']}/"
    data = pinterest._read(fetcher, "PinResource", {"id": row["source_ref"], "field_set_key": "detailed"}, source).get("data") or {}
    return pinterest.pin_details(data) if data else {}


_LOOKUPS = {"tumblr": _tumblr_details, "pinterest": _pin_details}


def _fill(conn, row, found) -> bool:
    """Write the found details into the entry's empty, placeholder or junk fields, skipping hand-edited ones."""
    manual = enrich.manual_fields(row)
    updates = {}
    title = capture.shorten_title(" ".join(str(found.get("title") or "").split()))
    if title and not arena.junk_title(title) and _replaceable_title(row):
        updates["title"] = title
    for field in ("description", "publisher", "posted_at"):
        if field not in manual and not row[field] and found.get(field):
            updates[field] = found[field]
    if updates:
        assignments = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(f"UPDATE entries SET {assignments} WHERE id = ?", (*updates.values(), row["id"]))
    tags = found.get("tags") or []
    if (tags and "tags" not in manual
            and not conn.execute("SELECT 1 FROM entry_tags WHERE entry_id = ?", (row["id"],)).fetchone()):
        library.apply_known_tags(conn, row["id"], tags)
        return True
    return bool(updates)


def details(conn, fetcher, limit=LIMIT) -> int:
    """Read up to limit due Tumblr and Pinterest entries from their source and fill what they lack; returns how many changed.

    Edit times are left alone so sync does not churn; a source that cannot be read waits longer after each failure,
    and a service that pushes back is skipped for the rest of the pass.
    """
    rows = conn.execute(
        "SELECT id, title, description, publisher, posted_at, creator, collection, domain, manual_fields,"
        " source_url, source_service, source_ref FROM entries"
        " WHERE source_service IN ('tumblr', 'pinterest') AND source_ref != ''"
        f" AND {checks.due()} ORDER BY id LIMIT ?", (STEP, checks.now(), int(limit))).fetchall()
    done = 0
    stopped = set()
    for row in rows:
        if row["source_service"] in stopped:
            continue
        try:
            found = _LOOKUPS[row["source_service"]](fetcher, row)
        except Exception as err:  # noqa: BLE001 - a post or pin that cannot be read waits for a later run
            if checks.pushed_back(err):
                stopped.add(row["source_service"])
                continue
            checks.failed(conn, row["id"], STEP)
            continue
        done += _fill(conn, row, found)
        checks.passed(conn, row["id"], STEP)
    return done
