"""The catalog of outside services Hyperbridge can or cannot pull from."""

# access: "open" needs nothing, "none" cannot be pulled automatically.
SOURCES = [
    {"id": "arena", "name": "Are.na", "access": "open", "description": "Public channels, read through the Are.na API."},
    {"id": "tumblr", "name": "Tumblr", "access": "open", "description": "Blogs such as searchsystem.co, read through the blog's public API."},
    {"id": "cosmos", "name": "Cosmos", "access": "none", "description": "No public API, and its terms forbid automated access."},
    {"id": "savee", "name": "Savee", "access": "none", "description": "Its terms forbid scraping, storing its content and building indexes from it."},
    {"id": "pinterest", "name": "Pinterest", "access": "none", "description": "Boards load through scripts and a login, so they cannot be read automatically."},
]


def list_sources() -> list[dict]:
    """Return the catalog, marking which services can be followed."""
    return [{**source, "available": source["access"] != "none"} for source in SOURCES]
