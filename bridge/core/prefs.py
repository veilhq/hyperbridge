"""Per-machine preferences kept as JSON beside the library; they are not exported or synced."""

import json
import threading

from bridge.core import db

DEFAULTS = {
    "downscale_originals": False,
    "library_order": "newest",
    "library_group": "",
    "library_columns": 0,
    "lightbox_fit": "fill",
    "sets_sort": "recent",
    "sets_rail_collapsed": False,
    "feed_ai": "blur",
}

# Allowed values for preferences limited to a fixed set.
CHOICES = {
    "library_order": ("newest", "color", "oldest", "title", "source", "random"),
    "library_group": ("", "color", "year", "source"),
    "library_columns": (-2, -1, 0, 1, 2),
    "lightbox_fit": ("fill", "fit"),
    "sets_sort": ("recent", "name", "size"),
    "feed_ai": ("hide", "blur", "show"),
}

# Preferences the app reads at launch as the starting view; the Defaults settings tab edits them.
VIEW_DEFAULTS = ("library_order", "library_group", "library_columns", "lightbox_fit", "sets_sort", "sets_rail_collapsed",
                 "feed_ai")

_lock = threading.Lock()


def _path():
    return db.data_dir() / "preferences.json"


def _coerce(key: str, value):
    """Return value as the preference's type, raising ValueError when it is not an allowed value."""
    default = DEFAULTS[key]
    if isinstance(default, bool):
        if not isinstance(value, bool):
            raise ValueError(f"{key} must be true or false")
        return value
    if isinstance(default, int):
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"{key} must be a whole number")
    elif not isinstance(value, type(default)):
        raise ValueError(f"{key} has the wrong type")
    if key in CHOICES and value not in CHOICES[key]:
        raise ValueError(f"{value!r} is not an allowed value for {key}")
    return value


def load() -> dict:
    """Return every preference, falling back to the default for missing, unreadable or disallowed values."""
    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    values = {}
    for key, default in DEFAULTS.items():
        try:
            values[key] = _coerce(key, saved[key]) if key in saved else default
        except ValueError:
            values[key] = default
    return values


def get(key: str):
    return load()[key]


def view_defaults() -> dict:
    """Return the launch-view preferences only."""
    values = load()
    return {key: values[key] for key in VIEW_DEFAULTS}


def set(key: str, value) -> dict:
    """Store one known preference and return them all; raises KeyError or ValueError for bad input."""
    if key not in DEFAULTS:
        raise KeyError(key)
    if isinstance(DEFAULTS[key], bool) and not isinstance(value, bool):
        value = bool(value)
    with _lock:
        values = load()
        values[key] = _coerce(key, value)
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(values, indent=2), encoding="utf-8")
        temp.replace(path)
    return values
