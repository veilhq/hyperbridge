"""Sources Discover finds on its own - Are.na channels and people near the library's saves or named like its tags -
and how much each source's images are kept or skipped, which steers how often Discover pulls from it."""

import math
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from bridge.ingest import arena

NEIGHBOR_BLOCKS = 8
RECENT_BLOCKS = 5
NEIGHBOR_WORKERS = 4
OWNER_FACTOR = 0.5
SEARCH_TAGS = 10
SEARCH_PHRASES = 1
SEARCH_RESULTS = 2
SEARCH_STRENGTH = 0.15
CANDIDATE_POOL = 40
DISCOVER_HOURS = 6
LEARN_FLOOR = 0.2
LEARN_CEILING = 2.0
# How much of each Discover round goes to suggested sources, by the New sources setting.
SHARES = {"off": 0.0, "few": 0.2, "some": 1 / 3, "more": 0.5}
ACTIVE = "('candidate', 'offered')"
# An entry's Are.na block id, from its recorded origin or its saved source; needs entries `e` left-joined to entry_origins `o`.
BLOCK_ID = ("COALESCE(o.block_id, CASE WHEN e.source_service = 'arena' AND e.source_ref != ''"
            " THEN CAST(e.source_ref AS INTEGER) END)")


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def bare(url) -> str:
    """Return a link as host and path without scheme, www or trailing slash, lowercased, for comparing sources."""
    parts = urlsplit(str(url or "").lower())
    return re.sub(r"^www\.", "", parts.netloc) + parts.path.rstrip("/")


def strength(shared, length) -> float:
    """Score a channel holding `shared` of the sampled images out of `length` blocks; closer and smaller counts up."""
    return shared / math.log(length + 10)


def learned(keeps, skips) -> float:
    """Return a source's pull factor from its kept and skipped images: 1 with no signal, between the floor and ceiling after."""
    return min(LEARN_CEILING, max(LEARN_FLOOR, 2 * (keeps + 1) / (keeps + skips + 2)))


def _block_channels(block_id, fetcher):
    try:
        return arena.block_channels(block_id, fetcher)
    except Exception:  # noqa: BLE001 - an unreadable block is tried again on a later look
        return None


def holders(blocks, fetcher) -> tuple:
    """Look up the public channels holding each Are.na block; returns ({slug: channel with `shared`}, failed lookups)."""
    if not blocks:
        return {}, 0
    with ThreadPoolExecutor(max_workers=NEIGHBOR_WORKERS) as pool:
        found = list(pool.map(lambda block: _block_channels(block, fetcher), blocks))
    channels = {}
    for held in found:
        for channel in held or []:
            entry = channels.setdefault(channel["slug"], dict(channel, shared=0))
            entry["shared"] += 1
    return channels, sum(1 for held in found if held is None)


def library_blocks(conn, rng, count=NEIGHBOR_BLOCKS) -> list:
    """Return a sample of the library's Are.na block ids: the most recently saved, then a few at random."""
    rows = conn.execute(f"SELECT {BLOCK_ID} FROM entries e LEFT JOIN entry_origins o ON o.entry_id = e.id"
                        " ORDER BY e.created_at DESC, e.id DESC").fetchall()
    blocks = list(dict.fromkeys(int(row[0]) for row in rows if row[0]))
    recent, rest = blocks[:RECENT_BLOCKS], blocks[RECENT_BLOCKS:]
    return recent + rng.sample(rest, min(max(0, count - len(recent)), len(rest)))


def _top_tags(conn) -> list:
    rows = conn.execute("SELECT t.name FROM tags t JOIN entry_tags et ON et.tag_id = t.id"
                        " GROUP BY t.id ORDER BY COUNT(*) DESC, t.name LIMIT ?", (SEARCH_TAGS,)).fetchall()
    return [row[0] for row in rows]


def _owner(url) -> str:
    segments = [part for part in urlsplit(url).path.split("/") if part]
    return segments[0] if len(segments) == 2 and segments[0] != "channel" else ""


def _label(url) -> str:
    return urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1].replace("-", " ")


def _followed(conn) -> set:
    return {bare(row[0]) for row in conn.execute("SELECT url FROM followed_sources")}


def _is_followed(url, followed) -> bool:
    home = bare(url)
    return home in followed or home.rsplit("/", 1)[0] in followed


def _remember(conn, found, followed) -> int:
    """Store found {url: (label, found_by, strength)} as candidates; a known one keeps its state and its best strength."""
    added = 0
    for url, (label, found_by, score) in found.items():
        if _is_followed(url, followed):
            continue
        added += conn.execute(
            "INSERT INTO candidate_sources (url, label, found_by, strength, found_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT (url) DO UPDATE SET strength = MAX(strength, excluded.strength),"
            " label = CASE WHEN label = '' THEN excluded.label ELSE label END",
            (url, str(label)[:200], found_by, score, _now())).rowcount
    return added


