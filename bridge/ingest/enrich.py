"""Fills missing tags and titles from what an entry already records about where it came from."""
import json
import re

from bridge.ingest import capture
from bridge.library import library

_SERVICE_TAGS = {"arena": "are.na", "x": "x", "pinterest": "pinterest", "tumblr": "tumblr", "instagram": "instagram"}
_URL_TITLE = re.compile(r"^(https?://|www\.)\S+$", re.I)


def source_tags(row) -> list[str]:
    """Return tags implied by an entry's source: its service or site, and each part of its board, section or channel."""
    service = row["source_service"] or ""
    names = [_SERVICE_TAGS.get(service, service)] if service else []
    if not service:
        domain = re.sub(r"^www\.", "", row["domain"] or "")
        names.append(domain)
    names.extend(part for part in str(row["collection"] or "").split(" / "))
    return [name.lower() for name in library.parse_tags(names)]


def fallback_title(row) -> str:
    """Return a title built from the description, or from the creator and collection, or from the site; empty when nothing is known."""
    description = " ".join(str(row["description"] or "").split())
    if description:
        return capture.shorten_title(description)
    leaf = str(row["collection"] or "").split(" / ")[-1].strip()
    creator = str(row["creator"] or "").strip()
    if leaf and creator:
        return capture.shorten_title(f"{leaf} by {creator}")
    return capture.shorten_title(leaf or creator or re.sub(r"^www\.", "", row["domain"] or ""))


def _manual(row) -> list:
    """Return the entry's hand-edited field names."""
    try:
        return list(json.loads(row["manual_fields"] or "[]"))
    except ValueError:
        return []


def enrich_entry(conn, row) -> bool:
    """Add source tags to an untagged entry and a fallback title to an untitled one; returns True when anything changed."""
    manual = _manual(row)
    changed = False
    title = str(row["title"] or "").strip()
    if "title" not in manual and (not title or _URL_TITLE.match(title)):
        found = fallback_title(row)
        if found and found != title:
            conn.execute("UPDATE entries SET title = ? WHERE id = ?", (found, row["id"]))
            changed = True
    if "tags" not in manual and not conn.execute("SELECT 1 FROM entry_tags WHERE entry_id = ?", (row["id"],)).fetchone():
        names = source_tags(row)
        if names:
            library.add_entry_tags(conn, row["id"], names)
            conn.execute("UPDATE entries SET manual_fields = ? WHERE id = ?", (json.dumps(manual + ["tags"]), row["id"]))
            changed = True
    return changed


def backfill(conn) -> int:
    """Enrich each captured entry that lacks tags or a title (the rest are skipped in SQL); returns how many changed. Edit times are left alone so sync does not churn."""
    count = 0
    candidates = (
        "SELECT * FROM entries WHERE state != 'pending' AND (trim(title) = '' OR lower(title) LIKE 'http%' OR lower(title) LIKE 'www.%'"
        " OR NOT EXISTS (SELECT 1 FROM entry_tags WHERE entry_tags.entry_id = entries.id))"
    )
    for row in conn.execute(candidates).fetchall():
        count += enrich_entry(conn, row)
    conn.commit()
    return count
