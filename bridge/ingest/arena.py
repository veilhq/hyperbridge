"""Are.na sampling for the discovery feed: channels, followed channels and users, and the channels that hold a given block."""

import json
import re
from datetime import datetime
from urllib.parse import urlencode, urlsplit

from bridge.ingest import capture, checks
from bridge.ingest import discover

API = "https://api.are.na/v2"
API_V3 = "https://api.are.na/v3"
PAGE_SIZE = 100
MAX_PAGES = 20
PER_CHANNEL = 12
_RESERVED = {"explore", "search", "block", "blocks", "about", "pricing", "tools", "log-in", "sign-up", "feed", "notifications"}


def _json(fetcher, url) -> dict:
    """Read one JSON reply; a failure, including a rate limit, is raised rather than retried."""
    return json.loads(bytes(fetcher(url).body).decode("utf-8", "replace"))


def target(url):
    """Return ("channel", slug) or ("user", slug) for an Are.na link, or None for any other link."""
    parts = urlsplit(url or "")
    if (parts.hostname or "").lower() not in ("are.na", "www.are.na"):
        return None
    slug = discover._arena_slug(url)
    if slug:
        return "channel", slug
    segments = [part for part in parts.path.split("/") if part]
    if len(segments) == 1 and segments[0] not in _RESERVED:
        return "user", segments[0]
    return None


def _contents_url(slug, page) -> str:
    return f"{API_V3}/channels/{slug}/contents?per={PAGE_SIZE}&page={page}"


def _text(value) -> str:
    """Return the plain text of an Are.na description, which the v3 API gives as an object."""
    if isinstance(value, dict):
        return value.get("plain") or value.get("markdown") or ""
    return value or ""


