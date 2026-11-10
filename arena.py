"""Are.na sampling for the discovery feed: channels, followed channels and users, and channels related through shared blocks."""

import json
import re
import time
from datetime import datetime
from urllib.parse import urlsplit

import capture
import discover

API = "https://api.are.na/v2"
API_V3 = "https://api.are.na/v3"
PAGE_SIZE = 100
MAX_PAGES = 20
PER_CHANNEL = 12
RETRIES = 4
RETRY_WAIT = 5
_RESERVED = {"explore", "search", "block", "blocks", "about", "pricing", "tools", "log-in", "sign-up", "feed", "notifications"}


def _json(fetcher, url, retries=0) -> dict:
    """Read a JSON reply; with retries, wait and try again when Are.na answers that it is being asked too often."""
    for attempt in range(retries + 1):
        try:
            return json.loads(bytes(fetcher(url).body).decode("utf-8", "replace"))
        except Exception as err:  # noqa: BLE001 - only a rate limit is retried
            if "429" not in str(err) or attempt == retries:
                raise
            time.sleep(RETRY_WAIT * (attempt + 1))


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


def channel_blocks(slug, fetcher, rng):
    """Return (title, blocks) from a random page of a channel, so large channels are reached beyond their first page."""
    info = _json(fetcher, f"{API_V3}/channels/{slug}")
    length = int((info.get("counts") or {}).get("contents") or 0)
    pages = min(MAX_PAGES, max(1, -(-length // PAGE_SIZE)))
    data = _json(fetcher, _contents_url(slug, rng.randint(1, pages)))
    return info.get("title") or "", data.get("data") or []


def _usable(block) -> bool:
    return bool((block.get("image") or {}).get("src"))


def _block_fields(block) -> dict:
    """Return the size, block id and posted date a feed item carries from its Are.na block."""
    image = block["image"]
    return {"width": int(image.get("width") or 0), "height": int(image.get("height") or 0),
            "source_ref": str(block.get("id") or ""), "posted_at": str(block.get("created_at") or "")[:10], "tags": []}


def channel_items(channel_url, fetcher, rng) -> list:
    """Return feed items sampled from one channel."""
    found = target(channel_url)
    if not found or found[0] != "channel":
        return []
    title, blocks = channel_blocks(found[1], fetcher, rng)
    blocks = [block for block in blocks if _usable(block)]
    blocks = rng.sample(blocks, min(PER_CHANNEL, len(blocks)))
    return [{
        "source_id": "arena", "url": block["image"]["src"],
        "thumb": (block["image"].get("large") or {}).get("src") or block["image"]["src"],
        **_block_fields(block), "title": (block.get("title") or "")[:300], "creator": "",
        "page_url": channel_url, "term": title[:100], "collection": title[:200],
    } for block in blocks]


def user_items(user_url, fetcher, rng) -> list:
    """Return feed items from a random page of the images a followed user has saved (the v3 API, which needs no login)."""
    found = target(user_url)
    if not found or found[0] != "user":
        return []
    url = f"{API_V3}/users/{found[1]}/contents?per={PAGE_SIZE}&page="
    first = _json(fetcher, url + "1")
    pages = min(MAX_PAGES, max(1, int((first.get("meta") or {}).get("total_pages") or 1)))
    page = rng.randint(1, pages)
    data = first if page == 1 else _json(fetcher, url + str(page))
    blocks = [block for block in data.get("data") or [] if (block.get("image") or {}).get("src")]
    blocks = rng.sample(blocks, min(PER_CHANNEL, len(blocks)))
    return [{
        "source_id": "arena", "url": block["image"]["src"],
        "thumb": (block["image"].get("large") or {}).get("src") or block["image"]["src"],
        **_block_fields(block), "title": (block.get("title") or "")[:300], "creator": "",
        "page_url": f"https://www.are.na/block/{block.get('id')}", "term": found[1], "collection": found[1],
    } for block in blocks]


_JUNK_TITLE = re.compile(r"^(original_)?[0-9a-f-]{12,}|^(img|dsc|image|untitled|screen[ _-]?shot|tumblr)\b", re.I)


def junk_title(title) -> bool:
    """Whether a title is a filename or camera-style label that says nothing about the image."""
    stem = re.sub(r"\.\w{2,4}$", "", (title or "").strip())
    digits = sum(char.isdigit() for char in stem)
    return not stem or bool(_JUNK_TITLE.search(stem)) or digits * 5 > len(stem) * 2


def _clean(text, limit) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^\W+", "", text or "")).strip()[:limit]


def backfill_origins(conn, fetcher, rng, max_channels=2, retries=0) -> int:
    """Match saved Are.na images to their blocks, recording the block and channel words and filling empty fields.

    Handles up to max_channels channels per call (all of them when None), waiting out rate limits retries times; entries saved from a block page are read directly.
    """
    now = datetime.now().isoformat(timespec="seconds")
    rows = conn.execute(
        "SELECT e.id, e.source_key, e.source_url, e.title, e.creator, e.description, e.publisher, e.source_ref FROM entries e"
        " WHERE e.source_url LIKE '%are.na/%' AND e.source_key IS NOT NULL"
        " AND e.source_ref = ''").fetchall()
    by_channel, done = {}, 0
    for row in rows:
        block = _BLOCK_LINK.search(row["source_url"])
        if block:
            try:
                done += _match_block(conn, int(block.group(1)), row, fetcher, now, retries)
            except Exception:  # noqa: BLE001 - an unreadable block is retried on a later refresh
                pass
            continue
        slug = discover._arena_slug(row["source_url"])
        if slug:
            by_channel.setdefault(slug, []).append(row)
    slugs = list(by_channel)
    rng.shuffle(slugs)
    for slug in slugs[:max_channels]:
        try:
            done += _match_channel(conn, slug, by_channel[slug], fetcher, now, retries)
        except Exception:  # noqa: BLE001 - an unreadable channel is retried on a later refresh
            continue
    return done


_BLOCK_LINK = re.compile(r"are\.na/block/(\d+)")


def _match_block(conn, block_id, row, fetcher, now, retries=0) -> int:
    block = _json(fetcher, f"{API_V3}/blocks/{block_id}", retries)
    conn.execute(
        "INSERT OR REPLACE INTO entry_origins (entry_id, block_id, channel_slug, channel_title, channel_text, checked_at)"
        " VALUES (?, ?, '', '', '', ?)", (row["id"], block.get("id") or block_id, now))
    _fill_entry(conn, row, block)
    return 1


def _image_path(url) -> str:
    """Host and path of an image URL without its query, so API versions that tack on different suffixes still match."""
    parts = urlsplit(url or "")
    return f"{parts.netloc}{parts.path}".lower()


def _match_channel(conn, slug, entries, fetcher, now, retries=0) -> int:
    info = _json(fetcher, f"{API_V3}/channels/{slug}", retries)
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
        scan(_json(fetcher, _contents_url(slug, page), retries).get("data") or [])
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
    return len(wanted)


def _fill_entry(conn, row, block) -> None:
    """Fill a saved image's empty or filename-only fields from its block."""
    provider = ((block.get("source") or {}).get("provider") or {}).get("name") or ""
    block_title = _clean(block.get("title"), 300)
    description = _clean(_text(block.get("description")), 1000)
    updates = {}
    if not row["source_ref"] and block.get("id"):
        updates.update(source_service="arena", source_ref=str(block["id"]), posted_at=str(block.get("created_at") or "")[:10])
    if junk_title(row["title"]) and block_title and not junk_title(block_title):
        updates["title"] = block_title
    if not row["description"] and description and not description.lower().startswith("source pattern"):
        updates["description"] = description
    if not row["publisher"] and provider:
        updates["publisher"] = re.sub(r"^https?://", "", provider)[:200]
    if updates:
        sets = ", ".join(f"{column} = ?" for column in updates)
        conn.execute(f"UPDATE entries SET {sets} WHERE id = ?", (*updates.values(), row["id"]))


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
