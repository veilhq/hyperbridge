"""Find similar: pulls from the Are.na channels that also hold a set's images, searches Are.na for the set's words,
and ranks those finds and the feed's Are.na images against the set."""

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
from bridge.ingest import labels
from bridge.library import sets as set_store

POOL_LIMIT = 5000
PAGE_LIMIT = 1000
QUERIES = 3
QUERY_POOL = 10
PAIR_POOL = 4
PAIR_WEIGHT = 0.8
USED_WEIGHT = 0.1
INFERRED_WEIGHT = 0.25
ARENA_CHANNELS = 3
SHOWN_TERMS = 8
MATCHED_TERMS = 3
SOURCE_PULL = 4.0
QUERY_TERM_WEIGHT = 0.3
NEIGHBOR_BLOCKS = 8
NEIGHBOR_WORKERS = 4
NEIGHBOR_PULLS = 3
NEIGHBOR_QUERIES = 1
NEIGHBOR_WEIGHT = 2.0
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


def set_tags(conn, set_id) -> list:
    """Return the tags given to the set itself, in the order they were entered."""
    row = conn.execute("SELECT tags FROM sets WHERE id = ?", (int(set_id),)).fetchone()
    return set_store.parse_tags(row["tags"]) if row else []


def profile(conn, set_id) -> dict:
    """Return {term: weight} for a set: its own tags at full weight, then the share of its images carrying each term.

    When the set has tags, the terms read from its images count only at INFERRED_WEIGHT; an empty untagged set has none.
    """
    rows = _set_rows(conn, set_id)
    totals = {}
    for row in rows:
        tags = [name for name in str(row["tags"] or "").split(chr(31)) if name]
        for term, weight in _describe(tags, row["collection"], row["creator"], row["title"], row["origin"] or "").items():
            totals[term] = totals.get(term, 0.0) + weight
    own = set_tags(conn, set_id)
    scale = INFERRED_WEIGHT if own else 1.0
    wanted = {term: scale * total / len(rows) for term, total in totals.items()} if rows else {}
    for tag in own:
        _add(wanted, words(tag) | {_named("tag", tag)}, FIELD_WEIGHTS["tag"])
    wanted.pop("", None)
    return wanted


