"""Find similar: ranks the discovery feed against one set's words, and pulls from the followed sources closest to it."""

import json
import math
import random
import re
from datetime import datetime
from urllib.parse import urlsplit

from bridge.ingest import arena
from bridge.ingest import capture
from bridge.ingest import feed

POOL_LIMIT = 5000
SHOWN_TERMS = 8
MATCHED_TERMS = 3
SOURCE_PULL = 4.0
FIELD_WEIGHTS = {"tag": 1.0, "collection": 1.0, "origin": 1.0, "creator": 1.0, "title": 0.5}
_WORD = re.compile(r"[a-z0-9][a-z0-9']*")
_STOPWORDS = frozenset(
    "a an and are as at be by for from has have in into is it its of on or our over that the this to under via was were"
    " with you your image images photo photos picture pictures untitled new more best www com http https html jpg png"
    " pin pins board boards channel post posts".split())
_SERVICE_WORDS = frozenset(("are.na", "arena", "pinterest", "tumblr", "instagram", "x"))


def _stem(word) -> str:
    """Fold a simple English plural onto its singular so 'posters' meets 'poster'."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def words(text) -> set:
    """Return the meaningful lowercase words of a piece of text, plurals folded."""
    found = set()
    for word in _WORD.findall(str(text or "").lower()):
        word = word.strip("'")
        if len(word) > 2 and word not in _STOPWORDS and word not in _SERVICE_WORDS and not word.isdigit():
            found.add(_stem(word))
    return found


def _named(kind, name) -> str:
    """Return a whole-name term such as 'collection:brutalism' that only an exact match can hit."""
    name = " ".join(str(name or "").lower().split())
    return f"{kind}:{name}" if name and name not in _SERVICE_WORDS else ""


def _add(found, terms, weight):
    for term in terms:
        if term and weight > found.get(term, 0):
            found[term] = weight


def _describe(tags, collection, creator, title, origin="") -> dict:
    """Return {term: field weight} for one image's tags, collection, origin channel, creator and title."""
    found = {}
    for tag in tags:
        _add(found, words(tag) | {_named("tag", tag)}, FIELD_WEIGHTS["tag"])
    for part in str(collection or "").split(" / "):
        _add(found, words(part) | {_named("collection", part)}, FIELD_WEIGHTS["collection"])
    if origin:
        _add(found, words(origin) | {_named("collection", origin)}, FIELD_WEIGHTS["origin"])
    _add(found, {_named("creator", creator)}, FIELD_WEIGHTS["creator"])
    if not arena.junk_title(title):
        _add(found, words(title), FIELD_WEIGHTS["title"])
    found.pop("", None)
    return found


def _set_rows(conn, set_id):
    return conn.execute(
        "SELECT e.id, e.title, e.creator, e.collection, e.source_url,"
        " (SELECT group_concat(t.name, char(31)) FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE et.entry_id = e.id) AS tags,"
        " (SELECT o.channel_title FROM entry_origins o WHERE o.entry_id = e.id) AS origin"
        " FROM set_entries se JOIN entries e ON e.id = se.entry_id WHERE se.set_id = ?", (int(set_id),)).fetchall()


def profile(conn, set_id) -> dict:
    """Return {term: share of the set's images that carry it, scaled by field weight}; empty for an empty set."""
    rows = _set_rows(conn, set_id)
    totals = {}
    for row in rows:
        tags = [name for name in str(row["tags"] or "").split(chr(31)) if name]
        for term, weight in _describe(tags, row["collection"], row["creator"], row["title"], row["origin"] or "").items():
            totals[term] = totals.get(term, 0.0) + weight
    return {term: total / len(rows) for term, total in totals.items()} if rows else {}


def _item_terms(row) -> dict:
    try:
        tags = list(json.loads(row["tags"] or "[]"))
    except ValueError:
        tags = []
    return _describe(tags, row["collection"] or row["term"], row["creator"], row["title"])


def _label(term) -> str:
    return term.split(":", 1)[1] if ":" in term else term


