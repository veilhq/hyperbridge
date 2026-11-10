"""Tumblr blogs such as searchsystem.co as a followed discovery source, read through the blog's public read API."""

import html
import json
import re
from datetime import datetime
from urllib.parse import urlsplit

PAGE = 50
PER_BLOG = 24
_IMG = re.compile(r"<img\b[^>]*>", re.I)
_ATTR = re.compile(r"""\b(src|srcset)\s*=\s*"([^"]*)\"""", re.I)
_TAG = re.compile(r"<[^>]+>")


def target(url):
    """Return the blog host for an http(s) link, or None."""
    parts = urlsplit((url or "").strip())
    if parts.scheme not in ("http", "https") or not parts.hostname or "." not in parts.hostname:
        return None
    return parts.hostname.lower()


def _read(fetcher, host, start, num) -> dict:
    body = bytes(fetcher(f"https://{host}/api/read/json?num={num}&start={start}").body).decode("utf-8", "replace")
    data = json.loads(body[body.index("{"):body.rindex("}") + 1])
    if "posts" not in data:
        raise ValueError("not a Tumblr blog")
    return data


def post_images(post) -> list:
    """Return (full size, preview) image URL pairs from a post: photo fields on older posts, srcset images in the body on newer ones."""
    found = []
    for photo in [post] + list(post.get("photos") or []):
        if photo.get("photo-url-1280"):
            found.append((photo["photo-url-1280"], photo.get("photo-url-500") or photo["photo-url-1280"]))
    if found:
        return found
    for tag in _IMG.findall(post.get("regular-body") or ""):
        attrs = {name.lower(): html.unescape(value) for name, value in _ATTR.findall(tag)}
        preview = attrs.get("src")
        sizes = []
        for entry in (attrs.get("srcset") or "").split(","):
            pieces = entry.split()
            if len(pieces) == 2 and pieces[1].endswith("w") and pieces[1][:-1].isdigit():
                sizes.append((int(pieces[1][:-1]), pieces[0]))
        full = max(sizes)[1] if sizes else preview
        if full and preview:
            found.append((full, preview))
    return found


def _title(post) -> str:
    text = post.get("regular-title") or ""
    if not text:
        match = re.search(r"<p>(.*?)</p>", post.get("regular-body") or post.get("photo-caption") or "", re.S)
        text = match.group(1) if match else ""
    return html.unescape(_TAG.sub("", text)).strip()[:300]


def items(blog_url, fetcher, rng) -> list:
    """Return feed items from a random stretch of a blog's posts, one per image."""
    host = target(blog_url)
    if not host:
        return []
    total = int(_read(fetcher, host, 0, 1).get("posts-total") or 0)
    data = _read(fetcher, host, rng.randint(0, max(0, total - PAGE)), PAGE)
    posts = [post for post in data["posts"] if post_images(post)]
    result = []
    for post in rng.sample(posts, min(PER_BLOG, len(posts))):
        tags = post.get("tags") or []
        for full, preview in post_images(post)[:4]:
            result.append({
                "source_id": "tumblr", "url": full, "thumb": preview, "width": 0, "height": 0,
                "title": _title(post), "creator": "", "page_url": post.get("url") or f"https://{host}/",
                "term": (tags[0] if tags else host)[:100],
            })
    return result


def follow(conn, url, fetcher) -> dict:
    """Follow a Tumblr blog after checking its read API answers; raises ValueError otherwise."""
    host = target(url)
    if not host:
        raise ValueError("Paste an Are.na link or a Tumblr blog link.")
    try:
        label = _read(fetcher, host, 0, 1).get("tumblelog", {}).get("title") or host
    except Exception as err:  # noqa: BLE001 - any read failure means the link cannot be followed
        raise ValueError("Could not read that blog. Paste an Are.na link or a Tumblr blog link.") from err
    canonical = f"https://{host}/"
    conn.execute(
        "INSERT OR IGNORE INTO followed_sources (kind, url, label, created_at) VALUES ('tumblr', ?, ?, ?)",
        (canonical, str(label)[:200], datetime.now().isoformat(timespec="seconds")))
    return dict(conn.execute("SELECT id, kind, url, label FROM followed_sources WHERE url = ?", (canonical,)).fetchone())
