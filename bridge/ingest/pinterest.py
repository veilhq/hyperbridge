"""Reads the pins of a public Pinterest board, section by section, through the JSON endpoints the board page itself calls."""
import json
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode, urlsplit

PIN_LIMIT = 1000
PAGE_SIZE = 25
SECTION_WORKERS = 4
_HANDLER = {"X-Pinterest-PWS-Handler": "www/[username]/[slug].js"}
_RESERVED = {"pin", "search", "ideas", "today", "explore", "business", "settings", "_saved", "_created", "videos", "shop"}
_RESOURCE = "https://www.pinterest.com/resource/{name}/get/?"


def board_ref(page_url):
    """Return (username, board slug, section slug or "") for a Pinterest board or section link, or None for any other page."""
    parts = urlsplit(page_url)
    host = (parts.hostname or "").lower()
    if not (host == "pinterest.com" or host.startswith("pinterest.") or host.endswith(".pinterest.com")):
        return None
    segments = [part for part in parts.path.split("/") if part]
    if len(segments) not in (2, 3) or any(part in _RESERVED for part in segments):
        return None
    return segments[0], segments[1], segments[2] if len(segments) == 3 else ""


def _read(fetcher, name, options, source):
    """Call one Pinterest resource endpoint and return its resource_response."""
    query = urlencode({"source_url": source, "data": json.dumps({"options": options, "context": {}})})
    response = fetcher(_RESOURCE.format(name=name) + query, headers=_HANDLER)
    return json.loads(bytes(response.body).decode("utf-8", "replace")).get("resource_response") or {}


def _pages(fetcher, name, options, source, limit):
    """Yield the data items of a resource page by page, following the paging bookmark up to limit items."""
    options = dict(options, page_size=PAGE_SIZE)
    count = 0
    while count < limit:
        data = _read(fetcher, name, options, source)
        items = data.get("data") or []
        count += len(items)
        yield from items
        bookmark = data.get("bookmark")
        if not bookmark or bookmark == "-end-" or not items:
            break
        options["bookmarks"] = [bookmark]


def _pin(item, section=""):
    """Return the pin's image URLs, size, id, title and section name, or None when it has no image."""
    sizes = item.get("images") or {}
    full = sizes.get("orig") or sizes.get("736x") or {}
    preview = sizes.get("474x") or sizes.get("236x") or full
    if item.get("type") != "pin" or not full.get("url") or not preview.get("url"):
        return None
    pin_id = str(item.get("id") or "")
    return {"url": full["url"], "preview": preview["url"], "width": full.get("width") or 0, "height": full.get("height") or 0,
            "id": pin_id if pin_id.isdigit() else "", "title": str(item.get("grid_title") or item.get("title") or "").strip(),
            "section": section}


def _section_pins(fetcher, section, source, limit):
    """Return the pins of one board section, each marked with the section name."""
    options = {"section_id": section["id"], "field_set_key": "react_grid_pin"}
    where = source + quote(section.get("slug") or "") + "/"
    items = _pages(fetcher, "BoardSectionPinsResource", options, where, limit)
    return [pin for pin in (_pin(item, section.get("title") or "") for item in items) if pin]


def board_pins(ref, fetcher, limit=PIN_LIMIT):
    """Return (board name, pins) for a public board or one of its sections; each pin names its section."""
    username, slug, section_slug = ref
    source = "/" + quote(username) + "/" + quote(slug) + "/"
    board = _read(fetcher, "BoardResource", {"username": username, "slug": slug, "field_set_key": "detail"}, source).get("data") or {}
    if not board.get("id"):
        return "", []
    sections = list(_pages(fetcher, "BoardSectionsResource", {"board_id": board["id"]}, source, 200))
    if section_slug:
        sections = [item for item in sections if item.get("slug") == section_slug]
        if not sections:
            return board.get("name") or "", []
    with ThreadPoolExecutor(max_workers=SECTION_WORKERS) as pool:
        grouped = list(pool.map(lambda item: _section_pins(fetcher, item, source, limit), sections))
    pins, seen = [], set()
    for group in grouped:
        for pin in group:
            if pin["url"] not in seen:
                seen.add(pin["url"])
                pins.append(pin)
    if not section_slug and len(pins) < int(board.get("pin_count") or 0):
        options = {"board_id": board["id"], "board_url": source, "field_set_key": "react_grid_pin",
                   "filter_section_pins": False, "layout": "default"}
        for item in _pages(fetcher, "BoardFeedResource", options, source, limit):
            pin = _pin(item)
            if pin and pin["url"] not in seen:
                seen.add(pin["url"])
                pins.append(pin)
    return board.get("name") or "", pins[:limit]
