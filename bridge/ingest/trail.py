"""Rabbit-hole trails: where one image leads (Are.na channels and people, Tumblr blogs, sites, creators, tags and colors).

A place on another site is checked with one paced request whose reply is also its first page of images. Checks run one
at a time under a per-trail request budget, are reused for a day, and leave a host alone while it is cooling down.
Trails never call Pinterest.
"""

import json
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from urllib.parse import urlsplit

from bridge.core.pacer import host_of
from bridge.ingest import arena, checks, feed, rss, sources, tumblr
from bridge.library import creators, swatches

BUDGET = 40
CACHE_DAYS = 1
MAX_CHANNELS = 12
MAX_TAGS = 5
SEARCH_TAGS = 2
TAG_CHANNELS = 3
MIN_TAG = 3
SITE_TAGS = frozenset({"are.na", "instagram", "x"})
STEP_LIMIT = 200
KEEP_TRAILS = 32
FOLLOWABLE = ("channel", "user", "blog", "site")
_SKIPPED_HOSTS = ("pinterest.", "pin.it", "x.com", "twitter.com", "instagram.com")
_LOCK = threading.Lock()
_SPENT = OrderedDict()


class BudgetSpent(Exception):
    """Raised instead of a request once a trail has spent its budget."""


def _now() -> datetime:
    return datetime.now()


def spent(trail) -> int:
    """Return how many outside requests a trail has made."""
    return _SPENT.get(str(trail), 0)


def _spend(trail) -> None:
    trail = str(trail)
    _SPENT[trail] = _SPENT.get(trail, 0) + 1
    _SPENT.move_to_end(trail)
    while len(_SPENT) > KEEP_TRAILS:
        _SPENT.popitem(last=False)


def _counted(fetcher, trail, forced):
    """Wrap fetcher so each request counts against the trail; unforced requests stop once the budget is spent."""
    def fetch(url, **kwargs):
        if not forced and spent(trail) >= BUDGET:
            raise BudgetSpent()
        _spend(trail)
        return fetcher(url, **kwargs)
    return fetch


def _cooling(fetcher, host) -> bool:
    check = getattr(fetcher, "is_cooling", None)
    return bool(check and check(host))


def _skipped(host) -> bool:
    host = host.removeprefix("www.")
    return any(host.startswith(name) or host == name for name in _SKIPPED_HOSTS)


def place_for(url, label=""):
    """Return {kind, url, label} for a link a trail can step to: an Are.na channel or user, a Tumblr blog, or a site.

    Pinterest, X and Instagram links return None.
    """
    found = arena.target(url or "")
    if found:
        kind = "channel" if found[0] == "channel" else "user"
        path = "/".join(part for part in urlsplit(url).path.split("/") if part)
        return {"kind": kind, "url": f"https://www.are.na/{path}", "label": label or found[1].replace("-", " ")}
    host = host_of(url)
    if not host or "." not in host or _skipped(host) or host.endswith("are.na"):
        return None
    kind = "blog" if host.endswith(".tumblr.com") else "site"
    return {"kind": kind, "url": f"https://{host}/", "label": label or host.removeprefix("www.")}


def _request_host(hop) -> str:
    return "api.are.na" if hop["kind"] in ("channel", "user") else host_of(hop["url"])


def load_item(conn, ref) -> dict | None:
    """Return the fields hops are built from for {"entry": id} or {"feed": id}, or None when it is gone."""
    if ref.get("entry"):
        row = conn.execute("SELECT * FROM entries WHERE id = ?", (int(ref["entry"]),)).fetchone()
        if not row:
            return None
        tags = [item[0] for item in conn.execute(
            "SELECT t.name FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE et.entry_id = ? ORDER BY t.name", (row["id"],))]
        origin = conn.execute("SELECT channel_slug, channel_title FROM entry_origins WHERE entry_id = ?", (row["id"],)).fetchone()
        item = dict(row, kind="entry", service=row["source_service"], page_url=row["source_url"], tags=tags,
                    origin_url="", channel_slug=origin["channel_slug"] if origin else "",
                    channel_title=origin["channel_title"] if origin else "")
        return item
    row = conn.execute("SELECT * FROM feed_items WHERE id = ?", (int(ref.get("feed") or 0),)).fetchone()
    if not row:
        return None
    return dict(row, kind="feed", service=row["source_id"], tags=json.loads(row["tags"] or "[]"), channel_slug="",
                channel_title="", color_family=None, swatches="[]", domain="")


