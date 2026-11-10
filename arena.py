"""Are.na sampling for the discovery feed: channels, followed channels and users, and channels related through shared blocks."""

import json
import re
from datetime import datetime
from urllib.parse import urlsplit

import capture
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


_JUNK_TITLE = re.compile(r"^(original_)?[0-9a-f-]{12,}|^(img|dsc|image|untitled|screen[ _-]?shot|tumblr)\b", re.I)


def junk_title(title) -> bool:
    """Whether a title is a filename or camera-style label that says nothing about the image."""
    stem = re.sub(r"\.\w{2,4}$", "", (title or "").strip())
    digits = sum(char.isdigit() for char in stem)
    return not stem or bool(_JUNK_TITLE.search(stem)) or digits * 5 > len(stem) * 2


def _clean(text, limit) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^\W+", "", text or "")).strip()[:limit]


def backfill_origins(conn, fetcher, rng, max_channels=2) -> int:
    """Match saved Are.na images to their blocks, recording the block and channel words and filling empty fields."""
    now = datetime.now().isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT e.id, e.source_key, e.source_url, e.title, e.creator, e.description, e.publisher FROM entries e"
        " WHERE e.source_url LIKE '%are.na/%' AND e.source_key IS NOT NULL"
        " AND NOT EXISTS (SELECT 1 FROM entry_origins o WHERE o.entry_id = e.id)").fetchall()
    by_channel = {}
    for row in rows:
        slug = discover._arena_slug(row["source_url"])
        if slug:
            by_channel.setdefault(slug, []).append(row)
    done = 0
    slugs = list(by_channel)
    rng.shuffle(slugs)
    for slug in slugs[:max_channels]:
        try:
            done += _match_channel(conn, slug, by_channel[slug], fetcher, now)
        except Exception:  # noqa: BLE001 - an unreadable channel is retried on a later refresh
            continue
    return done


def _match_channel(conn, slug, entries, fetcher, now) -> int:
    first = _json(fetcher, _page_url(slug, 1))
    pages = min(MAX_PAGES, max(1, -(-int(first.get("length") or 0) // PAGE_SIZE)))
    blocks = list(first.get("contents") or [])
    wanted = {row["source_key"]: row for row in entries}
    found = {}

    def scan(contents):
        for block in contents:
            url = ((block.get("image") or {}).get("original") or {}).get("url")
            try:
                key = capture.normalize_url(url) if url else None
            except ValueError:
                key = None
            if key in wanted and key not in found:
                found[key] = block

    scan(blocks)
    for page in range(2, pages + 1):
        if len(found) == len(wanted):
            break
        scan(_json(fetcher, _page_url(slug, page)).get("contents") or [])
    title = _clean(first.get("title"), 120)
    text = _clean((first.get("metadata") or {}).get("description"), 400)
    for key, row in wanted.items():
        block = found.get(key)
        conn.execute(
            "INSERT OR REPLACE INTO entry_origins (entry_id, block_id, channel_slug, channel_title, channel_text, checked_at)"
            " VALUES (?, ?, ?, ?, ?, ?)", (row["id"], block.get("id") if block else None, slug, title, text, now))
        if block:
            _fill_entry(conn, row, block)
    return len(wanted)


def _fill_entry(conn, row, block) -> None:
    """Fill a saved image's empty or filename-only fields from its block."""
    provider = ((block.get("source") or {}).get("provider") or {}).get("name") or ""
    block_title = _clean(block.get("title"), 300)
    description = _clean(block.get("description"), 1000)
    updates = {}
    if junk_title(row["title"]) and block_title and not junk_title(block_title):
        updates["title"] = block_title
    if not row["description"] and description and not description.lower().startswith("source pattern"):
        updates["description"] = description
    if not row["publisher"] and provider:
        updates["publisher"] = re.sub(r"^https?://", "", provider)[:200]
    if updates:
        sets = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(f"UPDATE entries SET {sets} WHERE id = ?", (*updates.values(), row["id"]))


def graph_items(conn, fetcher, rng, seeds=3) -> list:
    """Pull from channels that hold the same blocks as saved images, favoring channels that hold several of them."""
    block_ids = [row[0] for row in conn.execute("SELECT DISTINCT block_id FROM entry_origins WHERE block_id IS NOT NULL")]
    own = {row[0] for row in conn.execute("SELECT DISTINCT channel_slug FROM entry_origins")}
    scores = {}
    for block_id in rng.sample(block_ids, min(seeds, len(block_ids))):
        try:
            channels = _json(fetcher, f"{API}/blocks/{block_id}/channels?per=20").get("channels") or []
        except Exception:  # noqa: BLE001 - one unreadable block is skipped
            continue
        for item in channels:
            link = _channel_link(item)
            if link and item.get("slug") not in own and item.get("status") != "private" and int(item.get("length") or 0) > 0:
                scores[link] = scores.get(link, 0) + 1
    if not scores:
        return []
    pick = rng.choices(list(scores), weights=list(scores.values()))[0]
    return channel_items(pick, fetcher, rng)


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
