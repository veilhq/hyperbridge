"""Fills missing tags and titles from what an entry already records about where it came from."""
import json
import re

from bridge.ingest import capture
from bridge.library import library

_SERVICE_TAGS = {"arena": "are.na", "x": "x", "pinterest": "pinterest", "tumblr": "tumblr", "instagram": "instagram"}
_SITE_SERVICES = frozenset(("rss",))
_URL_TITLE =re.compile(r"^(https?://|www\.)\S+$", re.I)
_HASHTAG = r"(?<![\w&/])#([^\W\d_]\w*)"
_EDGE_GAP = r"[\s.,;:|]*"
_TAG_LINE = re.compile(rf"{_EDGE_GAP}(?:{_HASHTAG}{_EDGE_GAP})+")
_LEADING_TAGS = re.compile(rf"^{_EDGE_GAP}(?:{_HASHTAG}{_EDGE_GAP}){{2,}}")
_TRAILING_TAGS = re.compile(rf"(?:{_EDGE_GAP}{_HASHTAG}){{2,}}{_EDGE_GAP}$")


def hashtag_words(text) -> list[str]:
    """Return the distinct hashtag words in a text, lowercased, without the hash sign."""
    return list(dict.fromkeys(word.lower() for word in re.findall(_HASHTAG, text or "")))


def strip_hashtags(text) -> str:
    """Remove lines made only of hashtags and runs of two or more at a line's start or end; any other hashtag keeps its word."""
    lines = []
    for line in str(text or "").split("\n"):
        if _TAG_LINE.fullmatch(line):
            continue
        trimmed = _TRAILING_TAGS.sub("", _LEADING_TAGS.sub("", line))
        if trimmed.strip() or not line.strip():
            lines.append(re.sub(_HASHTAG, r"\1", trimmed).rstrip())
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def source_tags(row) -> list[str]:
    """Return tags implied by an entry's source: its service or site, and each part of its board, section or channel."""
    service = row["source_service"] or ""
    names = [_SERVICE_TAGS.get(service, service)] if service and service not in _SITE_SERVICES else []
    if not names:
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


def manual_fields(row) -> list:
    """Return the entry's hand-edited field names."""
    try:
        return list(json.loads(row["manual_fields"] or "[]"))
    except ValueError:
        return []


def placeholder_title(row) -> bool:
    """Whether an entry's title is only its collection, collection and creator, or site name - a stand-in a real title may replace."""
    title = " ".join(str(row["title"] or "").split()).lower()
    if not title:
        return True
    leaf = str(row["collection"] or "").split(" / ")[-1].strip()
    creator = str(row["creator"] or "").strip()
    domain = re.sub(r"^www\.", "", row["domain"] or "")
    stand_ins = [leaf, f"{leaf} by {creator}" if leaf and creator else "", creator, domain]
    return any(title == capture.shorten_title(" ".join(item.split())).lower() for item in stand_ins if item)


def _clean_description(conn, row, manual) -> list[str]:
    """Strip hashtags from a description the user has not edited; return the hashtag words removed."""
    description = str(row["description"] or "")
    if "description" in manual or "#" not in description:
        return []
    cleaned = strip_hashtags(description)
    if cleaned == description:
        return []
    conn.execute("UPDATE entries SET description = ? WHERE id = ?", (cleaned, row["id"]))
    return hashtag_words(description)


def enrich_entry(conn, row, extra_tags=()) -> bool:
    """Strip hashtags from the description, then add source tags (plus extra tags, such as page keywords) to an untagged entry and a fallback title to an untitled one.

    Hashtag words become tags unless the entry's tags were edited by hand. Returns True when anything changed.
    """
    manual = manual_fields(row)
    hashtags = _clean_description(conn, row, manual)
    changed = bool(hashtags)
    if changed:
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (row["id"],)).fetchone()
    title = str(row["title"] or "").strip()
    if "title" not in manual and (not title or _URL_TITLE.match(title)):
        found = fallback_title(row)
        if found and found != title:
            conn.execute("UPDATE entries SET title = ? WHERE id = ?", (found, row["id"]))
            changed = True
    if "tags" not in manual and not conn.execute("SELECT 1 FROM entry_tags WHERE entry_id = ?", (row["id"],)).fetchone():
        names = source_tags(row) + [name.lower() for name in library.parse_tags(list(extra_tags) + hashtags)]
        if names:
            library.add_entry_tags(conn, row["id"], names)
            conn.execute("UPDATE entries SET manual_fields = ? WHERE id = ?", (json.dumps(manual + ["tags"]), row["id"]))
            changed = True
    elif "tags" not in manual and hashtags:
        library.add_entry_tags(conn, row["id"], hashtags)
    return changed


def backfill(conn) -> int:
    """Enrich each captured entry that lacks tags or a title or has a # in its description (the rest are skipped in SQL); returns how many changed.

    Edit times are left alone so sync does not churn.
    """
    count = 0
    candidates = (
        "SELECT * FROM entries WHERE state != 'pending' AND (trim(title) = '' OR lower(title) LIKE 'http%' OR lower(title) LIKE 'www.%'"
        " OR description LIKE '%#%'"
        " OR NOT EXISTS (SELECT 1 FROM entry_tags WHERE entry_tags.entry_id = entries.id))"
    )
    for row in conn.execute(candidates).fetchall():
        count += enrich_entry(conn, row)
    conn.commit()
    return count