def _outside(item) -> list:
    """Return the places on other sites an image leads to, from its stored fields; no requests."""
    found = []
    service = item["service"]
    if service == "pinterest":
        return found
    if service == "arena":
        channel = place_for(item["page_url"], item["collection"])
        if channel and channel["kind"] == "channel":
            found.append(channel)
        elif item["channel_slug"]:
            found.append(place_for(f"https://www.are.na/channel/{item['channel_slug']}", item["channel_title"]))
        found.append(place_for(item["creator_handle"]))
        found.append(place_for(item["source_link"]))
    elif service == "tumblr":
        blog = place_for(item["creator_handle"] or item["page_url"], item["collection"])
        if blog:
            found.append(dict(blog, kind="blog"))
        for field, label in (("reblog_from", "Reblogged from"), ("reblog_root", "First posted by")):
            place = place_for(item[field])
            if place:
                found.append(dict(place, kind="blog", label=f"{label} {place['label']}"))
    elif service == "rss":
        site = place_for(item["origin_url"] or item["page_url"], item["collection"])
        if site:
            found.append(dict(site, feed_url=item["origin_url"]))
        found.append(place_for(f"https://{item['publisher']}/" if item["publisher"] else ""))
    elif service not in ("x", "instagram"):
        found.append(place_for(item["page_url"]))
    return [place for place in found if place]


def _block_id(conn, item) -> int | None:
    if item["service"] == "arena" and str(item["source_ref"]).isdigit():
        return int(item["source_ref"])
    if item["kind"] == "entry":
        row = conn.execute("SELECT block_id FROM entry_origins WHERE entry_id = ?", (item["id"],)).fetchone()
        return int(row[0]) if row and row[0] else None
    return None


def _cached(conn, url):
    fresh = (_now() - timedelta(days=CACHE_DAYS)).isoformat(timespec="seconds")
    return conn.execute("SELECT * FROM trail_places WHERE url = ? AND checked_at >= ?", (url, fresh)).fetchone()


def _remember(conn, url, kind, label, count, images=(), feed_url="", next_page="", extra=()) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO trail_places (url, kind, label, count, feed_url, next_page, images, extra, checked_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (url, kind, str(label)[:200], int(count), feed_url, str(next_page), json.dumps(list(images)),
         json.dumps(list(extra)), _now().isoformat(timespec="seconds")))


def _search_tags(item) -> list:
    """Return the tags an image's check searches Are.na for: its first few that are long enough to mean something.

    Tags that only name a site (Are.na, Instagram, X) are skipped."""
    return [tag for tag in item["tags"][:MAX_TAGS]
            if len(tag.strip()) >= MIN_TAG and tag.strip().lower() not in SITE_TAGS][:SEARCH_TAGS]


def _search_key(tag) -> str:
    return f"search:{tag.strip().lower()}"


def _followed(conn) -> set:
    return {sources.bare(row[0]) for row in conn.execute("SELECT url FROM followed_sources")}


def _library_hops(conn, item) -> list:
    """Return the creator, tag and color places in the library an image leads to, each with how many images it holds."""
    found = []
    own = item["id"] if item["kind"] == "entry" else 0
    person = creators.for_handle(conn, item["creator_handle"]) or creators.for_name(conn, item["creator"])
    if person:
        count = len([entry for entry in creators.entry_ids(conn, person) if entry != own])
        found.append({"kind": "creator", "url": f"creator:{person['id']}", "label": person["name"], "count": count,
                      "places": len(person["handles"])})
    elif len(creators.key(item["creator"])) >= creators.MIN_KEY:
        count = conn.execute("SELECT COUNT(*) FROM entries WHERE lower(creator) = lower(?) AND id != ?",
                             (item["creator"], own)).fetchone()[0]
        found.append({"kind": "creator", "url": f"credit:{item['creator']}", "label": item["creator"], "count": count})
    for tag in item["tags"][:MAX_TAGS]:
        count = conn.execute(
            "SELECT COUNT(*) FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE t.name = ? AND et.entry_id != ?",
            (tag, own)).fetchone()[0]
        found.append({"kind": "tag", "url": f"tag:{tag}", "label": tag, "count": count})
    if item["kind"] == "entry" and item["swatches"] not in ("", "[]"):
        count = conn.execute("SELECT COUNT(*) FROM entries WHERE color_family = ? AND id != ?",
                             (item["color_family"], own)).fetchone()[0]
        found.append({"kind": "color", "url": f"color:{item['color_family']}",
                      "label": swatches.family_name(item["color_family"]), "count": count})
    return [dict(hop, state="ready") for hop in found if hop["count"] > 0]


