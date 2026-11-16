"""Per-machine preferences kept as JSON beside the library; they are not exported or synced."""

import json
import threading

from bridge.core import db

DEFAULTS = {"downscale_originals": False}
_lock = threading.Lock()


def _path():
    return db.data_dir() / "preferences.json"


def load() -> dict:
    """Return every preference, falling back to the default for missing or unreadable values."""
    try:
        saved = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        saved = {}
    if not isinstance(saved, dict):
        saved = {}
    return {key: type(default)(saved.get(key, default)) for key, default in DEFAULTS.items()}


def get(key: str):
    return load()[key]


def set(key: str, value) -> dict:
    """Store one known preference and return them all."""
    if key not in DEFAULTS:
        raise KeyError(key)
    with _lock:
        values = load()
        values[key] = type(DEFAULTS[key])(value)
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(json.dumps(values, indent=2), encoding="utf-8")
        temp.replace(path)
    return values
