"""The discovery feed and Latest: images pulled from the followed Are.na channels, Pinterest boards, Tumblr blogs and site feeds."""

import json
import random
from datetime import datetime, timedelta

from bridge.ingest import arena
from bridge.ingest import capture
from bridge.ingest import labels
from bridge.ingest import pinterest
from bridge.ingest import rss
from bridge.library import library
from bridge.library import sets
from bridge.ingest import tumblr

MAX_CHANNELS = 3
ROUNDS = 3
FEED_SOURCES = ("arena", "tumblr", "pinterest", "rss")
STALE_HOURS = 6
PRUNE_DISMISSED_DAYS = 180
PRUNE_UNSEEN_DAYS = 30
LATEST_BATCH = 8
LATEST_STALE_MINUTES = 30
FRESH_DAYS = 14
# Sources whose posts carry a real date; Pinterest boards do not, so they stay in Discover only.
LATEST_SOURCES = "('arena', 'tumblr', 'rss')"
_LATEST = f"state = 'new' AND set_id IS NULL AND source_id IN {LATEST_SOURCES}"
# New in Latest: arrived after the last visit and posted within FRESH_DAYS of arriving, so old archive pulls do not count.
_FRESH = f"(created_at > ? AND posted_at != '' AND posted_at >= date(created_at, '-{FRESH_DAYS} days'))"


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _weighted_pick(rng, weights, count) -> list:
    """Draw distinct keys at random, favoring the heavier ones."""
    weights = dict(weights)
    chosen = []
    while weights and len(chosen) < count:
        key = rng.choices(list(weights), weights=list(weights.values()))[0]
        chosen.append(key)
        del weights[key]
    return chosen


def pull(url, fetcher, rng, kind="", newest=False) -> list:
    """Return feed items for one followed link, from Are.na, a Pinterest board, a site's RSS feed or a Tumblr blog.

    newest reads the source's latest posts instead of a random sample; Pinterest boards have no order to read.
    """
    if arena.target(url):
        return arena.pull(url, fetcher, rng, newest)
    if kind == "rss":
        return rss.items(url, fetcher, rng, newest)
    if pinterest.is_pinterest(url):
        return [] if newest else pinterest.items(url, fetcher, rng)
    return tumblr.items(url, fetcher, rng, newest)


def follow_site(conn, url, fetcher) -> dict:
    """Follow a link that is neither Are.na nor Pinterest: a Tumblr blog when it has the Tumblr API, else the site's RSS or Atom feed."""
    try:
        return tumblr.follow(conn, url, fetcher)
    except ValueError:
        return rss.follow(conn, url, fetcher)


def pull_round(weights, fetcher, rng, kinds=None):
    """Pull once from a few followed sources drawn by weight ({url: weight}, with {url: kind} when known); returns (items, failed, jobs)."""
    picked = _weighted_pick(rng, weights, MAX_CHANNELS)
    failed = 0
    pulled, seen = [], set()
    for url in picked:
        try:
            items = pull(url, fetcher, rng, (kinds or {}).get(url, ""))
        except Exception:  # noqa: BLE001 - a channel that is down is skipped
            failed += 1
            continue
        for item in items:
            if item["url"] not in seen:
                seen.add(item["url"])
                pulled.append(item)
    return pulled, failed, len(picked)


def prune(conn) -> int:
    """Delete dismissed items older than PRUNE_DISMISSED_DAYS and unseen ones older than PRUNE_UNSEEN_DAYS."""
    now = datetime.now()
    dismissed = (now - timedelta(days=PRUNE_DISMISSED_DAYS)).isoformat(timespec="seconds")
    unseen = (now - timedelta(days=PRUNE_UNSEEN_DAYS)).isoformat(timespec="seconds")
    return conn.execute(
        "DELETE FROM feed_items WHERE (state = 'dismissed' AND created_at < ?) OR (state = 'new' AND created_at < ?)",
        (dismissed, unseen)).rowcount


