"""The discovery feed: images pulled from the sources switched on in settings, steered by what is saved."""

import html
import json
import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import quote

import arena
import capture
import discover
import feed_sources
import sets

MIN_EDGE = 150
TERMS_PER_REFRESH = 3
PER_QUERY = 10
MAX_CHANNELS = 3
FOLLOWED_WEIGHT = 3
STALE_HOURS = 6
_TAG_PATTERN = re.compile(r"<[^>]+>")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _json(fetcher, url) -> dict:
    return json.loads(bytes(fetcher(url).body).decode("utf-8", "replace"))


def search_terms(conn) -> list:
    """Return search words drawn from the library: the most used tags, then set names."""
    tags = [row[0] for row in conn.execute(
        "SELECT t.name FROM tags t JOIN entry_tags et ON et.tag_id = t.id"
        " GROUP BY t.id ORDER BY COUNT(*) DESC, t.name LIMIT 12")]
    names = [row[0] for row in conn.execute("SELECT name FROM sets ORDER BY name COLLATE NOCASE LIMIT 12")]
    creators = [row[0] for row in conn.execute(
        "SELECT creator FROM entries WHERE creator != '' GROUP BY creator ORDER BY COUNT(*) DESC LIMIT 8")]
    seen, terms = set(), []
    for term in [*tags, *names, *creators]:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def term_weights(conn) -> dict:
    """Score each search word by how much of the library uses it, nudged by what was saved or dismissed from it."""
    weights = {}
    for term in search_terms(conn):
        used = conn.execute(
            "SELECT (SELECT COUNT(*) FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE t.name = ? COLLATE NOCASE)"
            " + (SELECT COUNT(*) FROM set_entries se JOIN sets s ON s.id = se.set_id WHERE s.name = ? COLLATE NOCASE)"
            " + (SELECT COUNT(*) FROM entries WHERE creator = ? COLLATE NOCASE)", (term, term, term)).fetchone()[0]
        saved, dismissed = conn.execute(
            "SELECT COALESCE(SUM(state = 'saved'), 0), COALESCE(SUM(state = 'dismissed'), 0)"
            " FROM feed_items WHERE term = ? COLLATE NOCASE", (term,)).fetchone()
        weights[term] = max(1, used + 3 * saved - dismissed)
    return weights


def _weighted_pick(rng, weights, count) -> list:
    """Draw distinct keys at random, favoring the heavier ones."""
    weights = dict(weights)
    chosen = []
    while weights and len(chosen) < count:
        key = rng.choices(list(weights), weights=list(weights.values()))[0]
        chosen.append(key)
        del weights[key]
    return chosen


def pick_terms(conn, rng, count) -> list:
    """Choose search words at random, favoring those the library and past choices point to."""
    return _weighted_pick(rng, term_weights(conn), count)


def arena_channels(conn) -> list:
    """Return Are.na channel links that saved entries came from."""
    rows = conn.execute("SELECT DISTINCT source_url FROM entries WHERE source_url LIKE '%are.na/%'").fetchall()
    return [row[0] for row in rows if discover._arena_slug(row[0])]


def _commons(term, fetcher) -> list:
    url = ("https://commons.wikimedia.org/w/api.php?action=query&format=json&generator=search&gsrnamespace=6"
           f"&gsrsearch={quote(term)}%20filetype:bitmap&gsrlimit={PER_QUERY}&prop=imageinfo"
           "&iiprop=url|size|extmetadata&iiurlwidth=400")
    items = []
    for page in (_json(fetcher, url).get("query", {}).get("pages") or {}).values():
        info = (page.get("imageinfo") or [{}])[0]
        if not info.get("url") or min(info.get("width", 0), info.get("height", 0)) < MIN_EDGE:
            continue
        artist = ((info.get("extmetadata") or {}).get("Artist") or {}).get("value", "")
        items.append({
            "source_id": "commons", "url": info["url"], "thumb": info.get("thumburl", ""),
            "width": info["width"], "height": info["height"],
            "title": re.sub(r"^File:|\.\w+$", "", page.get("title", "")),
            "creator": html.unescape(_TAG_PATTERN.sub("", artist)).strip()[:200],
            "page_url": info.get("descriptionurl", ""), "term": term,
        })
    return items


