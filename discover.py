"""Finds candidate images on a pasted page so they can be added to a set."""
import base64
import io
import json
import re
from concurrent.futures import ThreadPoolExecutor
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit

import capture
import sets

MAX_CANDIDATES = 60
MIN_EDGE = 150
THUMB_EDGE = 240
_IMAGE_LINK = re.compile(r"\.(?:png|jpe?g|gif|webp)(?:$|\?)", re.IGNORECASE)
_LAZY_ATTRS = ("data-src", "data-original", "data-lazy-src", "data-full-url")


class _ImageParser(HTMLParser):
    """Collects image URLs from img tags (including lazy-load and srcset forms) and links to image files."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): (value or "").strip() for key, value in attrs}
        if tag == "img":
            self.urls.append(_largest_source(attrs.get("srcset") or attrs.get("data-srcset", "")))
            self.urls.extend(attrs.get(name, "") for name in (*_LAZY_ATTRS, "src"))
        elif tag == "source":
            self.urls.append(_largest_source(attrs.get("srcset", "")))
        elif tag == "a" and _IMAGE_LINK.search(attrs.get("href", "")):
            self.urls.append(attrs["href"])


def _largest_source(srcset: str) -> str:
    """Return the widest URL in a srcset value, or an empty string."""
    best, best_width = "", -1
    for part in srcset.split(","):
        pieces = part.split()
        if not pieces:
            continue
        match = re.match(r"(\d+)[wx]$", pieces[1]) if len(pieces) > 1 else None
        width = int(match.group(1)) if match else 0
        if width > best_width:
            best, best_width = pieces[0], width
    return best


def page_images(html_bytes, base_url) -> list:
    """Return absolute http(s) image URLs found in a page, preview images first, without duplicates."""
    found = list(capture.extract_metadata(html_bytes, base_url)["image_urls"])
    parser = _ImageParser()
    try:
        parser.feed(capture._decode(bytes((html_bytes or b"")[: capture.MAX_HTML_BYTES])))
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup keeps whatever was parsed so far
        pass
    seen, urls = set(), []
    for raw in [*found, *parser.urls]:
        if not raw or raw.startswith("data:"):
            continue
        absolute = urljoin(base_url or "", raw)
        if urlsplit(absolute).scheme not in ("http", "https"):
            continue
        key = capture._image_key(absolute)
        if key in seen:
            continue
        seen.add(key)
        urls.append(absolute)
    return urls[: MAX_CANDIDATES * 2]


def _arena_slug(page_url):
    """Return the channel slug for an Are.na channel link, or None for any other page."""
    parts = urlsplit(page_url)
    segments = [part for part in parts.path.split("/") if part]
    host = (parts.hostname or "").lower()
    if host not in ("are.na", "www.are.na") or len(segments) != 2 or segments[0] in ("block", "explore", "search"):
        return None
    return segments[1]


def _arena_images(slug, fetcher):
    """Return (title, image URLs) for an Are.na channel through its public API."""
    urls, title, page = [], "", 1
    while len(urls) < MAX_CANDIDATES * 2:
        response = fetcher(f"https://api.are.na/v2/channels/{slug}?per=100&page={page}")
        data = json.loads(bytes(response.body).decode("utf-8", "replace"))
        title = data.get("title") or title
        blocks = data.get("contents") or []
        for block in blocks:
            image = (block.get("image") or {}).get("original") or {}
            if image.get("url"):
                urls.append(image["url"])
        if len(blocks) < 100:
            break
        page += 1
    return title, urls[: MAX_CANDIDATES * 2]


def _thumbnail(body: bytes) -> str:
    """Return a small JPEG data URI for an image."""
    from PIL import Image

    with Image.open(io.BytesIO(body)) as image:
        image = image.convert("RGB")
        image.thumbnail((THUMB_EDGE, THUMB_EDGE))
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", quality=80)
    return "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def _probe(url, fetcher):
    """Fetch one candidate; return its details, or None when it is not a usable, large-enough image."""
    try:
        response = fetcher(url)
        if not capture._is_image(response):
            return None
        _, width, height = capture._open_image(response.body)
        if min(width, height) < MIN_EDGE:
            return None
        return {"url": url, "thumb": _thumbnail(response.body), "width": width, "height": height}
    except Exception:  # noqa: BLE001 - a candidate that fails to load is simply left out
        return None


def discover(conn, url, fetcher=None) -> dict:
    """List the usable images on a page, marking those already in the library."""
    fetcher = fetcher or capture.default_fetcher()
    page_url = capture.normalize_url(url)
    response = fetcher(page_url)
    base = getattr(response, "final_url", "") or page_url
    slug = _arena_slug(base)
    if slug:
        title, urls = _arena_images(slug, fetcher)
    elif capture._is_image(response):
        urls, title = [base], ""
    else:
        urls = page_images(response.body, base)
        title = capture.extract_metadata(response.body, base)["title"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        probed = list(pool.map(lambda item: _probe(item, fetcher), urls))
    candidates = [item for item in probed if item][:MAX_CANDIDATES]
    for item in candidates:
        try:
            key = capture.normalize_url(item["url"])
        except ValueError:
            key = ""
        row = conn.execute("SELECT id FROM entries WHERE source_key = ?", (key,)).fetchone() if key else None
        item["known_entry_id"] = row["id"] if row else None
    return {"page_url": page_url, "title": title, "candidates": candidates}


def add_candidates(conn, urls, page_url, set_id) -> dict:
    """Queue the chosen image URLs for capture, credit the page as their source and place them in a set."""
    added = placed = 0
    for url in urls:
        result = capture.add_link(conn, url)
        if result["created"]:
            added += 1
            conn.execute("UPDATE entries SET source_url = ? WHERE id = ?", (page_url, result["entry_id"]))
        if set_id and sets.place(result["entry_id"], int(set_id)):
            placed += 1
    return {"added": added, "placed": placed}