def _place_hop(conn, place, fetcher, followed) -> dict | None:
    """Return a hop for an outside place with its checked count, or None when it was checked and found empty."""
    hop = {"kind": place["kind"], "url": place["url"], "label": place["label"], "count": None, "state": "unchecked",
           "followable": True, "followed": sources.bare(place["url"]) in followed
           or sources.bare(place.get("feed_url") or "") in followed}
    if place.get("feed_url"):
        hop["feed_url"] = place["feed_url"]
    if place.get("via"):
        hop["via"] = place["via"]
    if "count" in place:
        hop.update(count=place["count"], state="ready")
    row = _cached(conn, place["url"])
    if row:
        if row["count"] <= 0:
            return None
        hop.update(count=row["count"], state="ready")
    elif hop["state"] == "unchecked" and fetcher is not None and _cooling(fetcher, _request_host(hop)):
        hop["state"] = "cooling"
    if hop["kind"] in ("user", "blog"):
        match = creators.suggest(conn, hop["url"])
        if match:
            hop["suggest"] = match
    return hop


def hops(conn, ref, fetcher=None) -> dict:
    """Return {hops, pending} for an image: library places, then places on other sites from stored fields and checks
    made in the last day, including Are.na channels found by searching its tags. Makes no requests; places not yet
    checked come back unchecked, or cooling while their host is, and pending says a check still has lookups to make."""
    item = load_item(conn, ref)
    if not item:
        return {"hops": [], "pending": False}
    followed = _followed(conn)
    places = _outside(item)
    block = _block_id(conn, item)
    held = _cached(conn, f"block:{block}") if block else None
    if held:
        places.extend(dict(channel, kind="channel") for channel in json.loads(held["extra"]))
    pending = bool(block and not held)
    for tag in _search_tags(item):
        searched = _cached(conn, _search_key(tag))
        if searched:
            places.extend(dict(channel, kind="channel") for channel in json.loads(searched["extra"]))
        else:
            pending = True
    found, seen = [], set()
    for place in places:
        if place["url"] in seen:
            continue
        seen.add(place["url"])
        hop = _place_hop(conn, place, fetcher, followed)
        if hop:
            found.append(hop)
    return {"hops": _library_hops(conn, item) + found, "pending": pending}


def _store_images(conn, url, items) -> list:
    feed.store(conn, items, trail=url)
    return list(dict.fromkeys(item["url"] for item in items))


def _arena_page(conn, place, fetcher, page) -> tuple:
    """Read one contents page of an Are.na channel or user; returns (image links, total, next page)."""
    kind, slug = arena.target(place["url"])
    if kind == "channel":
        data = arena._json(fetcher, arena._contents_url(slug, page))
        owner = [part for part in urlsplit(place["url"]).path.split("/") if part][0]
        items = [arena.block_item(block, place["url"], place["label"], owner)
                 for block in data.get("data") or [] if arena._usable(block)]
    else:
        data = arena._json(fetcher, f"{arena.API_V3}/users/{slug}/contents?per={arena.PAGE_SIZE}&page={page}")
        items = [arena.block_item(block, f"https://www.are.na/block/{block.get('id')}", slug, slug)
                 for block in data.get("data") or [] if arena._usable(block)]
    meta = data.get("meta") or {}
    pages = int(meta.get("total_pages") or 1)
    total = int(meta.get("total_count") or meta.get("total") or 0) or (len(items) if pages <= 1 else pages * arena.PAGE_SIZE)
    more = bool(meta.get("has_more_pages")) or page < pages
    return _store_images(conn, place["url"], items), total, str(page + 1) if more and items else ""


def _tumblr_page(conn, place, fetcher, start) -> tuple:
    host = host_of(place["url"])
    data = tumblr._read(fetcher, host, start, tumblr.PAGE)
    total = int(data.get("posts-total") or 0)
    following = start + tumblr.PAGE
    return _store_images(conn, place["url"], tumblr.page_items(data, host)), total, str(following) if following < total else ""


def _site_page(conn, place, fetcher) -> tuple:
    feed_url, root = rss.find_feed(place.get("feed_url") or place["url"], fetcher)
    title, found = rss.entries(root, feed_url)
    collection = (title or host_of(feed_url))[:200]
    links = _store_images(conn, place["url"], rss.entry_items([entry for entry in found if entry["images"]], collection, feed_url))
    return links, len(links), "", feed_url