def top_terms(weights, count=SHOWN_TERMS) -> list:
    """Return the readable names of the heaviest terms, whole names before the single words they contain."""
    seen, names = set(), []
    for term in sorted(weights, key=lambda key: (-weights[key], ":" not in key, key)):
        name = _label(term)
        if name not in seen:
            seen.add(name)
            names.append(name)
        if len(names) == count:
            break
    return names


def rank(conn, set_id) -> tuple:
    """Return (scored unseen feed items, best first, each with the terms it matched; the set's profile)."""
    wanted = profile(conn, set_id)
    if not wanted:
        return [], wanted
    rows = conn.execute(
        "SELECT id, source_id, url, thumb, width, height, title, creator, page_url, term, collection, tags FROM feed_items"
        " WHERE state = 'new' AND source_id IN ('arena', 'tumblr', 'pinterest') ORDER BY id DESC LIMIT ?",
        (POOL_LIMIT,)).fetchall()
    described = [(row, _item_terms(row)) for row in rows]
    counts = {}
    for _, terms in described:
        for term in terms:
            counts[term] = counts.get(term, 0) + 1
    pool = len(described)
    scored = []
    for row, terms in described:
        shared = {term: wanted[term] * weight * math.log((pool + 1) / (counts[term] + 0.5))
                  for term, weight in terms.items() if term in wanted}
        if not shared:
            continue
        score = sum(shared.values()) / math.sqrt(len(terms))
        item = {key: row[key] for key in ("id", "source_id", "url", "thumb", "width", "height", "title", "creator", "page_url")}
        item.update(score=round(score, 4), matched=top_terms(shared, MATCHED_TERMS))
        scored.append(item)
    scored.sort(key=lambda item: (-item["score"], -item["id"]))
    return scored, wanted


def list_items(conn, set_id, offset=0, limit=60) -> dict:
    """Return a page of unseen feed items ranked by likeness to a set, with the set's leading terms and whether the feed is due a refresh."""
    scored, wanted = rank(conn, set_id)
    offset, limit = max(0, int(offset)), max(1, min(int(limit), 200))
    newest = conn.execute("SELECT MAX(created_at) FROM feed_items").fetchone()[0]
    stale = not newest or (datetime.now() - datetime.fromisoformat(newest)).total_seconds() > feed.STALE_HOURS * 3600
    return {"items": scored[offset:offset + limit], "total": len(scored), "stale": stale, "terms": top_terms(wanted)}


def _bare(url) -> str:
    parts = urlsplit(str(url or "").lower())
    return re.sub(r"^www\.", "", parts.netloc) + parts.path.rstrip("/")


def source_weights(conn, set_id, followed, wanted=None) -> dict:
    """Weight each followed source by how well its name matches the set and whether the set's images came from it."""
    wanted = profile(conn, set_id) if wanted is None else wanted
    rows = _set_rows(conn, set_id)
    origins = [_bare(row["source_url"]) for row in rows if row["source_url"]]
    collections = {" ".join(str(part).lower().split()) for row in rows for part in (row["collection"], row["origin"]) if part}
    weights = {}
    for source in followed:
        url, label = source["url"], source.get("label") or ""
        slug = _bare(url).rsplit("/", 1)[-1].replace("-", " ")
        score = sum(wanted.get(term, 0.0) for term in words(label) | words(slug) | {_named("collection", label)})
        home = _bare(url)
        if any(origin.startswith(home) for origin in origins) or " ".join(label.lower().split()) in collections:
            score += 1.0
        weights[url] = 1.0 + SOURCE_PULL * score
    return weights


def refresh(conn, set_id, fetcher=None, rng=None) -> dict:
    """Pull from the followed sources, favoring those closest to the set, until something new arrives or the rounds run out."""
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    feed.prune(conn)
    followed = arena.list_followed(conn)
    weights = source_weights(conn, set_id, followed)
    added = failed = jobs = 0
    for _ in range(feed.ROUNDS):
        pulled, round_failed, round_jobs = feed.pull_round(weights, fetcher, rng)
        failed, jobs = failed + round_failed, jobs + round_jobs
        added += feed.store(conn, pulled)
        if added or not followed or round_failed == round_jobs:
            break
    return {"added": added, "failed": failed, "jobs": jobs, "enabled": ["arena"] if followed else []}