def channel_blocks(slug, fetcher, rng, newest=False):
    """Return (title, blocks) from a random page of a channel, or with newest set its first and last pages newest first."""
    info = _json(fetcher, f"{API_V3}/channels/{slug}")
    length = int((info.get("counts") or {}).get("contents") or 0)
    pages = max(1, -(-length // PAGE_SIZE))
    if newest:
        blocks = [block for page in sorted({1, pages}) for block in _json(fetcher, _contents_url(slug, page)).get("data") or []]
        return info.get("title") or "", newest_first(blocks)
    data = _json(fetcher, _contents_url(slug, rng.randint(1, min(MAX_PAGES, pages))))
    return info.get("title") or "", data.get("data") or []


def newest_first(blocks) -> list:
    """Return blocks ordered by when they were added, newest first, whichever way the API listed them."""
    return sorted(blocks, key=lambda block: str(block.get("connected_at") or block.get("created_at") or ""), reverse=True)


def _usable(block) -> bool:
    return bool((block.get("image") or {}).get("src"))


def block_details(block) -> dict:
    """Return a block's description and the site its image came from, empty when the block gives none."""
    provider = ((block.get("source") or {}).get("provider") or {}).get("name") or ""
    description = _clean(_text(block.get("description")), 1000)
    if description.lower().startswith("source pattern"):
        description = ""
    return {"description": description, "publisher": re.sub(r"^https?://", "", provider)[:200]}


def _block_fields(block) -> dict:
    """Return the size, block id, posted date, description and source site a feed item carries from its Are.na block."""
    image = block["image"]
    return {"width": int(image.get("width") or 0), "height": int(image.get("height") or 0),
            "source_ref": str(block.get("id") or ""), "posted_at": str(block.get("created_at") or "")[:10], "tags": [],
            **block_details(block)}


def owner_url(block, fallback="") -> str:
    """Return the Are.na profile link of whoever added a block, else the fallback owner slug's link, else ''."""
    slug = (block.get("user") or block.get("owner") or {}).get("slug") or fallback
    return f"https://www.are.na/{slug}" if slug and slug != "channel" else ""


def source_link(block) -> str:
    """Return the page a block's image was taken from, or '' when Are.na does not know it."""
    url = str((block.get("source") or {}).get("url") or "")
    return url[:500] if url.startswith(("http://", "https://")) else ""


def block_item(block, page_url, collection, owner="") -> dict:
    """Return one feed item for an image block, with the owner handle and source link that trail hops follow."""
    return {
        "source_id": "arena", "url": block["image"]["src"],
        "thumb": (block["image"].get("large") or {}).get("src") or block["image"]["src"],
        **_block_fields(block), "title": (block.get("title") or "")[:300], "creator": "",
        "page_url": page_url, "term": collection[:100], "collection": collection[:200],
        "creator_handle": owner_url(block, owner), "source_link": source_link(block),
    }


def channel_items(channel_url, fetcher, rng, newest=False) -> list:
    """Return feed items sampled from one channel, or its newest blocks when asked."""
    found = target(channel_url)
    if not found or found[0] != "channel":
        return []
    title, blocks = channel_blocks(found[1], fetcher, rng, newest)
    blocks = [block for block in blocks if _usable(block)]
    blocks = blocks[:PER_CHANNEL] if newest else rng.sample(blocks, min(PER_CHANNEL, len(blocks)))
    owner = [part for part in urlsplit(channel_url).path.split("/") if part][0]
    return [block_item(block, channel_url, title, owner) for block in blocks]


def user_items(user_url, fetcher, rng, newest=False) -> list:
    """Return feed items from a random page of the images a followed user has saved (the v3 API, which needs no login).

    With newest set, the newest blocks across the first and last pages are used instead.
    """
    found = target(user_url)
    if not found or found[0] != "user":
        return []
    url = f"{API_V3}/users/{found[1]}/contents?per={PAGE_SIZE}&page="
    first = _json(fetcher, url + "1")
    total = max(1, int((first.get("meta") or {}).get("total_pages") or 1))
    if newest:
        blocks = (first.get("data") or []) + ((_json(fetcher, url + str(total)).get("data") or []) if total > 1 else [])
        blocks = [block for block in newest_first(blocks) if (block.get("image") or {}).get("src")][:PER_CHANNEL]
    else:
        page = rng.randint(1, min(MAX_PAGES, total))
        data = first if page == 1 else _json(fetcher, url + str(page))
        blocks = [block for block in data.get("data") or [] if (block.get("image") or {}).get("src")]
        blocks = rng.sample(blocks, min(PER_CHANNEL, len(blocks)))
    return [block_item(block, f"https://www.are.na/block/{block.get('id')}", found[1], found[1]) for block in blocks]


_JUNK_TITLE = re.compile(r"^(original_)?[0-9a-f-]{12,}|^(img|dsc|image|untitled|screen[ _-]?shot|tumblr)\b", re.I)


def junk_title(title) -> bool:
    """Whether a title is a filename or camera-style label that says nothing about the image."""
    stem = re.sub(r"\.\w{2,4}$", "", (title or "").strip())
    digits = sum(char.isdigit() for char in stem)
    return not stem or bool(_JUNK_TITLE.search(stem)) or digits * 5 > len(stem) * 2


def _clean(text, limit) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^\W+", "", text or "")).strip()[:limit]


BLOCK_LIMIT = 50
CHANNEL_LIMIT = 5
BLOCK_STEP = "arena-block"
_ROW_COLUMNS = ("e.id, e.source_key, e.source_url, e.title, e.creator, e.description, e.publisher, e.source_ref,"
                " e.collection, e.domain, e.manual_fields")


def backfill_origins(conn, fetcher, rng, max_channels=2, block_limit=BLOCK_LIMIT) -> int:
    """Match saved Are.na images to their blocks, recording the block and channel words and filling empty fields.

    Reads up to block_limit blocks (feed-saved entries whose block is known, then entries saved from a block page) and up to
    max_channels channels (all of them when None). An image that cannot be matched waits longer after each failed try,
    and the pass stops as soon as Are.na pushes back.
    """
    now = datetime.now().isoformat(timespec="seconds")
    known = conn.execute(
        f"SELECT {_ROW_COLUMNS} FROM entries e WHERE e.source_service = 'arena' AND e.source_ref != ''"
        f" AND NOT EXISTS (SELECT 1 FROM entry_origins o WHERE o.entry_id = e.id) AND {checks.due('e')}"
        " ORDER BY e.id LIMIT ?", (BLOCK_STEP, now, int(block_limit))).fetchall()
    rows = conn.execute(
        f"SELECT {_ROW_COLUMNS} FROM entries e"
        " WHERE e.source_url LIKE '%are.na/%' AND e.source_key IS NOT NULL"
        f" AND e.source_ref = '' AND {checks.due('e')} ORDER BY e.id", (BLOCK_STEP, now)).fetchall()
    blocks = [(int(row["source_ref"]), row) for row in known]
    by_channel = {}
    for row in rows:
        block = _BLOCK_LINK.search(row["source_url"])
        if block:
            blocks.append((int(block.group(1)), row))
            continue
        slug = discover._arena_slug(row["source_url"])
        if slug:
            by_channel.setdefault(slug, []).append(row)
    done = 0
    for block_id, row in blocks[:max(0, int(block_limit))]:
        try:
            done += _match_block(conn, block_id, row, fetcher, now)
        except Exception as err:  # noqa: BLE001 - an unreadable block waits for a later run
            if checks.pushed_back(err):
                return done
            checks.failed(conn, row["id"], BLOCK_STEP, now)
    slugs = list(by_channel)
    rng.shuffle(slugs)
    for slug in slugs[:max_channels]:
        try:
            done += _match_channel(conn, slug, by_channel[slug], fetcher, now)
        except Exception as err:  # noqa: BLE001 - an unreadable channel waits for a later run
            if checks.pushed_back(err):
                return done
            for row in by_channel[slug]:
                checks.failed(conn, row["id"], BLOCK_STEP, now)
    return done


_BLOCK_LINK = re.compile(r"are\.na/block/(\d+)")


def _match_block(conn, block_id, row, fetcher, now) -> int:
    block = _json(fetcher, f"{API_V3}/blocks/{block_id}")
    conn.execute(
        "INSERT OR REPLACE INTO entry_origins (entry_id, block_id, channel_slug, channel_title, channel_text, checked_at)"
        " VALUES (?, ?, '', '', '', ?)", (row["id"], block.get("id") or block_id, now))
    _fill_entry(conn, row, block)
    return 1


def _image_path(url) -> str:
    """Host and path of an image URL without its query, so API versions that tack on different suffixes still match."""
    parts = urlsplit(url or "")
    return f"{parts.netloc}{parts.path}".lower()


def _match_channel(conn, slug, entries, fetcher, now) -> int:
    info = _json(fetcher, f"{API_V3}/channels/{slug}")
    pages = min(MAX_PAGES, max(1, -(-int((info.get("counts") or {}).get("contents") or 0) // PAGE_SIZE)))
    wanted = {_image_path(row["source_key"]): row for row in entries}
    found = {}

    def scan(contents):
        for block in contents:
            key = _image_path((block.get("image") or {}).get("src"))
            if key in wanted and key not in found:
                found[key] = block

    for page in range(1, pages + 1):
        if len(found) == len(wanted):
            break
        scan(_json(fetcher, _contents_url(slug, page)).get("data") or [])
    title = _clean(info.get("title"), 120)
    text = _clean(_text(info.get("description")), 400)
    for key, row in wanted.items():
        block = found.get(key)
        conn.execute(
            "INSERT OR REPLACE INTO entry_origins (entry_id, block_id, channel_slug, channel_title, channel_text, checked_at)"
            " VALUES (?, ?, ?, ?, ?, ?)", (row["id"], block.get("id") if block else None, slug, title, text, now))
        if block:
            _fill_entry(conn, row, block)
            conn.execute("UPDATE entries SET collection = ? WHERE id = ? AND collection = ''", (title, row["id"]))
        else:
            checks.failed(conn, row["id"], BLOCK_STEP, now)
    return len(wanted)


def _fill_entry(conn, row, block) -> None:
    """Fill a saved image's empty, filename-only or placeholder fields from its block, leaving hand-edited ones alone."""
    from bridge.ingest import enrich

    details = block_details(block)
    block_title = _clean(block.get("title"), 300)
    manual = enrich.manual_fields(row)
    updates = {}
    if not row["source_ref"] and block.get("id"):
        updates.update(source_service="arena", source_ref=str(block["id"]), posted_at=str(block.get("created_at") or "")[:10])
    if ("title" not in manual and block_title and not junk_title(block_title)
            and (junk_title(row["title"]) or enrich.placeholder_title(row))):
        updates["title"] = block_title
    for field in ("description", "publisher"):
        if field not in manual and not row[field] and details[field]:
            updates[field] = details[field]
    if updates:
        sets = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(f"UPDATE entries SET {sets} WHERE id = ?", (*updates.values(), row["id"]))
    conn.execute("UPDATE entries SET source_link = CASE WHEN source_link = '' THEN ? ELSE source_link END,"
                 " creator_handle = CASE WHEN creator_handle = '' THEN ? ELSE creator_handle END WHERE id = ?",
                 (source_link(block), owner_url(block), row["id"]))


SEARCH_CHANNELS = 20
SEARCH_WORDS = 2
_TITLE_WORD = re.compile(r"[a-z0-9]{3,}")


def search_channels(query, fetcher) -> list:
    """Return the links of public Are.na channels whose titles share words with a query, closest then biggest first.

    Uses the v2 search, which needs no login; a phrase that finds nothing is searched again word by word.
    """
    wanted = _TITLE_WORD.findall(query.lower())

    def overlap(item):
        return len(set(wanted) & set(_TITLE_WORD.findall(str(item.get("title") or "").lower())))

    def lookup(text):
        data = _json(fetcher, f"{API}/search/channels?" + urlencode({"q": text, "per": SEARCH_CHANNELS}))
        return [item for item in data.get("channels") or []
                if item.get("slug") and int(item.get("length") or 0) > 0 and item.get("status") != "private" and overlap(item)]

    found = lookup(query)
    if not found and len(wanted) > 1:
        seen = set()
        for word in sorted(set(wanted), key=len, reverse=True)[:SEARCH_WORDS]:
            for item in lookup(word):
                if item["slug"] not in seen:
                    seen.add(item["slug"])
                    found.append(item)
    found.sort(key=lambda item: (-overlap(item), -int(item.get("length") or 0)))
    owners = [((item.get("user") or {}).get("slug") or "channel") for item in found]
    return [f"https://www.are.na/{owner}/{item['slug']}" for owner, item in zip(owners, found)]


CONNECTIONS = 50


def block_channels(block_id, fetcher) -> list:
    """Return the public channels that hold one block, each as {slug, url, title, length} (the v3 API, which needs no login)."""
    data = _json(fetcher, f"{API_V3}/blocks/{int(block_id)}/connections?per={CONNECTIONS}")
    found = []
    for item in data.get("data") or []:
        visibility = str(item.get("visibility") or item.get("status") or "").lower()
        length = int((item.get("counts") or {}).get("contents") or item.get("length") or 0)
        if not item.get("slug") or visibility == "private" or length < 2:
            continue
        owner = (item.get("owner") or item.get("user") or {}).get("slug") or "channel"
        found.append({"slug": item["slug"], "url": f"https://www.are.na/{owner}/{item['slug']}",
                      "title": _clean(item.get("title"), 200), "length": length})
    return found


def pull(url, fetcher, rng, newest=False) -> list:
    """Return feed items for a followed or inferred Are.na link, whether it is a channel or a user."""
    found = target(url)
    if not found:
        return []
    reader = channel_items if found[0] == "channel" else user_items
    return reader(url, fetcher, rng, newest)


def list_followed(conn) -> list:
    """Return the Are.na channels and users followed from settings."""
    rows = conn.execute("SELECT id, kind, url, label FROM followed_sources ORDER BY id").fetchall()
    return [dict(row) for row in rows]


def follow(conn, url, fetcher) -> dict:
    """Follow an Are.na channel or user link after checking that Are.na knows it; raises ValueError otherwise."""
    found = target((url or "").strip())
    if not found:
        raise ValueError("Paste an Are.na channel or user link.")
    kind, slug = found
    segments = [part for part in urlsplit(url.strip()).path.split("/") if part]
    canonical = "https://www.are.na/" + "/".join(segments)
    try:
        if kind == "channel":
            label = _json(fetcher, f"{API_V3}/channels/{slug}").get("title") or slug
        else:
            data = _json(fetcher, f"{API}/users/{slug}")
            label = data.get("username") or data.get("full_name") or slug
    except Exception as err:  # noqa: BLE001 - any read failure means the link cannot be followed
        raise ValueError("Could not read that Are.na link.") from err
    conn.execute(
        "INSERT OR IGNORE INTO followed_sources (kind, url, label, created_at) VALUES (?, ?, ?, ?)",
        (kind, canonical, str(label)[:200], datetime.now().isoformat(timespec="seconds")))
    return dict(conn.execute("SELECT id, kind, url, label FROM followed_sources WHERE url = ?", (canonical,)).fetchone())


def unfollow(conn, source_id) -> bool:
    """Stop following a source; returns whether it existed."""
    return conn.execute("DELETE FROM followed_sources WHERE id = ?", (int(source_id),)).rowcount > 0
