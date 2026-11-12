"""Link capture: normalize and queue URLs, extract page metadata, store images and thumbnails."""

import hashlib
import io
import json
import re
import sqlite3
import threading
from datetime import datetime
from html.parser import HTMLParser
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlsplit, urlunsplit

from bridge.core import db
from bridge.core import storage
from bridge.library import swatches

THUMB_EDGE = 480
MAX_PIXELS = 50_000_000
MAX_HTML_BYTES = 2_000_000
MAX_IMAGES = 20
MAX_TITLE = 100
_TRACKING_PARAMS = {"fbclid", "gclid", "ref"}
_DEFAULT_PORTS = {"http": 80, "https": 443}
_FORMAT_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "GIF": "image/gif", "WEBP": "image/webp"}
_FORMAT_SUFFIX = {"PNG": "png", "JPEG": "jpg", "GIF": "gif", "WEBP": "webp"}
_FIELDS = ("title", "description", "creator", "publisher", "type", "year")


class CaptureError(Exception):
    """Raised when a capture cannot complete (bad image, unsupported content)."""


def _timestamp(now=None) -> str:
    """Return an ISO timestamp, using the given datetime or string when provided."""
    if isinstance(now, str):
        return now
    return (now or datetime.now()).isoformat(timespec="seconds")


def normalize_url(url) -> str:
    """Return a canonical form of an http(s) URL used as the dedupe key."""
    parts = urlsplit(str(url).strip())
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not parts.hostname:
        raise ValueError(f"Only http and https URLs can be captured: {url!r}")
    host = parts.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    try:
        port = parts.port
    except ValueError as error:
        raise ValueError(f"Invalid port in URL: {url!r}") from error
    netloc = host if port in (None, _DEFAULT_PORTS[scheme]) else f"{host}:{port}"
    if parts.username:
        userinfo = quote(unquote(parts.username), safe="")
        if parts.password:
            userinfo += ":" + quote(unquote(parts.password), safe="")
        netloc = f"{userinfo}@{netloc}"
    path = parts.path
    if len(path) > 1:
        path = path.rstrip("/") or "/"
    pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in _TRACKING_PARAMS
    ]
    query = urlencode(sorted(pairs))
    return urlunsplit((scheme, netloc, path or "/", query, ""))


