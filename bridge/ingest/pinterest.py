"""Reads the pins of a public Pinterest board through the same JSON endpoints the board page itself calls."""
import json
from urllib.parse import quote, urlencode, urlsplit

PIN_LIMIT = 200
PAGE_SIZE = 25
_HANDLER = {"X-Pinterest-PWS-Handler": "www/[username]/[slug].js"}
_RESERVED = {"pin", "search", "ideas", "today", "explore", "business", "settings", "_saved", "_created", "videos", "shop"}
_RESOURCE = "https://www.pinterest.com/resource/{name}/get/?"


def board_ref(page_url):
    """Return (username, board slug) for a Pinterest board link, or None for any other page."""
    parts = urlsplit(page_url)
    host = (parts.hostname or "").lower()
    if not (host == "pinterest.com" or host.startswith("pinterest.") or host.endswith(".pinterest.com")):
        return None
    segments = [part for part in parts.path.split("/") if part]
    if len(segments) != 2 or segments[0] in _RESERVED or segments[1] in _RESERVED:
        return None
    return segments[0], segments[1]


def _read(fetcher, name, options, source):
    """Call one Pinterest resource endpoint and return its resource_response."""
    query = urlencode({"source_url": source, "data": json.dumps({"options": options, "context": {}})})
    response = fetcher(_RESOURCE.format(name=name) + query, headers=_HANDLER)
    return json.loads(bytes(response.body).decode("utf-8", "replace")).get("resource_response") or {}


def _pin(item):
    """Return {url, preview, width, height} for a pin dict, or None when it has no image."""
    sizes = item.get("images") or {}
    full = sizes.get("orig") or sizes.get("736x") or {}
    preview = sizes.get("474x") or sizes.get("236x") or full
    if item.get("type") != "pin" or not full.get("url") or not preview.get("url"):
        return None
    return {"url": full["url"], "preview": preview["url"], "width": full.get("width") or 0, "height": full.get("height") or 0}


def board_pins(ref, fetcher, limit=PIN_LIMIT):
    """Return (board name, pins) for a public board, following the paging bookmark up to limit pins."""
    username, slug = ref
    source = "/" + quote(username) + "/" + quote(slug) + "/"
    board = _read(fetcher, "BoardResource", {"username": username, "slug": slug, "field_set_key": "detail"}, source).get("data") or {}
    if not board.get("id"):
        return "", []
    options = {"board_id": board["id"], "board_url": source, "field_set_key": "react_grid_pin",
               "filter_section_pins": False, "layout": "default", "page_size": PAGE_SIZE}
    pins, seen = [], set()
    while len(pins) < limit:
        data = _read(fetcher, "BoardFeedResource", options, source)
        for item in data.get("data") or []:
            pin = _pin(item)
            if pin and pin["url"] not in seen:
                seen.add(pin["url"])
                pins.append(pin)
        bookmark = data.get("bookmark")
        if not bookmark or bookmark == "-end-" or not data.get("data"):
            break
        options["bookmarks"] = [bookmark]
    return board.get("name") or "", pins[:limit]