def _met(term, fetcher, rng) -> list:
    base = "https://collectionapi.metmuseum.org/public/collection/v1"
    found = _json(fetcher, f"{base}.1/search?hasImages=true&isPublicDomain=true&q={quote(term)}")
    ids = (found.get("objectIDs") or [])[:60]
    ids = rng.sample(ids, min(PER_QUERY, len(ids)))

    def one(object_id):
        try:
            return _json(fetcher, f"{base}/objects/{object_id}")
        except Exception:  # noqa: BLE001 - one missing object is skipped
            return {}

    with ThreadPoolExecutor(max_workers=5) as pool:
        objects = list(pool.map(one, ids))
    return [{
        "source_id": "met", "url": obj["primaryImage"], "thumb": obj.get("primaryImageSmall") or obj["primaryImage"],
        "width": 0, "height": 0, "title": obj.get("title", "")[:300],
        "creator": obj.get("artistDisplayName", "")[:200],
        "page_url": obj.get("objectURL", ""), "term": term,
    } for obj in objects if obj.get("isPublicDomain") and obj.get("primaryImage")]


def refresh(conn, fetcher=None, rng=None) -> dict:
    """Pull new images from every enabled source and store the ones not seen before."""
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    enabled = set(feed_sources.enabled_sources())
    chosen = pick_terms(conn, rng, TERMS_PER_REFRESH)
    jobs = []
    if "commons" in enabled:
        jobs += [lambda term=term: _commons(term, fetcher) for term in chosen]
    if "met" in enabled:
        jobs += [lambda term=term: _met(term, fetcher, rng) for term in chosen]
    if "arena" in enabled:
        followed = [item["url"] for item in arena.list_followed(conn)]
        pool = {url: FOLLOWED_WEIGHT for url in followed}
        for url in arena_channels(conn):
            pool.setdefault(url, 1)
        picked = _weighted_pick(rng, pool, MAX_CHANNELS)
        jobs += [lambda url=url: arena.pull(url, fetcher, rng) for url in picked]
        if pool:
            seed = rng.choice([url for url in pool if arena.target(url) and arena.target(url)[0] == "channel"] or [""])
            if seed:
                jobs.append(lambda: arena.related_items(seed, fetcher, rng))
    added = failed = 0
    for job in jobs:
        try:
            items = job()
        except Exception:  # noqa: BLE001 - a source that is down is skipped
            failed += 1
            continue
        added += _store(conn, items)
    return {"added": added, "failed": failed, "enabled": sorted(enabled), "terms": chosen}


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
            "INSERT OR IGNORE INTO feed_items (source_id, url, thumb, width, height, title, creator, page_url, term, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["source_id"], item["url"], item["thumb"], item["width"], item["height"], item["title"],
             item["creator"], item["page_url"], item["term"], _now()),
        )
        added += cursor.rowcount
    return added


def list_items(conn, offset=0, limit=60) -> dict:
    """Return unseen feed items, oldest first so later pulls append, with whether the feed is due a refresh."""
    total = conn.execute("SELECT COUNT(*) FROM feed_items WHERE state = 'new'").fetchone()[0]
    rows = conn.execute(
        "SELECT id, source_id, url, thumb, width, height, title, creator, page_url FROM feed_items"
        " WHERE state = 'new' ORDER BY id LIMIT ? OFFSET ?",
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
            conn.execute("UPDATE entries SET source_url = ? WHERE id = ?",
                         (row["page_url"] or row["url"], result["entry_id"]))
        conn.execute("UPDATE feed_items SET state = 'saved' WHERE id = ?", (row["id"],))
        if set_id and sets.place(result["entry_id"], int(set_id)):
            placed += 1
    return {"added": added, "placed": placed}
