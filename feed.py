"""The discovery feed: images pulled from the followed Are.na channels and Tumblr blogs."""

import json
import random
from datetime import datetime, timedelta

import arena
import capture
import library
import sets
import tumblr

MAX_CHANNELS = 3
ROUNDS = 3
FEED_SOURCES = ("arena", "tumblr")
STALE_HOURS = 6
PRUNE_DISMISSED_DAYS = 180
PRUNE_UNSEEN_DAYS = 30


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


def pull(url, fetcher, rng) -> list:
    """Return feed items for one followed link, from Are.na or a Tumblr blog."""
    return arena.pull(url, fetcher, rng) if arena.target(url) else tumblr.items(url, fetcher, rng)


def _round(followed, fetcher, rng):
    """Pull from a few followed sources once; returns (items, failed, jobs)."""
    picked = _weighted_pick(rng, {url: 1 for url in followed}, MAX_CHANNELS)
    failed = 0
    pulled, seen = [], set()
    for url in picked:
        try:
            items = pull(url, fetcher, rng)
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
    """Pull images from the followed Are.na and Tumblr sources.

    replace swaps the unseen feed for the new pull; otherwise the images are appended, retrying up to ROUNDS times until something new arrives.
    """
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    prune(conn)
    followed = [item["url"] for item in arena.list_followed(conn)]
    try:
        arena.backfill_origins(conn, fetcher, rng)
    except Exception:  # noqa: BLE001 - missing origins only leave the library less described
        pass
    added = failed = jobs = 0
    for attempt in range(1 if replace else ROUNDS):
        pulled, round_failed, round_jobs = _round(followed, fetcher, rng)
        failed, jobs = failed + round_failed, jobs + round_jobs
        if replace and (pulled or not followed):
            conn.execute("DELETE FROM feed_items WHERE state = 'new'")
        added += _store(conn, pulled)
        if added or not followed or round_failed == round_jobs:
            break
    return {"added": added, "failed": failed, "jobs": jobs, "enabled": ["arena"] if followed else []}


def _store(conn, items) -> int:
    """Insert items not already saved or seen; returns how many were new."""
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
            " source_ref, collection, posted_at, tags) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["source_id"], item["url"], item["thumb"], item["width"], item["height"], item["title"],
             item["creator"], item["page_url"], item["term"], _now(),
             item.get("source_ref", ""), item.get("collection", ""), item.get("posted_at", ""),
             json.dumps(item.get("tags") or [])),
        )
        added += cursor.rowcount
    return added


def list_items(conn, offset=0, limit=60) -> dict:
    """Return unseen feed items, oldest first so later pulls append, with whether the feed is due a refresh."""
    total = conn.execute("SELECT COUNT(*) FROM feed_items WHERE state = 'new' AND source_id IN ('arena', 'tumblr')").fetchone()[0]
    rows = conn.execute(
        "SELECT id, source_id, url, thumb, width, height, title, creator, page_url FROM feed_items"
        " WHERE state = 'new' AND source_id IN ('arena', 'tumblr') ORDER BY id LIMIT ? OFFSET ?",
        (max(1, min(int(limit), 200)), max(0, int(offset)))).fetchall()
    newest = conn.execute("SELECT MAX(created_at) FROM feed_items").fetchone()[0]
    stale = not newest or (datetime.now() - datetime.fromisoformat(newest)).total_seconds() > STALE_HOURS * 3600
    return {"items": [dict(row) for row in rows], "total": total, "stale": stale}


def dismiss(conn, ids) -> int:
    """Hide feed items for good; returns how many changed."""
    count = 0
    for item_id in ids:
        count += conn.execute(
            "UPDATE feed_items SET state = 'dismissed' WHERE id = ? AND state = 'new'", (int(item_id),)).rowcount
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
                "UPDATE entries SET source_url = ?, source_service = ?, source_ref = ?, collection = ?, posted_at = ? WHERE id = ?",
                (row["page_url"] or row["url"], row["source_id"], row["source_ref"], row["collection"], row["posted_at"],
                 result["entry_id"]))
            library.add_entry_tags(conn, result["entry_id"], json.loads(row["tags"] or "[]"))
        conn.execute("UPDATE feed_items SET state = 'saved' WHERE id = ?", (row["id"],))
        if set_id and sets.place(result["entry_id"], int(set_id)):
            placed += 1
    return {"added": added, "placed": placed}
