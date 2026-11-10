"""The discovery feed: images pulled from the followed Are.na channels and ranked by similarity to what is saved."""

import random
import re
from collections import Counter
from datetime import datetime

import arena
import capture
import embed
import sets

MAX_CHANNELS = 3
STALE_HOURS = 6
KEYWORD_SCAN = 500
KEYWORD_TERMS = 10
_WORD_PATTERN = re.compile(r"[a-z]+")
_STOPWORDS = frozenset(
    "this that with from have your about into their there which would could should these those them they what when where "
    "will more most some other than then also only over just like very much many such each both being been were "
    "image images photo photos picture pictures screenshot untitled file page site www http https com jpg jpeg png "
    "webp gif view free download stock official home".split())


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def keyword_counts(conn) -> Counter:
    """Count the words, by entry, in recent titles and descriptions so untagged libraries still steer the feed."""
    counts = Counter()
    rows = conn.execute(
        "SELECT e.title, e.description, COALESCE(o.channel_title, '') AS channel_title FROM entries e"
        " LEFT JOIN entry_origins o ON o.entry_id = e.id ORDER BY e.id DESC LIMIT ?", (KEYWORD_SCAN,))
    for title, description, channel_title in rows:
        title = "" if arena.junk_title(title) else title
        words = _WORD_PATTERN.findall(f"{title} {(description or '')[:300]} {channel_title}".lower())
        counts.update({word for word in words if len(word) >= 4 and word not in _STOPWORDS})
    return counts


def phrase_counts(conn) -> Counter:
    """Count saved images per source channel title, cleaned into a search phrase."""
    counts = Counter()
    for (title,) in conn.execute("SELECT channel_title FROM entry_origins WHERE channel_title != ''"):
        phrase = " ".join(re.sub(r"[^\w ]+", " ", title).split())
        if len(phrase) >= 4:
            counts[phrase] += 1
    return counts


def channel_phrases(conn) -> list:
    """Return the source channel titles saved images came from, most used first, as search phrases."""
    return [phrase for phrase, _ in phrase_counts(conn).most_common(6)]


def search_terms(conn) -> list:
    """Return search words drawn from the library: the most used tags, set names, creators, then title keywords."""
    tags = [row[0] for row in conn.execute(
        "SELECT t.name FROM tags t JOIN entry_tags et ON et.tag_id = t.id"
        " GROUP BY t.id ORDER BY COUNT(*) DESC, t.name LIMIT 12")]
    names = [row[0] for row in conn.execute("SELECT name FROM sets ORDER BY name COLLATE NOCASE LIMIT 12")]
    creators = [row[0] for row in conn.execute(
        "SELECT creator FROM entries WHERE creator != '' GROUP BY creator ORDER BY COUNT(*) DESC LIMIT 8")]
    keywords = [word for word, _ in sorted(keyword_counts(conn).items(), key=lambda pair: (-pair[1], pair[0]))[:KEYWORD_TERMS]]
    seen, terms = set(), []
    for term in [*tags, *names, *channel_phrases(conn), *creators, *keywords]:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            terms.append(term)
    return terms


def term_weights(conn) -> dict:
    """Score each search word by how much of the library uses it, nudged by what was saved or dismissed from it."""
    weights = {}
    keywords = keyword_counts(conn)
    phrases = phrase_counts(conn)
    for term in search_terms(conn):
        used = conn.execute(
            "SELECT (SELECT COUNT(*) FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE t.name = ? COLLATE NOCASE)"
            " + (SELECT COUNT(*) FROM set_entries se JOIN sets s ON s.id = se.set_id WHERE s.name = ? COLLATE NOCASE)"
            " + (SELECT COUNT(*) FROM entries WHERE creator = ? COLLATE NOCASE)", (term, term, term)).fetchone()[0]
        saved, dismissed = conn.execute(
            "SELECT COALESCE(SUM(state = 'saved'), 0), COALESCE(SUM(state = 'dismissed'), 0)"
            " FROM feed_items WHERE term = ? COLLATE NOCASE", (term,)).fetchone()
        weights[term] = max(1, used + keywords.get(term.lower(), 0) + phrases.get(term, 0) + 3 * saved - dismissed)
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


def refresh(conn, fetcher=None, rng=None, embedder=None) -> dict:
    """Pull new images from the followed Are.na channels, rank them against the library, and store the unseen ones."""
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    followed = [item["url"] for item in arena.list_followed(conn)]
    try:
        arena.backfill_origins(conn, fetcher, rng)
    except Exception:  # noqa: BLE001 - missing origins only leave the library less described
        pass
    picked = _weighted_pick(rng, {url: 1 for url in followed}, MAX_CHANNELS)
    jobs = [lambda url=url: arena.pull(url, fetcher, rng) for url in picked]
    failed = 0
    pulled, seen = [], set()
    for job in jobs:
        try:
            items = job()
        except Exception:  # noqa: BLE001 - a channel that is down is skipped
            failed += 1
            continue
        for item in items:
            if item["url"] not in seen:
                seen.add(item["url"])
                pulled.append(item)
    ranked = False
    try:
        ordered = embed.rank(conn, pulled, lambda url: bytes(fetcher(url).body), embedder)
        ranked = ordered is not pulled
        pulled = ordered
    except Exception:  # noqa: BLE001 - without scores the feed keeps source order
        pass
    added = _store(conn, pulled)
    return {"added": added, "failed": failed, "jobs": len(jobs), "enabled": ["arena"] if followed else [],
            "ranked": ranked}



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
            " (source_id, url, thumb, width, height, title, creator, page_url, term, created_at, score)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (item["source_id"], item["url"], item["thumb"], item["width"], item["height"], item["title"],
             item["creator"], item["page_url"], item["term"], _now(), item.get("score")),
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
