"""Find similar: searches Are.na for one set's words, and ranks those finds and the feed's Are.na images against the set."""

import json
import math
import random
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from urllib.parse import urlsplit

from bridge.ingest import arena
from bridge.ingest import capture
from bridge.ingest import feed

POOL_LIMIT = 5000
PAGE_LIMIT = 1000
QUERIES = 3
QUERY_POOL = 10
PAIR_POOL = 4
PAIR_WEIGHT = 0.8
USED_WEIGHT = 0.1
ARENA_CHANNELS = 3
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


def _followable(row, followed) -> dict:
    """Return the Are.na channel an image came from when neither it nor its owner is followed, else nothing."""
    found = arena.target(row["page_url"])
    home = _bare(row["page_url"])
    if not found or found[0] != "channel" or home in followed or home.rsplit("/", 1)[0] in followed:
        return {}
    return {"follow_url": row["page_url"], "follow_label": row["collection"] or found[1]}


def rank(conn, set_id) -> tuple:
    """Return (scored unseen feed items, best first, each with the terms it matched; the set's profile)."""
    wanted = profile(conn, set_id)
    if not wanted:
        return [], wanted
    rows = conn.execute(
        "SELECT id, source_id, url, thumb, width, height, title, creator, page_url, term, collection, tags FROM feed_items"
        " WHERE state = 'new' AND (set_id IS NULL OR set_id = ?) AND source_id = 'arena'"
        " ORDER BY id DESC LIMIT ?", (int(set_id), POOL_LIMIT)).fetchall()
    followed = {_bare(source["url"]) for source in arena.list_followed(conn)}
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
        item.update(score=round(score, 4), matched=top_terms(shared, MATCHED_TERMS), **_followable(row, followed))
        scored.append(item)
    scored.sort(key=lambda item: (-item["score"], -item["id"]))
    return scored, wanted


def list_items(conn, set_id, offset=0, limit=60) -> dict:
    """Return a page of unseen feed items ranked by likeness to a set, with the set's leading terms and whether a new search is due."""
    scored, wanted = rank(conn, set_id)
    offset, limit = max(0, int(offset)), max(1, min(int(limit), PAGE_LIMIT))
    newest = conn.execute("SELECT MAX(created_at) FROM feed_items WHERE set_id = ?", (int(set_id),)).fetchone()[0]
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


def queries(wanted, rng, count=QUERIES, used=()) -> list:
    """Draw a few search phrases from the set's heaviest terms and pairs of them, favoring heavier and not yet searched ones."""
    weights = {}
    for term, weight in wanted.items():
        name = _label(term)
        if term.startswith("creator:") or name.startswith(("http", "www.")):
            continue
        if weight > weights.get(name, 0):
            weights[name] = weight
    best = dict(sorted(weights.items(), key=lambda pair: -pair[1])[:QUERY_POOL])
    leaders = list(best)[:PAIR_POOL]
    for index, first in enumerate(leaders):
        for second in leaders[index + 1:]:
            if first not in second and second not in first:
                best[f"{first} {second}"] = min(best[first], best[second]) * PAIR_WEIGHT
    used = {str(phrase).lower() for phrase in used}
    return feed._weighted_pick(rng, {phrase: weight * (USED_WEIGHT if phrase in used else 1.0) for phrase, weight in best.items()}, count)


def _search_one(query, fetcher, rng):
    """Search Are.na channel names for one phrase and pull from one of the closest channels; returns (items, failed searches)."""
    try:
        channels = arena.search_channels(query, fetcher)[:ARENA_CHANNELS]
        if not channels:
            return [], 0
        return [dict(item, term=query[:100]) for item in arena.channel_items(rng.choice(channels), fetcher, rng)], 0
    except Exception:  # noqa: BLE001 - a failed search leaves the other phrases' results
        return [], 1


def search(conn, set_id, fetcher=None, rng=None) -> dict:
    """Search Are.na for the set's leading terms and keep the images for that set's Find similar."""
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    used = [row[0] for row in conn.execute("SELECT DISTINCT term FROM feed_items WHERE set_id = ?", (int(set_id),))]
    phrases = queries(profile(conn, set_id), rng, used=used)
    with ThreadPoolExecutor(max_workers=max(1, len(phrases))) as pool:
        found = list(pool.map(lambda phrase: _search_one(phrase, fetcher, rng), phrases))
    items = [item for batch, _ in found for item in batch]
    added = feed.store(conn, items, int(set_id))
    return {"added": added, "failed": sum(failed for _, failed in found), "jobs": len(phrases), "queries": phrases}


def refresh(conn, set_id, fetcher=None, rng=None) -> dict:
    """Search Are.na for the set, then pull once from the followed Are.na channels and users closest to it."""
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    feed.prune(conn)
    searched = search(conn, set_id, fetcher, rng)
    followed = [source for source in arena.list_followed(conn) if arena.target(source["url"])]
    added, failed, jobs = searched["added"], searched["failed"], searched["jobs"]
    if followed:
        pulled, round_failed, round_jobs = feed.pull_round(source_weights(conn, set_id, followed), fetcher, rng)
        added += feed.store(conn, pulled)
        failed, jobs = failed + round_failed, jobs + round_jobs
    enabled = (["search"] if searched["queries"] else []) + (["arena"] if followed else [])
    return {"added": added, "failed": failed, "jobs": jobs, "enabled": enabled, "queries": searched["queries"]}