def _read_place(conn, place, fetcher) -> None:
    """Check one place with its first-page request and remember its count and images for a day."""
    feed_url = ""
    if place["kind"] in ("channel", "user"):
        links, total, following = _arena_page(conn, place, fetcher, 1)
    elif place["kind"] == "blog" or host_of(place["url"]).endswith(".tumblr.com"):
        links, total, following = _tumblr_page(conn, place, fetcher, 0)
    else:
        try:
            links, total, following, feed_url = _site_page(conn, place, fetcher)
        except ValueError:
            links, total, following = [], 0, ""
    _remember(conn, place["url"], place["kind"], place["label"], total if links else 0, links, feed_url, following)


def _fail_quietly(conn, place, err) -> str:
    """Return the hop state after a failed check: cooling on pushback, else the place is remembered as empty."""
    if checks.pushed_back(err):
        return "cooling"
    _remember(conn, place["url"], place["kind"], place["label"], 0)
    return "empty"


def check(conn, ref, trail, fetcher) -> dict:
    """Check the unchecked places an image leads to, one request each and one at a time, within the trail's budget.

    An Are.na image first looks up the channels holding it, and the first few tags are searched for Are.na channels;
    both replies carry the channels' counts. Returns {hops, left}.
    """
    with _LOCK:
        counted = _counted(fetcher, trail, forced=False)
        item = load_item(conn, ref)
        if not item:
            return {"hops": [], "left": max(0, BUDGET - spent(trail))}
        block = _block_id(conn, item)
        try:
            if block and not _cached(conn, f"block:{block}") and not _cooling(fetcher, "api.are.na"):
                try:
                    held = arena.block_channels(block, counted)[:MAX_CHANNELS]
                    _remember(conn, f"block:{block}", "block", "", len(held), extra=[
                        {"url": place_for(channel["url"])["url"], "label": channel["title"] or channel["slug"],
                         "count": channel["length"]} for channel in held if place_for(channel["url"])])
                except BudgetSpent:
                    raise
                except Exception as err:  # noqa: BLE001 - an unreadable block only leaves its channels out
                    if not checks.pushed_back(err):
                        _remember(conn, f"block:{block}", "block", "", 0)
            for tag in _search_tags(item):
                if _cached(conn, _search_key(tag)) or _cooling(fetcher, "api.are.na"):
                    continue
                try:
                    found = arena.search_channel_details(tag, counted)[:TAG_CHANNELS]
                    _remember(conn, _search_key(tag), "search", tag, len(found), extra=[
                        {"url": place_for(channel["url"])["url"], "label": channel["title"] or channel["slug"],
                         "count": channel["length"], "via": tag} for channel in found if place_for(channel["url"])])
                except BudgetSpent:
                    raise
                except Exception as err:  # noqa: BLE001 - a failed search only leaves that tag's channels out
                    if not checks.pushed_back(err):
                        _remember(conn, _search_key(tag), "search", tag, 0)
            for hop in hops(conn, ref, fetcher)["hops"]:
                if hop["state"] != "unchecked":
                    continue
                if _cooling(fetcher, _request_host(hop)):
                    continue
                try:
                    _read_place(conn, hop, counted)
                except BudgetSpent:
                    raise
                except Exception as err:  # noqa: BLE001 - a place that cannot be read is left out or waits out its host
                    _fail_quietly(conn, hop, err)
        except BudgetSpent:
            pass
        return {"hops": hops(conn, ref, fetcher)["hops"], "left": max(0, BUDGET - spent(trail))}


def _feed_images(conn, links) -> list:
    if not links:
        return []
    rows = {row["url"]: dict(row) for row in conn.execute(
        "SELECT id, source_id, url, thumb, width, height, title, creator, page_url, collection FROM feed_items"
        f" WHERE url IN ({', '.join('?' * len(links))})", links)}
    items = [dict(rows[link], type="feed") for link in links if link in rows]
    return feed.mark_captured(conn, items)