def _item_terms(row) -> dict:
    try:
        tags = list(json.loads(row["tags"] or "[]"))
    except ValueError:
        tags = []
    terms = _describe(tags, row["collection"] or row["term"], row["creator"], row["title"])
    _add(terms, {_named("tag", row["term"])} - {""}, QUERY_TERM_WEIGHT)
    return terms


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
    """Return (scored unseen feed items, best first, each with the terms it matched; the set's profile).

    Items from a channel that also holds the set's images are boosted and kept even when no words match;
    otherwise a set with its own tags only lists items that match one of them.
    """
    wanted = profile(conn, set_id)
    near = neighbor_weights(conn, set_id)
    if not wanted and not near:
        return [], wanted
    closest = max((weight for weight, _, _ in near.values()), default=0.0)
    required = set()
    for tag in set_tags(conn, set_id):
        required |= words(tag) | {_named("tag", tag)}
    rows = conn.execute(
        "SELECT id, source_id, url, thumb, width, height, title, creator, page_url, term, collection, tags, ai_label FROM feed_items"
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
        home = arena.target(row["page_url"])
        weight, title, _ = near.get(home[1], (0.0, "", "")) if home and home[0] == "channel" else (0.0, "", "")
        if not weight and (not shared or (required and not required & shared.keys())):
            continue
        score = sum(shared.values()) / math.sqrt(len(terms)) if shared else 0.0
        if weight:
            score += NEIGHBOR_WEIGHT * weight / closest
        item = {key: row[key] for key in ("id", "source_id", "url", "thumb", "width", "height", "title", "creator", "page_url", "ai_label")}
        matched = top_terms(shared, MATCHED_TERMS) or ([title] if title else [])
        item.update(score=round(score, 4), matched=matched, **_followable(row, followed))
        scored.append(item)
    scored.sort(key=lambda item: (-item["score"], -item["id"]))
    return scored, wanted


def list_items(conn, set_id, offset=0, limit=60, show_flagged=False) -> dict:
    """Return a page of unseen feed items ranked by likeness to a set, with the set's leading terms and whether a new search is due.

    Matches carrying an AI label are left out and counted as flagged unless show_flagged is set.
    """
    scored, wanted = rank(conn, set_id)
    flagged = sum(1 for item in scored if item["ai_label"])
    if not show_flagged:
        scored = [item for item in scored if not item["ai_label"]]
    offset, limit = max(0, int(offset)), max(1, min(int(limit), PAGE_LIMIT))
    newest = conn.execute("SELECT MAX(searched_at) FROM set_searches WHERE set_id = ?", (int(set_id),)).fetchone()[0]
    stale = not newest or (datetime.now() - datetime.fromisoformat(newest)).total_seconds() > feed.STALE_HOURS * 3600
    own = set_tags(conn, set_id)
    if own and not stale:
        searched = {phrase.lower() for phrase in _searched(conn, set_id)}
        stale = any(tag.lower() not in searched for tag in own)
    return {"items": feed.mark_captured(conn, scored[offset:offset + limit]), "total": len(scored), "flagged": flagged, "stale": stale,
            "terms": own or top_terms(wanted)}


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


def _searched(conn, set_id) -> list:
    return [row[0] for row in conn.execute("SELECT phrase FROM set_searches WHERE set_id = ?", (int(set_id),))]


def tag_queries(tags, rng, count=QUERIES, used=()) -> list:
    """Draw search phrases straight from the set's own tags, those not yet searched first."""
    used = {str(phrase).lower() for phrase in used}
    return feed._weighted_pick(rng, {tag: USED_WEIGHT if tag.lower() in used else 1.0 for tag in tags}, count)


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


def _set_blocks(conn, set_id) -> list:
    """Return the Are.na block ids of the set's images, from their recorded origin or their saved source."""
    rows = conn.execute(
        "SELECT DISTINCT COALESCE(o.block_id, CASE WHEN e.source_service = 'arena' AND e.source_ref != ''"
        " THEN CAST(e.source_ref AS INTEGER) END) FROM set_entries se JOIN entries e ON e.id = se.entry_id"
        " LEFT JOIN entry_origins o ON o.entry_id = e.id WHERE se.set_id = ?", (int(set_id),)).fetchall()
    return sorted(int(row[0]) for row in rows if row[0])


def _block_channels(block_id, fetcher):
    try:
        return arena.block_channels(block_id, fetcher)
    except Exception:  # noqa: BLE001 - an unreadable block is tried again on a later refresh
        return None


def find_neighbors(conn, set_id, fetcher, rng) -> int:
    """Record the public Are.na channels holding a sample of the set's images and how many each holds; returns failed lookups."""
    blocks = _set_blocks(conn, set_id)
    sample = rng.sample(blocks, min(NEIGHBOR_BLOCKS, len(blocks)))
    if not sample:
        return 0
    with ThreadPoolExecutor(max_workers=NEIGHBOR_WORKERS) as pool:
        found = list(pool.map(lambda block: _block_channels(block, fetcher), sample))
    shared, channels = {}, {}
    for holders in found:
        for channel in holders or []:
            shared[channel["slug"]] = shared.get(channel["slug"], 0) + 1
            channels[channel["slug"]] = channel
    stamp = datetime.now().isoformat(timespec="seconds")
    conn.executemany(
        "INSERT INTO set_neighbors (set_id, slug, url, title, shared, length, checked_at) VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT (set_id, slug) DO UPDATE SET url = excluded.url, title = excluded.title,"
        " shared = MAX(shared, excluded.shared), length = excluded.length, checked_at = excluded.checked_at",
        [(int(set_id), slug, item["url"], item["title"], shared[slug], item["length"], stamp) for slug, item in channels.items()])
    return sum(1 for holders in found if holders is None)


def neighbor_weights(conn, set_id) -> dict:
    """Return {slug: (weight, title, url)} for the set's neighbor channels; sharing more of the set counts up, sheer size down."""
    rows = conn.execute("SELECT slug, url, title, shared, length FROM set_neighbors WHERE set_id = ?", (int(set_id),)).fetchall()
    return {row["slug"]: (row["shared"] / math.log(row["length"] + 10), row["title"], row["url"]) for row in rows if row["shared"] > 0}


def _pull_one(url, fetcher, rng):
    try:
        return arena.channel_items(url, fetcher, rng), 0
    except Exception:  # noqa: BLE001 - a failed pull leaves the other channels' results
        return [], 1


def _search_one(query, fetcher, rng, closest=False):
    """Search Are.na channel names for one phrase and pull from the closest channel, or one of the closest; returns (items, failed)."""
    try:
        channels = arena.search_channels(query, fetcher)[:ARENA_CHANNELS]
        if not channels:
            return [], 0
        channel = channels[0] if closest else rng.choice(channels)
        return [dict(item, term=query[:100]) for item in arena.channel_items(channel, fetcher, rng)], 0
    except Exception:  # noqa: BLE001 - a failed search leaves the other phrases' results
        return [], 1


def search(conn, set_id, fetcher=None, rng=None) -> dict:
    """Pull from the set's neighbor channels and search Are.na for its leading terms, keeping the images for its Find similar.

    A set with neighbors searches a single phrase in its closest channel, since the neighbors carry most of the likeness.
    """
    fetcher = fetcher or capture.default_fetcher()
    rng = rng or random.Random()
    looked = find_neighbors(conn, set_id, fetcher, rng)
    near = neighbor_weights(conn, set_id)
    urls = feed._weighted_pick(rng, {url: weight for weight, _, url in near.values()}, NEIGHBOR_PULLS)
    used, own = _searched(conn, set_id), set_tags(conn, set_id)
    count = NEIGHBOR_QUERIES if urls else QUERIES
    phrases = tag_queries(own, rng, count, used) if own else queries(profile(conn, set_id), rng, count, used)
    jobs = [lambda url=url: _pull_one(url, fetcher, rng) for url in urls]
    jobs += [lambda phrase=phrase: _search_one(phrase, fetcher, rng, bool(urls)) for phrase in phrases]
    with ThreadPoolExecutor(max_workers=max(1, len(jobs))) as pool:
        found = list(pool.map(lambda job: job(), jobs))
    items = [item for batch, _ in found for item in batch]
    added = feed.store(conn, items, int(set_id))
    stamp = datetime.now().isoformat(timespec="seconds")
    conn.executemany("INSERT OR REPLACE INTO set_searches (set_id, phrase, searched_at) VALUES (?, ?, ?)",
                     [(int(set_id), phrase, stamp) for phrase in phrases])
    return {"added": added, "failed": looked + sum(failed for _, failed in found), "jobs": len(jobs), "queries": phrases,
            "neighbors": urls}


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
    labels.check_new(conn, fetcher)
    enabled = (["neighbors"] if searched["neighbors"] else []) + (["search"] if searched["queries"] else []) + (["arena"] if followed else [])
    return {"added": added, "failed": failed, "jobs": jobs, "enabled": enabled, "queries": searched["queries"]}
