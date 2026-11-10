"""Are.na sampling for the discovery feed: channels, followed channels and users, and channels related through shared blocks."""

import json
from datetime import datetime
from urllib.parse import urlsplit

import discover

API = "https://api.are.na/v2"
PAGE_SIZE = 100
MAX_PAGES = 20
PER_CHANNEL = 12
_RESERVED = {"explore", "search", "block", "blocks", "about", "pricing", "tools", "log-in", "sign-up", "feed", "notifications"}


def _json(fetcher, url) -> dict:
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


def _page_url(slug, page) -> str:
    return f"{API}/channels/{slug}?per={PAGE_SIZE}&page={page}"


def channel_blocks(slug, fetcher, rng):
    """Return (title, blocks) from a random page of a channel, so large channels are reached beyond their first page."""
    first = _json(fetcher, _page_url(slug, 1))
    length = int(first.get("length") or 0)
    pages = min(MAX_PAGES, max(1, -(-length // PAGE_SIZE)))
    page = rng.randint(1, pages)
    data = first if page == 1 else _json(fetcher, _page_url(slug, page))
    return first.get("title") or "", data.get("contents") or []


def _usable(block) -> bool:
    return bool(((block.get("image") or {}).get("original") or {}).get("url"))


def channel_items(channel_url, fetcher, rng) -> list:
    """Return feed items sampled from one channel."""
    found = target(channel_url)
    if not found or found[0] != "channel":
        return []
    title, blocks = channel_blocks(found[1], fetcher, rng)
    blocks = [block for block in blocks if _usable(block)]
    blocks = rng.sample(blocks, min(PER_CHANNEL, len(blocks)))
    return [{
        "source_id": "arena", "url": block["image"]["original"]["url"],
        "thumb": (block["image"].get("display") or {}).get("url") or block["image"]["original"]["url"],
        "width": 0, "height": 0, "title": (block.get("title") or "")[:300], "creator": "",
        "page_url": channel_url, "term": title[:100],
    } for block in blocks]


def _channel_link(channel) -> str:
    owner = (channel.get("user") or {}).get("slug") or ""
    return f"https://www.are.na/{owner}/{channel['slug']}" if owner and channel.get("slug") else ""


def user_items(user_url, fetcher, rng) -> list:
    """Return feed items from a random public channel of a followed user."""
    found = target(user_url)
    if not found or found[0] != "user":
        return []
    channels = _json(fetcher, f"{API}/users/{found[1]}/channels?per={PAGE_SIZE}").get("channels") or []
    links = [_channel_link(c) for c in channels if c.get("status") != "private" and int(c.get("length") or 0) > 0]
    links = [link for link in links if link]
    return channel_items(rng.choice(links), fetcher, rng) if links else []


def related_items(channel_url, fetcher, rng) -> list:
    """Return feed items from a channel that shares a block with the given one."""
    found = target(channel_url)
    if not found or found[0] != "channel":
        return []
    _, blocks = channel_blocks(found[1], fetcher, rng)
    ids = [block["id"] for block in blocks if block.get("id") and _usable(block)]
    if not ids:
        return []
    channels = _json(fetcher, f"{API}/blocks/{rng.choice(ids)}/channels?per=20").get("channels") or []
    links = [_channel_link(c) for c in channels
             if c.get("slug") != found[1] and c.get("status") != "private" and int(c.get("length") or 0) > 0]
    links = [link for link in links if link]
    return channel_items(rng.choice(links), fetcher, rng) if links else []


def pull(url, fetcher, rng) -> list:
    """Return feed items for a followed or inferred Are.na link, whether it is a channel or a user."""
    found = target(url)
    if not found:
        return []
    return channel_items(url, fetcher, rng) if found[0] == "channel" else user_items(url, fetcher, rng)


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
            label = _json(fetcher, f"{API}/channels/{slug}?per=1&page=1").get("title") or slug
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
