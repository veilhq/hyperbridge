"""Sites that publish an RSS or Atom feed with images, such as figsfromplums.com, as a followed discovery source."""

import html
import json
import re
import xml.etree.ElementTree as ElementTree
from datetime import datetime
from email.utils import parsedate_to_datetime
from urllib.parse import quote, urljoin, urlsplit

PER_FEED = 24
IMAGES_PER_ENTRY = 4
MAX_BYTES = 5_000_000
_ATOM = "{http://www.w3.org/2005/Atom}"
_MEDIA = "{http://search.yahoo.com/mrss/}"
_ENCODED = "{http://purl.org/rss/1.0/modules/content/}encoded"
_FEED_TYPES = ("application/rss+xml", "application/atom+xml")
_IMAGE_EXT = re.compile(r"\.(jpe?g|png|gif|webp|avif)$", re.I)
_LINK_TAG = re.compile(r"<link\b[^>]*>", re.I)
_ATTR = re.compile(r"""([\w:-]+)\s*=\s*(?:"([^"]*)"|'([^']*)')""")
_IMG_SRC = re.compile(r"""<img\b[^>]*?\bsrc\s*=\s*["']([^"']+)""", re.I)
_HREF = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["'](https?://[^"']+)""", re.I)
_TAG = re.compile(r"<[^>]+>")
_BREAK = re.compile(r"</p>|<br\s*/?>|</h\d>|</li>|</blockquote>", re.I)
_POSTS = re.compile(r"window\.POSTS\s*=\s*")
_HOUSE_BYLINES = ("", "editors")
_MD_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


def target(url):
    """Return the http(s) link stripped of spaces, or None."""
    url = (url or "").strip()
    parts = urlsplit(url)
    return url if parts.scheme in ("http", "https") and parts.hostname and "." in parts.hostname else None


def _get(fetcher, url):
    reply = fetcher(url)
    return bytes(reply.body)[:MAX_BYTES], getattr(reply, "final_url", "") or url


def _parse(body):
    """Return the root of an RSS or Atom document, or None for anything else."""
    try:
        root = ElementTree.fromstring(body)
    except (ElementTree.ParseError, ValueError):
        return None
    return root if root.tag == "rss" or root.tag == f"{_ATOM}feed" else None


def find_feed(url, fetcher) -> tuple:
    """Return (feed url, parsed feed) for a feed link, or for a page that names its feed; raises ValueError when there is none."""
    body, final = _get(fetcher, url)
    root = _parse(body)
    if root is not None:
        return final, root
    for tag in _LINK_TAG.findall(body.decode("utf-8", "replace")):
        attrs = {name.lower(): html.unescape(double or single) for name, double, single in _ATTR.findall(tag)}
        if "alternate" in attrs.get("rel", "").lower().split() and attrs.get("type", "").lower() in _FEED_TYPES and attrs.get("href"):
            feed_url = urljoin(final, attrs["href"])
            root = _parse(_get(fetcher, feed_url)[0])
            if root is not None:
                return feed_url, root
    raise ValueError("no feed")


def _plain(markup) -> str:
    return " ".join(html.unescape(_TAG.sub(" ", markup or "")).split())


def _caption(markup) -> str:
    return "\n".join(line for line in (_plain(part) for part in _BREAK.split(markup or "")) if line)


def _date(text) -> str:
    text = (text or "").strip()
    try:
        return parsedate_to_datetime(text).date().isoformat()
    except (TypeError, ValueError):
        return text[:10] if re.match(r"\d{4}-\d{2}-\d{2}", text) else ""


def _size(value) -> int:
    return int(value) if str(value or "").isdigit() else 0


def _images(node, markup, base) -> list:
    """Return (image url, width, height) for an entry: media and enclosure images first, then images in its body."""
    found = []
    for media in node.iter():
        if media.tag not in (f"{_MEDIA}content", "enclosure"):
            continue
        url = media.get("url") or ""
        kind = (media.get("type") or "").lower()
        if url and (media.get("medium") == "image" or kind.startswith("image/") or (not kind and _IMAGE_EXT.search(urlsplit(url).path))):
            found.append((urljoin(base, url), _size(media.get("width")), _size(media.get("height"))))
    if not found:
        found = [(urljoin(base, html.unescape(src)), 0, 0) for src in _IMG_SRC.findall(markup or "")]
    if not found:
        found = [(urljoin(base, thumb.get("url")), _size(thumb.get("width")), _size(thumb.get("height")))
                 for thumb in node.iter(f"{_MEDIA}thumbnail") if thumb.get("url")]
    seen, unique = set(), []
    for image in found:
        if image[0] not in seen:
            seen.add(image[0])
            unique.append(image)
    return unique


def _credit(markup, home) -> str:
    """Return the host of the first outside link in an entry, which curation feeds use to credit the maker."""
    for link in _HREF.findall(markup or ""):
        host = re.sub(r"^www\.", "", (urlsplit(html.unescape(link)).hostname or "").lower())
        if host and host != home and not host.endswith("." + home):
            return host[:200]
    return ""


def entries(root, base) -> tuple:
    """Return (feed title, entries) where each entry has its title, link, id, date, categories, text and images."""
    home = re.sub(r"^www\.", "", (urlsplit(base).hostname or "").lower())
    channel = root.find("channel")
    found = []
    if channel is not None:
        title = channel.findtext("title") or ""
        for item in channel.findall("item"):
            markup = item.findtext(_ENCODED) or item.findtext("description") or ""
            found.append({"title": _plain(item.findtext("title")), "link": (item.findtext("link") or "").strip(),
                          "id": (item.findtext("guid") or item.findtext("link") or "").strip(),
                          "date": _date(item.findtext("pubDate")), "categories": [_plain(c.text) for c in item.findall("category") if c.text],
                          "markup": markup, "images": _images(item, markup, base), "credit": _credit(markup, home)})
        return _plain(title), found
    title = root.findtext(f"{_ATOM}title") or ""
    for entry in root.findall(f"{_ATOM}entry"):
        markup = entry.findtext(f"{_ATOM}content") or entry.findtext(f"{_ATOM}summary") or ""
        links = [link for link in entry.findall(f"{_ATOM}link") if link.get("rel", "alternate") == "alternate"]
        found.append({"title": _plain(entry.findtext(f"{_ATOM}title")), "link": links[0].get("href", "") if links else "",
                      "id": (entry.findtext(f"{_ATOM}id") or "").strip(),
                      "date": _date(entry.findtext(f"{_ATOM}published") or entry.findtext(f"{_ATOM}updated")),
                      "categories": [c.get("term") for c in entry.findall(f"{_ATOM}category") if c.get("term")],
                      "markup": markup, "images": _images(entry, markup, base), "credit": _credit(markup, home)})
    return _plain(title), found


def _markup(blocks) -> str:
    """Render a post's text blocks, whose links are markdown, as HTML paragraphs."""
    parts = []
    for block in blocks:
        text, out, last = str(block.get("text") or ""), [], 0
        for link in _MD_LINK.finditer(text):
            out.append(html.escape(text[last:link.start()]))
            out.append(f'<a href="{html.escape(link.group(2))}">{html.escape(link.group(1))}</a>')
            last = link.end()
        parts.append("<p>" + "".join(out) + html.escape(text[last:]) + "</p>")
    return "".join(parts)


def _published(post, now) -> bool:
    try:
        when = datetime.fromisoformat(post.get("publishAt") or "")
    except ValueError:
        return True
    return when <= (now.astimezone(when.tzinfo) if when.tzinfo else now)


def post_entries(page, base, now=None) -> list:
    """Return entries from the full post list a site embeds in its page as window.POSTS, or [] when there is none."""
    match = _POSTS.search(page)
    if not match:
        return []
    try:
        posts, _ = json.JSONDecoder().raw_decode(page, match.end())
    except ValueError:
        return []
    home = re.sub(r"^www\.", "", (urlsplit(base).hostname or "").lower())
    now = now or datetime.now().astimezone()
    found = []
    for post in posts if isinstance(posts, list) else []:
        if not isinstance(post, dict) or not post.get("id") or not _published(post, now):
            continue
        article = post.get("article") if isinstance(post.get("article"), dict) else {}
        blocks = [block for block in article.get("blocks") or [] if isinstance(block, dict)]
        sources = [post.get("src")] + [block.get("src") for block in blocks if block.get("type") == "image"]
        images = list(dict.fromkeys(urljoin(base, src) for src in sources if isinstance(src, str) and src))
        markup = _markup([block for block in blocks if block.get("type") == "text"])
        section = str(post.get("section") or "").strip()
        byline = _plain(article.get("by"))
        found.append({"title": _plain(article.get("title") or post.get("title")),
                      "creator": byline if byline.lower() not in _HOUSE_BYLINES else _plain(post.get("title")),
                      "link": urljoin(base, "/article?id=" + quote(str(post["id"]))), "id": str(post["id"]),
                      "date": _date(post.get("date")), "categories": [section.capitalize()] if section else [],
                      "markup": markup, "images": [(url, 0, 0) for url in images], "credit": _credit(markup, home)})
    return found


def _site_entries(fetcher, feed_url) -> list:
    """Return the embedded post list from the feed's site home page, or [] when it has none or cannot be read."""
    try:
        body, final = _get(fetcher, urljoin(feed_url, "/"))
    except Exception:  # noqa: BLE001 - a missing home page leaves the feed itself
        return []
    return post_entries(body.decode("utf-8", "replace"), final)


def items(feed_url, fetcher, rng, newest=False) -> list:
    """Return feed items from a sample of a site's posts, or its newest posts when asked, one per image.

    Sites that embed their whole post list in the home page are read from that list; others from the feed's latest entries.
    """
    body, final = _get(fetcher, feed_url)
    root = _parse(body)
    if root is None:
        raise ValueError("not an RSS or Atom feed")
    title, found = entries(root, final)
    collection = (title or urlsplit(final).hostname or "")[:200]
    found = [entry for entry in (_site_entries(fetcher, final) or found) if entry["images"]]
    if newest:
        found = sorted(found, key=lambda entry: entry["date"], reverse=True)[:PER_FEED]
    else:
        found = rng.sample(found, min(PER_FEED, len(found)))
    result = []
    for entry in found:
        caption = _caption(entry["markup"])[:1000]
        for url, width, height in entry["images"][:IMAGES_PER_ENTRY]:
            result.append({
                "source_id": "rss", "url": url, "thumb": url, "width": width, "height": height,
                "title": entry["title"][:300], "creator": entry.get("creator", "")[:200],"page_url": urljoin(final, entry["link"]) if entry["link"] else final,
                "term": (entry["categories"][0] if entry["categories"] else collection)[:100], "tags": entry["categories"],
                "source_ref": entry["id"][:200], "posted_at": entry["date"], "collection": collection,
                "description": caption if caption.lower() != entry["title"].lower() else "", "publisher": entry["credit"],
            })
    return result


def follow(conn, url, fetcher) -> dict:
    """Follow a site's RSS or Atom feed, found from the feed link or the site's own page; raises ValueError otherwise."""
    if not target(url):
        raise ValueError("Paste an Are.na, Pinterest or Tumblr link, or a site with an RSS feed.")
    try:
        feed_url, root = find_feed(target(url), fetcher)
    except Exception as err:  # noqa: BLE001 - any read failure means the link cannot be followed
        raise ValueError("Could not find an RSS or Atom feed at that link.") from err
    title, found = entries(root, feed_url)
    if not any(entry["images"] for entry in found):
        raise ValueError("That site's feed has no images to pull.")
    conn.execute(
        "INSERT OR IGNORE INTO followed_sources (kind, url, label, created_at) VALUES ('rss', ?, ?, ?)",
        (feed_url, (title or urlsplit(feed_url).hostname or feed_url)[:200], datetime.now().isoformat(timespec="seconds")))
    return dict(conn.execute("SELECT id, kind, url, label FROM followed_sources WHERE url = ?", (feed_url,)).fetchone())
