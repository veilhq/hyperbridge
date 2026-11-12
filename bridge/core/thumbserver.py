"""Loopback image server: grid thumbnails load by URL instead of travelling the JS bridge as base64."""

import http.server
import logging
import secrets
import threading
from pathlib import Path
from urllib.parse import quote, unquote, urlsplit

from bridge.core import db

logger = logging.getLogger("hyperbridge")
IMAGE_TYPES = {".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".gif": "image/gif"}
_state: dict = {"server": None, "base": None, "token": None}


def _resolve(relative: str) -> Path | None:
    """Return the stored image a relative path names, or None unless it is an image inside the assets folder."""
    root = (db.data_dir() / "assets").resolve()
    try:
        target = (db.data_dir() / relative).resolve()
    except (OSError, ValueError):
        return None
    if root not in target.parents or target.suffix.lower() not in IMAGE_TYPES or not target.is_file():
        return None
    return target


class _Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):  # noqa: D401 - silence per-request logging
        return

    def do_GET(self):  # noqa: N802 - http.server naming
        parts = unquote(urlsplit(self.path).path).lstrip("/").split("/", 1)
        target = _resolve(parts[1]) if len(parts) == 2 and secrets.compare_digest(parts[0], _state["token"] or "") else None
        if target is None:
            self.send_error(404)
            return
        stat = target.stat()
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.end_headers()
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", IMAGE_TYPES[target.suffix.lower()])
        self.send_header("Content-Length", str(len(body)))
        self.send_header("ETag", etag)
        self.send_header("Cache-Control", "private, max-age=31536000, immutable")
        self.end_headers()
        self.wfile.write(body)


def start() -> str | None:
    """Start the loopback server once and return its base URL; None when it cannot bind."""
    if _state["server"]:
        return _state["base"]
    try:
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    except OSError:
        logger.exception("thumbnail server could not start")
        return None
    server.daemon_threads = True
    _state["token"] = secrets.token_urlsafe(16)
    _state["server"] = server
    _state["base"] = f"http://127.0.0.1:{server.server_address[1]}/{_state['token']}/"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return _state["base"]


def stop() -> None:
    """Shut the server down (tests and app exit)."""
    server = _state["server"]
    if server:
        server.shutdown()
        server.server_close()
    _state.update(server=None, base=None, token=None)


def url_for(relative: str) -> str | None:
    """Return the URL serving a stored image, versioned by its modified time; None when the server is off or the file is missing."""
    base = _state["base"]
    if not base or Path(relative).suffix.lower() not in IMAGE_TYPES:
        return None
    try:
        stamp = (db.data_dir() / relative).stat().st_mtime_ns
    except OSError:
        return None
    return f"{base}{quote(relative)}?v={stamp:x}"