def discover(conn, fetcher, rng, force=False) -> int:
    """Find candidate sources near the library's saves (channels holding them and their owners) and named like its top tags.

    Runs at most every DISCOVER_HOURS unless forced; returns how many candidates were stored or refreshed.
    """
    mark = conn.execute("SELECT value FROM feed_marks WHERE name = 'sources_checked'").fetchone()
    if not force and mark and datetime.fromisoformat(mark[0]) > datetime.now() - timedelta(hours=DISCOVER_HOURS):
        return 0
    conn.execute("INSERT INTO feed_marks (name, value) VALUES ('sources_checked', ?)"
                 " ON CONFLICT (name) DO UPDATE SET value = excluded.value", (_now(),))
    found, owners = {}, {}
    channels, _ = holders(library_blocks(conn, rng), fetcher)
    for channel in channels.values():
        score = strength(channel["shared"], channel["length"])
        found[channel["url"]] = (channel["title"] or channel["slug"], "neighbor", score)
        owner = _owner(channel["url"])
        if owner:
            owners[owner] = owners.get(owner, 0.0) + score
    for owner, score in owners.items():
        found.setdefault(f"https://www.are.na/{owner}", (owner, "owner", OWNER_FACTOR * score))
    tags = _top_tags(conn)
    for phrase in rng.sample(tags, min(SEARCH_PHRASES, len(tags))):
        try:
            urls = arena.search_channels(phrase, fetcher)[:SEARCH_RESULTS]
        except Exception:  # noqa: BLE001 - a failed search leaves the neighbor finds
            continue
        for rank, url in enumerate(urls):
            found.setdefault(url, (_label(url), "search", SEARCH_STRENGTH / (rank + 1)))
    return _remember(conn, found, _followed(conn))


def tallies(conn) -> dict:
    """Return {source url: (kept, skipped)} over the feed images each source supplied; unseen images do not count."""
    rows = conn.execute("SELECT origin_url, SUM(state = 'saved'), SUM(state = 'dismissed') FROM feed_items"
                        " WHERE origin_url != '' GROUP BY origin_url").fetchall()
    return {row[0]: (row[1] or 0, row[2] or 0) for row in rows}


def settle_followed(conn) -> None:
    """Mark candidates the Operator has since followed by any route, so they leave the suggestion pool."""
    followed = _followed(conn)
    for row in conn.execute(f"SELECT url FROM candidate_sources WHERE state IN {ACTIVE}").fetchall():
        if _is_followed(row[0], followed):
            conn.execute("UPDATE candidate_sources SET state = 'followed' WHERE url = ?", (row[0],))


def review(conn, offer_keeps, drop_skips) -> None:
    """Offer a follow for candidates kept `offer_keeps` times and drop those skipped `drop_skips` times with none kept."""
    tally = tallies(conn)
    for row in conn.execute(f"SELECT url, state FROM candidate_sources WHERE state IN {ACTIVE}").fetchall():
        keeps, skips = tally.get(row["url"], (0, 0))
        if keeps == 0 and skips >= drop_skips:
            conn.execute("UPDATE candidate_sources SET state = 'declined' WHERE url = ?", (row["url"],))
        elif row["state"] == "candidate" and keeps >= offer_keeps:
            conn.execute("UPDATE candidate_sources SET state = 'offered' WHERE url = ?", (row["url"],))


def mixed_weights(conn, followed_urls, share) -> tuple:
    """Return ({url: weight}, candidate urls) for one Discover round: followed sources by learned factor, plus
    suggested ones by strength times learned factor, scaled to take about `share` of the draw."""
    tally = tallies(conn)
    weights = {url: learned(*tally.get(url, (0, 0))) for url in followed_urls}
    if share <= 0:
        return weights, set()
    rows = conn.execute(f"SELECT url, strength FROM candidate_sources WHERE state IN {ACTIVE}"
                        " ORDER BY strength DESC LIMIT ?", (CANDIDATE_POOL,)).fetchall()
    raw = {row["url"]: max(row["strength"], 1e-3) * learned(*tally.get(row["url"], (0, 0)))
           for row in rows if row["url"] not in weights}
    if not raw:
        return weights, set()
    scale = sum(weights.values()) * share / (1 - share) / sum(raw.values()) if weights else 1.0
    weights.update({url: weight * scale for url, weight in raw.items()})
    return weights, set(raw)


def mark_pulled(conn, urls) -> None:
    """Record when candidate sources were last pulled from."""
    conn.executemany("UPDATE candidate_sources SET pulled_at = ? WHERE url = ?", [(_now(), url) for url in urls])


def next_offer(conn, offer_keeps, drop_skips) -> dict | None:
    """Return the one candidate Discover should offer to follow - {url, label, keeps} - or None."""
    review(conn, offer_keeps, drop_skips)
    tally = tallies(conn)
    rows = conn.execute("SELECT url, label FROM candidate_sources WHERE state = 'offered' ORDER BY strength DESC, url").fetchall()
    if not rows:
        return None
    best = max(rows, key=lambda row: tally.get(row["url"], (0, 0))[0])
    return {"url": best["url"], "label": best["label"] or _label(best["url"]), "keeps": tally.get(best["url"], (0, 0))[0]}


def answer(conn, url, yes, follow) -> dict:
    """Follow an offered candidate with `follow(conn, url)` on yes, or turn it down for good on no."""
    row = conn.execute("SELECT url FROM candidate_sources WHERE url = ?", (str(url),)).fetchone()
    if not row:
        raise ValueError("That suggestion is gone.")
    if not yes:
        conn.execute("UPDATE candidate_sources SET state = 'declined' WHERE url = ?", (row["url"],))
        return {"followed": False}
    item = follow(conn, row["url"])
    conn.execute("UPDATE candidate_sources SET state = 'followed' WHERE url = ?", (row["url"],))
    return {"followed": True, "item": item}