def refresh(conn, fetcher=None, rng=None, replace=False) -> dict:
    """Pull images from the followed Are.na, Pinterest, Tumblr and site feed sources.

    replace swaps the unseen feed for the new pull; otherwise the images are appended, retrying up to ROUNDS times until something new arrives.
    """
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    prune(conn)
    sources = arena.list_followed(conn)
    followed = [item["url"] for item in sources]
    kinds = {item["url"]: item["kind"] for item in sources}
    try:
        arena.backfill_origins(conn, fetcher, rng)
    except Exception:  # noqa: BLE001 - missing origins only leave the library less described
        pass
    added = failed = jobs = 0
    for attempt in range(1 if replace else ROUNDS):
        pulled, round_failed, round_jobs = pull_round({url: 1 for url in followed}, fetcher, rng, kinds)
        failed, jobs = failed + round_failed, jobs + round_jobs
        if replace and (pulled or not followed):
            conn.execute("DELETE FROM feed_items WHERE state = 'new' AND set_id IS NULL")
        added += store(conn, pulled)
        if added or not followed or round_failed == round_jobs:
            break
    labels.check_new(conn, fetcher)
    return {"added": added, "failed": failed, "jobs": jobs, "enabled": ["arena"] if followed else []}


def refresh_latest(conn, fetcher=None, rng=None, batch=LATEST_BATCH) -> dict:
    """Read the newest posts of the dated followed sources checked longest ago, a batch at a time, into the feed."""
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    prune(conn)
    rows = conn.execute(
        "SELECT url, kind FROM followed_sources WHERE kind != 'pinterest' ORDER BY checked_at, id LIMIT ?", (int(batch),)).fetchall()
    added = failed = 0
    for row in rows:
        try:
            added += store(conn, pull(row["url"], fetcher, rng, row["kind"], newest=True))
        except Exception:  # noqa: BLE001 - a source that is down is skipped until its next turn
            failed += 1
        conn.execute("UPDATE followed_sources SET checked_at = ? WHERE url = ?", (_now(), row["url"]))
    labels.check_new(conn, fetcher)
    return {"added": added, "failed": failed, "jobs": len(rows), "enabled": ["latest"] if rows else []}


def latest_seen(conn) -> str:
    """Return when Latest was last opened, or '' before the first visit."""
    row = conn.execute("SELECT value FROM feed_marks WHERE name = 'latest_seen'").fetchone()
    return row["value"] if row else ""


def mark_latest_seen(conn) -> str:
    """Record a Latest visit now and return the previous visit, which the open view marks new images against."""
    previous = latest_seen(conn)
    conn.execute("INSERT INTO feed_marks (name, value) VALUES ('latest_seen', ?)"
                 " ON CONFLICT (name) DO UPDATE SET value = excluded.value", (_now(),))
    return previous


def latest_status(conn) -> dict:
    """Return how many images in Latest are new since the last visit, for the nav indicator."""
    fresh = conn.execute(f"SELECT COUNT(*) FROM feed_items WHERE {_LATEST} AND ai_label = '' AND {_FRESH}",
                         (latest_seen(conn),)).fetchone()[0]
    return {"fresh": fresh}


def list_latest(conn, offset=0, limit=60, show_flagged=False, since=None) -> dict:
    """Return unseen images from dated sources newest posted first, each marked fresh when new since `since` (default: the last visit)."""
    since = latest_seen(conn) if since is None else str(since)
    shown = _LATEST if show_flagged else _LATEST + " AND ai_label = ''"
    total = conn.execute(f"SELECT COUNT(*) FROM feed_items WHERE {shown}").fetchone()[0]
    flagged = conn.execute(f"SELECT COUNT(*) FROM feed_items WHERE {_LATEST} AND ai_label != ''").fetchone()[0]
    rows = conn.execute(
        f"SELECT id, source_id, url, thumb, width, height, title, creator, page_url, ai_label, posted_at, {_FRESH} AS fresh"
        f" FROM feed_items WHERE {shown} ORDER BY posted_at DESC, id DESC LIMIT ? OFFSET ?",
        (since, max(1, min(int(limit), 200)), max(0, int(offset)))).fetchall()
    checked = conn.execute("SELECT MAX(checked_at) FROM followed_sources WHERE kind != 'pinterest'").fetchone()[0]
    stale = not checked or (datetime.now() - datetime.fromisoformat(checked)).total_seconds() > LATEST_STALE_MINUTES * 60
    items = [dict(row, fresh=bool(row["fresh"])) for row in rows]
    return {"items": mark_captured(conn, items), "total": total, "flagged": flagged, "stale": stale}


