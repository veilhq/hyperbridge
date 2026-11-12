"""Restores titles that capture lost, by asking Tumblr or Pinterest again for the post or pin an entry came from."""
import json

from bridge.ingest import arena, capture, pinterest, tumblr

LIMIT = 40


def _needs_title(row) -> bool:
    """Whether an entry's title is empty, a link or a filename-style label, and was not edited by hand."""
    try:
        manual = list(json.loads(row["manual_fields"] or "[]"))
    except ValueError:
        return False
    title = str(row["title"] or "").strip()
    return "title" not in manual and (not title or arena.junk_title(title) or title.lower().startswith(("http", "www.")))


def _tumblr_title(fetcher, row) -> str:
    match = tumblr._POST_LINK.search(row["source_url"] or "")
    host = tumblr.target(row["source_url"])
    if not match or not host:
        return ""
    post = (tumblr._read_post(fetcher, host, match.group(1)).get("posts") or [None])[0]
    return tumblr._title(post) if post else ""


def _pin_title(fetcher, row) -> str:
    source = f"/pin/{row['source_ref']}/"
    data = pinterest._read(fetcher, "PinResource", {"id": row["source_ref"], "field_set_key": "detailed"}, source).get("data") or {}
    return str(data.get("grid_title") or data.get("title") or "").strip()


_LOOKUPS = {"tumblr": _tumblr_title, "pinterest": _pin_title}


def titles(conn, fetcher, limit=LIMIT) -> int:
    """Give up to limit untitled Tumblr and Pinterest entries the title their source shows; returns how many changed.

    Edit times are left alone so sync does not churn; entries the source cannot answer for are retried at the next start.
    """
    rows = conn.execute(
        "SELECT id, title, manual_fields, source_url, source_service, source_ref FROM entries"
        " WHERE source_service IN ('tumblr', 'pinterest') AND source_ref != ''").fetchall()
    done = 0
    for row in rows:
        if done >= limit:
            break
        if not _needs_title(row):
            continue
        try:
            found = capture.shorten_title(" ".join(_LOOKUPS[row["source_service"]](fetcher, row).split()))
        except Exception:  # noqa: BLE001 - a post or pin that cannot be read is left for a later run
            continue
        if found and not arena.junk_title(found):
            conn.execute("UPDATE entries SET title = ? WHERE id = ?", (found, row["id"]))
            done += 1
    return done