def _library_images(conn, url) -> dict:
    kind, _, value = url.partition(":")
    places = []
    if kind == "creator":
        person = creators._row(conn, int(value)) if value.isdigit() else None
        ids = creators.entry_ids(conn, person, STEP_LIMIT) if person else []
        for handle in (person or {}).get("handles", []):
            place = place_for(handle["url"])
            if place:
                places.append(place)
    elif kind == "credit":
        ids = [row[0] for row in conn.execute(
            "SELECT id FROM entries WHERE lower(creator) = lower(?) ORDER BY created_at DESC, id DESC LIMIT ?", (value, STEP_LIMIT))]
    elif kind == "tag":
        ids = [row[0] for row in conn.execute(
            "SELECT e.id FROM entries e JOIN entry_tags et ON et.entry_id = e.id JOIN tags t ON t.id = et.tag_id"
            " WHERE t.name = ? ORDER BY e.created_at DESC, e.id DESC LIMIT ?", (value, STEP_LIMIT))]
    elif kind == "color" and value.lstrip("-").isdigit():
        ids = [row[0] for row in conn.execute(
            "SELECT id FROM entries WHERE color_family = ? ORDER BY created_at DESC, id DESC LIMIT ?", (int(value), STEP_LIMIT))]
    else:
        ids = []
    followed = _followed(conn)
    hops_out = [hop for hop in (_place_hop(conn, place, None, followed) for place in places) if hop]
    return {"images": [{"type": "entry", "id": entry_id} for entry_id in ids], "more": False, "count": len(ids),
            "state": "ready", "places": hops_out}


def images(conn, place, trail, fetcher, more=False) -> dict:
    """Return a place's images {images, more, count, state, places}: library places from the database, outside places
    from the day's check or, when picked unchecked, one request now. more reads the next page."""
    url = str(place.get("url") or "")
    if url.split(":", 1)[0] in ("creator", "credit", "tag", "color"):
        return _library_images(conn, url)
    target = place_for(url, place.get("label") or "")
    if not target:
        return {"images": [], "more": False, "count": 0, "state": "empty", "places": []}
    target = dict(target, kind=place.get("kind") or target["kind"], feed_url=place.get("feed_url") or "")
    with _LOCK:
        row = _cached(conn, target["url"])
        if (not row or (more and row["next_page"])) and _cooling(fetcher, _request_host(target)):
            return {"images": _feed_images(conn, json.loads(row["images"])) if row else [], "more": False,
                    "count": row["count"] if row else 0, "state": "cooling", "places": []}
        counted = _counted(fetcher, trail, forced=True)
        try:
            if not row:
                _read_place(conn, target, counted)
            elif more and row["next_page"]:
                _read_next(conn, target, row, counted)
        except Exception as err:  # noqa: BLE001 - a place that cannot be read shows what it already has
            state = _fail_quietly(conn, target, err) if not row else ("cooling" if checks.pushed_back(err) else "ready")
            if not row:
                return {"images": [], "more": False, "count": 0, "state": state, "places": []}
        row = _cached(conn, target["url"])
    links = json.loads(row["images"]) if row else []
    return {"images": _feed_images(conn, links), "more": bool(row and row["next_page"]),
            "count": row["count"] if row else 0, "state": "ready" if links else "empty", "places": []}


def _read_next(conn, place, row, fetcher) -> None:
    if place["kind"] in ("channel", "user"):
        links, _, following = _arena_page(conn, place, fetcher, int(row["next_page"]))
    else:
        links, _, following = _tumblr_page(conn, place, fetcher, int(row["next_page"]))
    merged = list(dict.fromkeys(json.loads(row["images"]) + links))
    conn.execute("UPDATE trail_places SET images = ?, next_page = ? WHERE url = ?",
                 (json.dumps(merged), following, row["url"]))


def save(conn, feed_ids, set_id=None) -> dict:
    """Keep trail images in the library, optionally in a set, the same way Discover saves.

    Returns {added, placed, entry_ids} with entry_ids mapping each kept feed id to its library entry."""
    ids = [int(feed_id) for feed_id in (feed_ids if isinstance(feed_ids, (list, tuple)) else [feed_ids])]
    if not ids:
        return {"added": 0, "placed": 0, "entry_ids": {}}
    marks = ", ".join("?" * len(ids))
    conn.execute(f"UPDATE feed_items SET state = 'new' WHERE id IN ({marks}) AND state = 'dismissed'", ids)
    rows = conn.execute(f"SELECT id, url FROM feed_items WHERE id IN ({marks})", ids).fetchall()
    if not rows:
        return {"added": 0, "placed": 0, "entry_ids": {}}
    result = feed.accept(conn, [row["id"] for row in rows], set_id)
    known = feed.mark_captured(conn, [{"id": row["id"], "url": row["url"]} for row in rows])
    return dict(result, entry_ids={str(item["id"]): item["known_entry_id"] for item in known if item["known_entry_id"]})