def store(conn, items, set_id=None) -> int:
    """Insert items not already saved or seen, marked for a set when one is given; returns how many were new."""
    added = 0
    for item in items:
        try:
            key = capture.normalize_url(item["url"])
        except ValueError:
            continue
        if conn.execute("SELECT 1 FROM entries WHERE source_key = ?", (key,)).fetchone():
            continue
        cursor = conn.execute(
            "INSERT OR IGNORE INTO feed_items"
            " (source_id, url, thumb, width, height, title, creator, page_url, term, created_at,"
            " source_ref, collection, posted_at, tags, set_id, description, publisher)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["source_id"], item["url"], item["thumb"], item["width"], item["height"], item["title"],
             item["creator"], item["page_url"], item["term"], _now(),
             item.get("source_ref", ""), item.get("collection", ""), item.get("posted_at", ""),
             json.dumps(item.get("tags") or []), set_id, item.get("description", ""), item.get("publisher", "")),
        )
        added += cursor.rowcount
    return added


def list_items(conn, offset=0, limit=60, show_flagged=False) -> dict:
    """Return unseen feed items, oldest first so later pulls append, with whether the feed is due a refresh.

    Items carrying an AI label are left out and counted as flagged unless show_flagged is set.
    """
    unseen = "state = 'new' AND set_id IS NULL AND source_id IN ('arena', 'tumblr', 'pinterest', 'rss')"
    shown = unseen if show_flagged else unseen + " AND ai_label = ''"
    total = conn.execute(f"SELECT COUNT(*) FROM feed_items WHERE {shown}").fetchone()[0]
    flagged = conn.execute(f"SELECT COUNT(*) FROM feed_items WHERE {unseen} AND ai_label != ''").fetchone()[0]
    rows = conn.execute(
        "SELECT id, source_id, url, thumb, width, height, title, creator, page_url, ai_label FROM feed_items"
        f" WHERE {shown} ORDER BY id LIMIT ? OFFSET ?",
        (max(1, min(int(limit), 200)), max(0, int(offset)))).fetchall()
    newest = conn.execute("SELECT MAX(created_at) FROM feed_items").fetchone()[0]
    stale = not newest or (datetime.now() - datetime.fromisoformat(newest)).total_seconds() > STALE_HOURS * 3600
    return {"items": mark_captured(conn, [dict(row) for row in rows]), "total": total, "flagged": flagged, "stale": stale}


def mark_captured(conn, items) -> list:
    """Set known_entry_id on each feed item to the library entry already captured from its image link, else None."""
    for item in items:
        try:
            key = capture.normalize_url(item["url"])
        except ValueError:
            key = None
        row = conn.execute("SELECT id FROM entries WHERE source_key = ?", (key,)).fetchone() if key else None
        item["known_entry_id"] = row["id"] if row else None
    return items


def dismiss(conn, ids) -> int:
    """Hide feed items for good in one statement per few hundred ids; returns how many changed."""
    ids = [int(item_id) for item_id in ids]
    count = 0
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        count += conn.execute(
            f"UPDATE feed_items SET state = 'dismissed' WHERE state = 'new' AND id IN ({','.join('?' * len(chunk))})", chunk).rowcount
    return count


def accept(conn, ids, set_id=None) -> dict:
    """Capture the chosen feed items crediting their pages, mark them saved and place them in a set."""
    added = placed = 0
    for item_id in ids:
        row = conn.execute("SELECT * FROM feed_items WHERE id = ? AND state = 'new'", (int(item_id),)).fetchone()
        if not row:
            continue
        result = capture.add_link(conn, row["url"])
        if result["created"]:
            added += 1
            conn.execute(
                "UPDATE entries SET source_url = ?, domain = ?, source_service = ?, source_ref = ?, collection = ?, posted_at = ?,"
                " description = ?, publisher = ? WHERE id = ?",
                (row["page_url"] or row["url"], capture.source_domain(row["page_url"] or row["url"]), row["source_id"], row["source_ref"], row["collection"], row["posted_at"],
                 row["description"], row["publisher"], result["entry_id"]))
            capture.keep_details(conn, result["entry_id"], row["title"], row["creator"])
            library.add_entry_tags(conn, result["entry_id"], json.loads(row["tags"] or "[]"))
        conn.execute("UPDATE feed_items SET state = 'saved' WHERE id = ?", (row["id"],))
        if set_id and sets.place(result["entry_id"], int(set_id)):
            placed += 1
    return {"added": added, "placed": placed}