def source_domain(url) -> str:
    """Return the site name shown under an entry: the URL's host without a leading www."""
    host = (urlsplit(str(url or "")).hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def add_link(conn, url, now=None) -> dict:
    """Queue a URL for capture; an already-known URL returns its existing entry."""
    key = normalize_url(url)
    domain = source_domain(key)
    stamp = _timestamp(now)
    existing = conn.execute("SELECT id FROM entries WHERE source_key = ?", (key,)).fetchone()
    if existing:
        return {"entry_id": existing["id"], "created": False, "already_captured": True}
    conn.execute("BEGIN IMMEDIATE")
    try:
        existing = conn.execute("SELECT id FROM entries WHERE source_key = ?", (key,)).fetchone()
        if existing:
            conn.execute("COMMIT")
            return {"entry_id": existing["id"], "created": False, "already_captured": True}
        cursor = conn.execute(
            "INSERT INTO entries (uid, source_url, source_key, domain, state, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, 'pending', ?, ?)",
            (storage.new_uid(), str(url).strip(), key, domain, stamp, stamp),
        )
        entry_id = cursor.lastrowid
        conn.execute(
            "INSERT INTO jobs (kind, entry_id, payload, state, created_at, updated_at)"
            " VALUES ('capture', ?, ?, 'queued', ?, ?)",
            (entry_id, json.dumps({"url": key}), stamp, stamp),
        )
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise
    return {"entry_id": entry_id, "created": True, "already_captured": False}


_IMAGE_META = (
    "og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src",
    "twitter:image0", "twitter:image1", "twitter:image2", "twitter:image3",
)


class _MetaParser(HTMLParser):
    """Collects meta tags, the title text and JSON-LD blocks from a page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta = {}
        self.images = []
        self.title = ""
        self.jsonld = []
        self._in_title = False
        self._in_jsonld = False
        self._buffer = []

    def handle_starttag(self, tag, attrs):
        attrs = {key.lower(): (value or "") for key, value in attrs}
        if tag == "meta":
            name = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
            content = attrs.get("content", "").strip()
            if name and content:
                self.meta.setdefault(name, content)
                if name in _IMAGE_META:
                    self.images.append(content)
        elif tag == "title" and not self.title:
            self._in_title = True
            self._buffer = []
        elif tag == "script" and "ld+json" in attrs.get("type", "").lower():
            self._in_jsonld = True
            self._buffer = []
        elif tag == "link" and "image_src" in attrs.get("rel", "").lower() and attrs.get("href"):
            self.meta.setdefault("link:image_src", attrs["href"].strip())

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self._in_title = False
            self.title = " ".join("".join(self._buffer).split())
        elif tag == "script" and self._in_jsonld:
            self._in_jsonld = False
            self.jsonld.append("".join(self._buffer))

    def handle_data(self, data):
        if self._in_title or self._in_jsonld:
            self._buffer.append(data)


def _decode(html_bytes: bytes) -> str:
    """Decode page bytes using a declared charset when valid, else utf-8 with replacement."""
    head = html_bytes[:4096].decode("ascii", errors="ignore")
    match = re.search(r"charset\s*=\s*[\"']?([A-Za-z0-9_\-]+)", head)
    for encoding in ([match.group(1)] if match else []) + ["utf-8"]:
        try:
            return html_bytes.decode(encoding, errors="replace")
        except LookupError:
            continue
    return html_bytes.decode("utf-8", errors="replace")


def _jsonld_nodes(blocks):
    """Yield every dict found in the JSON-LD blocks, flattening lists and @graph."""
    stack = []
    for block in blocks:
        try:
            stack.append(json.loads(block))
        except ValueError:
            continue
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            stack.extend(item)
        elif isinstance(item, dict):
            yield item
            if isinstance(item.get("@graph"), list):
                stack.extend(item["@graph"])


def _name_of(value) -> str:
    """Return a display name from a JSON-LD value (string, object or list of either)."""
    if isinstance(value, list):
        names = [_name_of(item) for item in value]
        return ", ".join(name for name in names if name)
    if isinstance(value, dict):
        return _name_of(value.get("name", ""))
    return value.strip() if isinstance(value, str) else ""


def _image_of(value) -> str:
    """Return an image URL from a JSON-LD image value."""
    if isinstance(value, list):
        return next((found for found in map(_image_of, value) if found), "")
    if isinstance(value, dict):
        return _image_of(value.get("url", ""))
    return value.strip() if isinstance(value, str) else ""


def _images_of(value) -> list:
    """Return every image URL found in a JSON-LD image value."""
    if isinstance(value, list):
        return [url for item in value for url in _images_of(item)]
    if isinstance(value, dict):
        return _images_of(value.get("url", ""))
    return [value.strip()] if isinstance(value, str) and value.strip() else []


_TWIMG_MEDIA = re.compile(r"media_url_https[^h]{1,8}https://pbs\.twimg\.com/media/([A-Za-z0-9_-]+)")
_TWIMG_GAP = 1500


def _post_media(text, lead_url) -> list:
    """Return the pbs.twimg.com images embedded in the same post as lead_url, in page order."""
    lead = re.search(r"pbs\.twimg\.com/media/([A-Za-z0-9_-]+)", lead_url or "")
    if not lead:
        return []
    groups, last_end = [], None
    for match in _TWIMG_MEDIA.finditer(text):
        if last_end is None or match.start() - last_end > _TWIMG_GAP:
            groups.append([])
        groups[-1].append(match.group(1))
        last_end = match.end()
    for group in groups:
        if lead.group(1) in group:
            ids = list(dict.fromkeys(group))
            return ["https://pbs.twimg.com/media/%s?format=webp&name=large" % item for item in ids]
    return []


_INSTAGRAM_POST = re.compile(r"^/(?:[^/]+/)?((?:p|reel|tv)/[A-Za-z0-9_-]+)")


def instagram_embed_url(url) -> str:
    """Return the embed page URL for an Instagram post URL, or "" for anything else."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if host != "instagram.com" and not host.endswith(".instagram.com"):
        return ""
    match = _INSTAGRAM_POST.match(parts.path)
    return "https://www.instagram.com/%s/embed/" % match.group(1) if match else ""


def instagram_media(embed_bytes) -> list:
    """Return the full-size image URLs of an Instagram post from its embed page, in carousel order (videos give their poster frame)."""
    text = _decode(bytes(embed_bytes[:MAX_HTML_BYTES]))
    marker = '"contextJSON":'
    start = text.find(marker)
    if start < 0:
        return []
    try:
        literal, _ = json.JSONDecoder().raw_decode(text[start + len(marker):])
        media = json.loads(literal)["gql_data"]["shortcode_media"]
    except (ValueError, KeyError, TypeError):
        return []
    edges = (media.get("edge_sidecar_to_children") or {}).get("edges") or []
    nodes = [edge.get("node") or {} for edge in edges] or [media]
    urls = [node.get("display_url") for node in nodes]
    return list(dict.fromkeys(url for url in urls if isinstance(url, str) and url.startswith("http")))


def _image_key(url: str) -> str:
    """Return a key that is the same for size variants of one image (Pinterest serves each at several widths)."""
    parts = urlsplit(url)
    if (parts.hostname or "").endswith("pinimg.com"):
        return "pinimg:" + parts.path.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    return url


def shorten_title(title: str) -> str:
    """Cut a long page title to MAX_TITLE characters at a word boundary, ending in an ellipsis."""
    if len(title) <= MAX_TITLE:
        return title
    cut = title[: MAX_TITLE - 3]
    if " " in cut[MAX_TITLE // 2:]:
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" -|,:;") + "..."


_GENERIC_WORDS = {"original", "orig", "image", "img", "full", "large", "medium", "small",
                  "download", "file", "default", "untitled", "thumb", "thumbnail"}


def readable_name(filename: str) -> str:
    """Turn an image file name into a short title, dropping generic words and random-looking tokens; empty when nothing is left."""
    stem = unquote(str(filename or "")).rsplit(".", 1)[0] if "." in str(filename or "") else unquote(str(filename or ""))
    words = []
    for token in re.split(r"[\s_.+-]+", stem):
        if not token or token.lower() in _GENERIC_WORDS:
            continue
        mixed = bool(re.search(r"\d", token)) and bool(re.search(r"[A-Za-z]", token))
        if (mixed and len(token) >= 6) or len(token) >= 16 or (token.isdigit() and len(token) >= 4):
            continue
        words.append(token)
    return shorten_title(" ".join(words))


def extract_metadata(html_bytes, base_url) -> dict:
    """Return title, description, creator, publisher, type, year and image_url from page HTML."""
    result = {key: "" for key in _FIELDS}
    result["image_url"] = ""
    result["image_urls"] = []
    if not html_bytes:
        return result
    parser = _MetaParser()
    try:
        parser.feed(_decode(bytes(html_bytes[:MAX_HTML_BYTES])))
        parser.close()
    except Exception:  # noqa: BLE001 - malformed markup keeps whatever was parsed so far
        pass
    meta = parser.meta
    ld = {key: "" for key in (*_FIELDS, "image_url", "date")}
    ld_images = []
    for node in _jsonld_nodes(parser.jsonld):
        kind = node.get("@type", "")
        kind = kind[0] if isinstance(kind, list) and kind else kind
        ld["title"] = ld["title"] or _name_of(node.get("headline") or node.get("name"))
        ld["description"] = ld["description"] or _name_of(node.get("description"))
        ld["creator"] = ld["creator"] or _name_of(node.get("author") or node.get("creator"))
        ld["publisher"] = ld["publisher"] or _name_of(node.get("publisher"))
        ld["type"] = ld["type"] or (kind if isinstance(kind, str) else "")
        ld["image_url"] = ld["image_url"] or _image_of(node.get("image"))
        ld_images.extend(_images_of(node.get("image")))
        ld["date"] = ld["date"] or _name_of(node.get("datePublished") or node.get("dateCreated"))

    def first(*values):
        return next((value for value in values if value), "")

    author = meta.get("article:author", "")
    result["title"] = first(
        meta.get("og:title"), meta.get("twitter:title"), ld["title"], parser.title
    )
    result["title"] = shorten_title(result["title"])
    result["description"] = first(
        meta.get("og:description"), meta.get("twitter:description"), ld["description"],
        meta.get("description"),
    )
    result["creator"] = first(
        meta.get("author"), "" if author.lower().startswith("http") else author,
        meta.get("twitter:creator"), ld["creator"],
    )
    result["publisher"] = first(meta.get("og:site_name"), ld["publisher"], meta.get("publisher"))
    result["type"] = first(meta.get("og:type"), ld["type"])
    date = first(
        meta.get("article:published_time"), meta.get("datepublished"), ld["date"],
        meta.get("date"),
    )
    year = re.search(r"(?<!\d)(1[5-9]\d\d|2\d\d\d)(?!\d)", date)
    result["year"] = year.group(1) if year else ""
    image = first(
        meta.get("og:image"), meta.get("og:image:url"), meta.get("twitter:image"),
        meta.get("twitter:image:src"), ld["image_url"], meta.get("link:image_src"),
    )
    embedded = _post_media(_decode(bytes(html_bytes[:MAX_HTML_BYTES])), image)
    candidates = [image, *embedded, *parser.images, *ld_images, meta.get("link:image_src", "")]
    seen = set()
    for candidate in candidates:
        if not candidate:
            continue
        absolute = urljoin(base_url or "", candidate)
        if urlsplit(absolute).scheme not in ("http", "https"):
            continue
        key = _image_key(absolute)
        if key not in seen:
            seen.add(key)
            result["image_urls"].append(absolute)
        elif "/originals/" in absolute:
            # A Pinterest size variant already listed is upgraded to its full-size original.
            for index, listed in enumerate(result["image_urls"]):
                if _image_key(listed) == key:
                    result["image_urls"][index] = absolute
    result["image_urls"] = result["image_urls"][:MAX_IMAGES]
    result["image_url"] = result["image_urls"][0] if result["image_urls"] else ""
    return result


def default_fetcher():
    """Return the guarded fetcher from fetchguard, imported on first use."""
    from bridge.core.fetchguard import safe_fetch

    return safe_fetch


def _open_image(body: bytes):
    """Verify bytes are a supported image under the pixel cap; return (format, width, height)."""
    from PIL import Image

    try:
        with Image.open(io.BytesIO(body)) as image:
            width, height = image.size
            if width < 1 or height < 1 or width * height > MAX_PIXELS:
                raise CaptureError(f"Image dimensions {width}x{height} exceed the pixel limit")
            image_format = image.format
            image.verify()
    except CaptureError:
        raise
    except Exception as error:  # noqa: BLE001 - Pillow raises many types for bad data
        raise CaptureError(f"Response is not a usable image: {error}") from error
    if image_format not in _FORMAT_SUFFIX:
        raise CaptureError(f"Unsupported image format: {image_format}")
    return image_format, width, height


def _write_thumbnail(body: bytes, target_dir_uid: str):
    """Write a thumbnail (webp, else jpeg) and return (path, width, height)."""
    from PIL import Image

    with Image.open(io.BytesIO(body)) as image:
        if getattr(image, "is_animated", False):
            animated = _write_animated_thumbnail(image, target_dir_uid)
            if animated:
                return animated
            image.seek(0)
        image.load()
        transparent = "A" in image.getbands() or "transparency" in image.info
        image = image.convert("RGBA" if transparent else "RGB")
        image.thumbnail((THUMB_EDGE, THUMB_EDGE))
        path = storage.asset_path(target_dir_uid, "thumbnail", 0, "webp")
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            image.save(path, "WEBP", quality=82)
        except (OSError, KeyError, ValueError):
            path.unlink(missing_ok=True)
            path = storage.asset_path(target_dir_uid, "thumbnail", 0, "jpg")
            image.convert("RGB").save(path, "JPEG", quality=85)
        return path, image.width, image.height


ANIM_FRAME_BUDGET = 128 * 1024 * 1024  # bytes of decoded frames held while building an animated thumbnail


def _write_animated_thumbnail(image, target_dir_uid: str):
    """Write an animated webp thumbnail for a multi-frame image; return (path, width, height) or None."""
    from PIL import ImageSequence

    scale = min(1.0, THUMB_EDGE / max(image.width, image.height))
    width, height = max(1, round(image.width * scale)), max(1, round(image.height * scale))
    if width * height * 4 * getattr(image, "n_frames", 1) > ANIM_FRAME_BUDGET:
        return None
    frames, durations = [], []
    try:
        for frame in ImageSequence.Iterator(image):
            durations.append(max(20, int(frame.info.get("duration", 100) or 100)))
            frames.append(frame.convert("RGBA").resize((width, height)))
        path = storage.asset_path(target_dir_uid, "thumbnail", 0, "webp")
        path.parent.mkdir(parents=True, exist_ok=True)
        frames[0].save(path, "WEBP", save_all=True, append_images=frames[1:], duration=durations,
                       loop=0, quality=75, method=4)
    except (OSError, KeyError, ValueError, MemoryError):
        return None
    return path, width, height


def _has_animation(path) -> bool:
    """Return True when a webp file carries an ANIM chunk (an animated webp)."""
    try:
        with open(path, "rb") as handle:
            return b"ANIM" in handle.read(64)
    except OSError:
        return False


def refresh_animated_thumbnails(conn) -> int:
    """Rebuild static grid thumbnails of animated originals as animated webp; return how many changed."""
    from PIL import Image

    rows = conn.execute(
        "SELECT e.id, e.uid, o.path AS original, t.path AS thumb FROM entries e"
        " JOIN assets o ON o.entry_id = e.id AND o.kind = 'original' AND o.position = 0"
        " JOIN assets t ON t.entry_id = e.id AND t.kind = 'thumbnail' AND t.position = 0"
        " WHERE o.path LIKE '%.gif' OR o.path LIKE '%.webp' OR o.path LIKE '%.png'"
    ).fetchall()
    changed = 0
    for row in rows:
        thumb = db.data_dir() / row["thumb"]
        if thumb.suffix == ".webp" and _has_animation(thumb):
            continue
        try:
            with Image.open(db.data_dir() / row["original"]) as image:
                if not getattr(image, "is_animated", False):
                    continue
                made = _write_animated_thumbnail(image, row["uid"])
        except (OSError, ValueError):
            continue
        if not made:
            continue
        path, width, height = made
        conn.execute(
            "UPDATE assets SET path = ?, width = ?, height = ?, bytes = ?"
            " WHERE entry_id = ? AND kind = 'thumbnail' AND position = 0",
            (storage.relative_path(path), width, height, path.stat().st_size, row["id"]),
        )
        changed += 1
    conn.commit()
    return changed


def _store_image(conn, entry, body: bytes, position: int = 0) -> None:
    """Validate an image and store it at a position; position 0 also gets the grid thumbnail."""
    image_format, width, height = _open_image(body)
    uid = entry["uid"]
    conn.execute(
        "DELETE FROM assets WHERE entry_id = ? AND position = ? AND kind IN ('original', 'thumbnail')",
        (entry["id"], position),
    )
    folder = storage.entry_dir(uid)
    folder.mkdir(parents=True, exist_ok=True)
    for kind in ("original", "thumbnail"):
        for stale in folder.glob(f"{kind}-{position}.*"):
            stale.unlink(missing_ok=True)
    original = storage.asset_path(uid, "original", position, _FORMAT_SUFFIX[image_format])
    original.write_bytes(body)
    rows = [("original", original, width, height, len(body))]
    if position == 0:
        thumb, thumb_width, thumb_height = _write_thumbnail(body, uid)
        swatches.store(conn, entry["id"], body)
        rows.append(("thumbnail", thumb, thumb_width, thumb_height, thumb.stat().st_size))
    for kind, path, row_width, row_height, size in rows:
        conn.execute(
            "INSERT INTO assets (entry_id, position, kind, path, width, height, bytes)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (entry["id"], position, kind, storage.relative_path(path), row_width, row_height, size),
        )


def _is_image(response) -> bool:
    """Return True when a fetch response declares an image content type."""
    return str(getattr(response, "content_type", "") or "").lower().startswith("image/")


def _apply_metadata(conn, entry, values: dict, stamp: str) -> None:
    """Write non-empty extracted fields to the entry, skipping any listed in manual_fields."""
    try:
        manual = set(json.loads(entry["manual_fields"] or "[]"))
    except ValueError:
        manual = set()
    changes = {
        key: values[key] for key in _FIELDS if values.get(key) and key not in manual
    }
    if not changes:
        return
    assignments = ", ".join(f"{key} = ?" for key in changes)
    conn.execute(
        f"UPDATE entries SET {assignments}, updated_at = ? WHERE id = ?",
        (*changes.values(), stamp, entry["id"]),
    )


def _capture_entry(conn, entry, fetcher, screenshotter=None) -> None:
    """Fetch the entry's page (or image), store assets and update its fields; screenshot when no image."""
    url = entry["source_key"] or entry["source_url"]
    response = fetcher(url)
    if _is_image(response):
        name = unquote(urlsplit(response.final_url or url).path.rsplit("/", 1)[-1])
        _apply_metadata(conn, entry, {"title": readable_name(name)}, _timestamp())
        _store_image(conn, entry, response.body)
        return
    base = getattr(response, "final_url", "") or url
    values = extract_metadata(response.body, base)
    embed_url = instagram_embed_url(base)
    if embed_url:
        try:
            posted = instagram_media(fetcher(embed_url).body)
        except Exception:  # noqa: BLE001 - the page's own preview image still applies
            posted = []
        if posted:
            values["image_urls"] = posted[:MAX_IMAGES]
            values["image_url"] = posted[0]
    _apply_metadata(conn, entry, values, _timestamp())
    stored = 0
    fetched = set()
    for image_url in values["image_urls"]:
        try:
            image = fetcher(image_url)
            if not _is_image(image):
                raise CaptureError("Preview image URL did not return an image")
            digest = hashlib.sha256(image.body).hexdigest()
            if digest in fetched:
                continue
            fetched.add(digest)
            _store_image(conn, entry, image.body, stored)
            stored += 1
        except Exception:  # noqa: BLE001 - one bad image does not fail the entry
            continue
    if not stored and screenshotter is not None:
        try:
            _store_image(conn, entry, screenshotter(base), 0)
            stored = 1
        except Exception:  # noqa: BLE001 - a missing screenshot leaves the entry without an image
            pass
    if values["image_urls"] and not stored:
        raise CaptureError("No preview image could be fetched")


_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_FILE_BYTES = 50_000_000


def _text(value) -> str:
    """Return a metadata value as clean text, decoding bytes and dropping control characters."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "ignore")
    return re.sub(r"[\x00-\x1f]+", " ", str(value or "")).strip()[:500]


def image_info(body: bytes) -> dict:
    """Read creator, publisher, year, title and description from EXIF and PNG text chunks."""
    from PIL import Image

    info = {}
    try:
        with Image.open(io.BytesIO(body)) as image:
            exif = image.getexif()
            tags = dict(exif)
            try:
                tags.update(exif.get_ifd(0x8769))
            except Exception:  # noqa: BLE001 - a broken EXIF block only loses the dates
                pass
            text = {str(key).lower(): value for key, value in (image.info or {}).items()}
    except Exception:  # noqa: BLE001 - metadata is optional
        return info
    info["creator"] = _text(tags.get(0x013B) or text.get("author") or text.get("artist"))
    info["publisher"] = _text(tags.get(0x8298) or text.get("copyright") or text.get("source"))
    info["title"] = _text(text.get("title"))
    info["description"] = _text(tags.get(0x010E) or text.get("description") or text.get("comment"))
    when = _text(tags.get(0x9003) or tags.get(0x0132) or text.get("creation time"))
    match = re.search(r"\b(19|20)\d\d\b", when)
    info["year"] = match.group(0) if match else ""
    return {key: value for key, value in info.items() if value}


def add_image(conn, body: bytes, name: str = "", now=None) -> dict:
    """Create a captured entry from image bytes (a paste or a dropped file); raises CaptureError."""
    image_format = _open_image(body)[0]
    stamp = _timestamp(now)
    found = image_info(body)
    title = found.get("title") or (
        readable_name(name) if name else ""
    )
    cursor = conn.execute(
        "INSERT INTO entries (uid, title, description, creator, publisher, type, year, state, created_at, updated_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, 'captured', ?, ?)",
        (
            storage.new_uid(), shorten_title(title), found.get("description", ""), found.get("creator", ""),
            found.get("publisher", ""), _FORMAT_MIME[image_format], found.get("year", ""), stamp, stamp,
        ),
    )
    entry = conn.execute("SELECT * FROM entries WHERE id = ?", (cursor.lastrowid,)).fetchone()
    try:
        _store_image(conn, entry, body, 0)
    except Exception:
        conn.execute("DELETE FROM entries WHERE id = ?", (entry["id"],))
        raise
    return {"entry_id": entry["id"]}


def add_image_file(conn, path, now=None) -> dict:
    """Create an entry from an image file on disk, rejecting other types and oversized files."""
    from pathlib import Path

    source = Path(path)
    if source.suffix.lower() not in _IMAGE_SUFFIXES or not source.is_file():
        raise CaptureError(f"Not an image file: {source.name}")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise CaptureError(f"Image is too large: {source.name}")
    return add_image(conn, source.read_bytes(), source.name, now)


def fix_image_types(conn) -> None:
    """Rewrite the earlier img/ type prefix on pasted and dropped entries to the MIME prefix."""
    conn.execute(
        "UPDATE entries SET type = 'image/' || substr(type, 5) WHERE source_key IS NULL AND type LIKE 'img/%'"
    )


def fix_file_name_titles(conn) -> None:
    """Clean titles that are raw image file names (one token with an extension or underscores) unless the title was edited by hand."""
    rows = conn.execute("SELECT id, title, manual_fields FROM entries WHERE title != '' AND title NOT LIKE '% %'").fetchall()
    for row in rows:
        title = row["title"]
        if not (re.search(r"\.(png|jpe?g|gif|webp)$", title, re.I) or "_" in title):
            continue
        try:
            if "title" in json.loads(row["manual_fields"] or "[]"):
                continue
        except ValueError:
            pass
        cleaned = readable_name(title)
        if cleaned != title:
            conn.execute("UPDATE entries SET title = ? WHERE id = ?", (cleaned, row["id"]))


def fix_domains(conn) -> None:
    """Point each entry's shown domain at its source page rather than the image host it was saved from."""
    rows = conn.execute("SELECT id, source_url, domain FROM entries WHERE source_url IS NOT NULL AND source_url != ''").fetchall()
    for row in rows:
        domain = source_domain(row["source_url"])
        if domain and domain != row["domain"]:
            conn.execute("UPDATE entries SET domain = ? WHERE id = ?", (domain, row["id"]))


def run_capture(conn, job_id, fetcher=None, screenshotter=None) -> None:
    """Run one capture job: fetch, extract, store assets, then mark entry and job."""
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        raise ValueError(f"No job with id {job_id}")
    if job["state"] != "running":
        conn.execute(
            "UPDATE jobs SET state = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?",
            (_timestamp(), job_id),
        )
    error = ""
    try:
        entry = conn.execute("SELECT * FROM entries WHERE id = ?", (job["entry_id"],)).fetchone()
        if entry is None:
            raise CaptureError("Entry no longer exists")
        _capture_entry(conn, entry, fetcher or default_fetcher(), screenshotter)
    except Exception as exc:  # noqa: BLE001 - any failure is recorded on the job
        error = f"{type(exc).__name__}: {exc}"[:500]
    stamp = _timestamp()
    entry_state, job_state = ("failed", "failed") if error else ("captured", "done")
    if not error and job["entry_id"] is not None:
        from bridge.ingest import enrich
        enrich.enrich_entry(conn, conn.execute("SELECT * FROM entries WHERE id = ?", (job["entry_id"],)).fetchone())
    if job["entry_id"] is not None:
        conn.execute(
            "UPDATE entries SET state = ?, updated_at = ? WHERE id = ?",
            (entry_state, stamp, job["entry_id"]),
        )
    conn.execute(
        "UPDATE jobs SET state = ?, error = ?, updated_at = ? WHERE id = ?",
        (job_state, error, stamp, job_id),
    )


def claim_next_job(conn):
    """Atomically move the oldest queued job to running and return it, or None."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT id FROM jobs WHERE state = 'queued' ORDER BY created_at, id LIMIT 1"
        ).fetchone()
        if row is None:
            conn.execute("COMMIT")
            return None
        conn.execute(
            "UPDATE jobs SET state = 'running', attempts = attempts + 1, updated_at = ? WHERE id = ?",
            (_timestamp(), row["id"]),
        )
        claimed = conn.execute("SELECT * FROM jobs WHERE id = ?", (row["id"],)).fetchone()
        conn.execute("COMMIT")
        return claimed
    except Exception:
        conn.execute("ROLLBACK")
        raise


class Worker(threading.Thread):
    """Background thread that claims queued capture jobs and runs them on its own connection."""

    def __init__(self, fetcher=None, on_change=None, poll_interval=0.5, screenshotter=None):
        super().__init__(name="hyperbridge-capture", daemon=True)
        self._fetcher = fetcher
        self._screenshotter = screenshotter
        self._on_change = on_change
        self._poll_interval = poll_interval
        self._halt = threading.Event()

    def stop(self) -> None:
        """Ask the loop to finish its current job and exit."""
        self._halt.set()

    def run(self) -> None:
        """Reset interrupted jobs, then process the queue until stopped."""
        conn = db.connect()
        try:
            conn.execute(
                "UPDATE jobs SET state = 'queued', updated_at = ? WHERE state = 'running'",
                (_timestamp(),),
            )
            while not self._halt.is_set():
                try:
                    job = claim_next_job(conn)
                except sqlite3.Error:
                    self._halt.wait(self._poll_interval)
                    continue
                if job is None:
                    self._halt.wait(self._poll_interval)
                    continue
                self._process(conn, job)
        finally:
            conn.close()

    def _process(self, conn, job) -> None:
        """Run one claimed job and notify the change callback."""
        try:
            if job["kind"] == "capture":
                run_capture(conn, job["id"], self._fetcher, self._screenshotter)
            else:
                conn.execute(
                    "UPDATE jobs SET state = 'failed', error = ?, updated_at = ? WHERE id = ?",
                    (f"Unknown job kind: {job['kind']}", _timestamp(), job["id"]),
                )
        except Exception:  # noqa: BLE001 - the worker must survive any single job
            pass
        if self._on_change:
            try:
                self._on_change()
            except Exception:  # noqa: BLE001 - callback errors must not stop the loop
                pass
