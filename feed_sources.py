"""The catalog of outside sources a discovery feed may pull from, and which of them are switched on."""

import db

MAX_KEY = 200

# access: "open" needs nothing, "key" needs the user's own API key, "none" cannot be pulled automatically.
SOURCES = [
    {"id": "arena", "name": "Are.na", "access": "open", "description": "Public channels, read through the Are.na API."},
    {"id": "tumblr", "name": "Tumblr", "access": "open", "description": "Blogs such as searchsystem.co, read through the blog's public API."},
    {"id": "cosmos", "name": "Cosmos", "access": "none", "description": "No public API, and its terms forbid automated access."},
    {"id": "savee", "name": "Savee", "access": "none", "description": "Its terms forbid scraping, storing its content and building indexes from it."},
    {"id": "pinterest", "name": "Pinterest", "access": "none", "description": "Boards load through scripts and a login, so they cannot be read automatically."},
]
_BY_ID = {source["id"]: source for source in SOURCES}


def list_sources() -> list[dict]:
    """Return the catalog with each source's switch and whether a key is stored (never the key itself)."""
    conn = db.connect()
    try:
        saved = {row["source_id"]: row for row in conn.execute("SELECT source_id, enabled, api_key FROM feed_sources")}
    finally:
        conn.close()
    result = []
    for source in SOURCES:
        row = saved.get(source["id"])
        usable = source["access"] != "none"
        result.append({
            **source,
            "available": usable,
            "enabled": bool(row and row["enabled"]) and usable,
            "has_key": bool(row and row["api_key"]),
        })
    return result


def set_source(source_id, enabled, api_key=None) -> dict | None:
    """Switch a source on or off and optionally store its key; returns the updated source, or None if unknown or unavailable."""
    source = _BY_ID.get(source_id)
    if not source or source["access"] == "none":
        return None
    key = None if api_key is None else str(api_key).strip()[:MAX_KEY]
    conn = db.connect()
    try:
        conn.execute("INSERT OR IGNORE INTO feed_sources (source_id) VALUES (?)", (source_id,))
        conn.execute("UPDATE feed_sources SET enabled = ? WHERE source_id = ?", (1 if enabled else 0, source_id))
        if key is not None:
            conn.execute("UPDATE feed_sources SET api_key = ? WHERE source_id = ?", (key, source_id))
    finally:
        conn.close()
    return next(item for item in list_sources() if item["id"] == source_id)


def enabled_sources() -> list[str]:
    """Return the ids of the sources that are on and, where a key is required, have one."""
    return [item["id"] for item in list_sources() if item["enabled"] and (item["access"] != "key" or item["has_key"])]
