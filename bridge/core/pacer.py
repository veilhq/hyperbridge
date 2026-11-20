"""Paces outside requests per host and cools a host down after it pushes back, so the app never bursts or retries into a limit."""

import logging
import threading
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from bridge.core.fetchguard import FetchError

logger = logging.getLogger("hyperbridge")

API_GAP = 2.0
SITE_GAP = 1.0
IMAGE_GAP = 0.25
COOLDOWN = 15 * 60
MAX_COOLDOWN = 6 * 60 * 60
PUSHBACK_STATUSES = (403, 429)
CHALLENGE_MARKERS = (b"cf-chl", b"challenge-platform", b"Just a moment...", b"cf-browser-verification")
CHALLENGE_SCAN = 64 * 1024
_API_HOSTS = ("api.are.na", "www.pinterest.com", "pinterest.com", "cdn.syndication.twimg.com",
              "www.instagram.com", "instagram.com")
_IMAGE_HOSTS = ("images.are.na", "i.pinimg.com", "pbs.twimg.com")
_IMAGE_SUFFIXES = (".media.tumblr.com",)


class HostCooling(FetchError):
    """Raised without a request when a host is still cooling down after pushing back."""

    def __init__(self, host: str, until: float, now: float):
        super().__init__("cooling", f"{host} is cooling down for {max(0, int(until - now))}s")
        self.host = host
        self.until = until


def host_of(url) -> str:
    """Return the lowercased hostname of url, or "" when it has none."""
    try:
        return (urlsplit(str(url)).hostname or "").lower()
    except ValueError:
        return ""


def gap_for(url) -> float:
    """Return the minimum seconds between two requests to the host of url."""
    host = host_of(url)
    if host in _IMAGE_HOSTS or host.endswith(_IMAGE_SUFFIXES):
        return IMAGE_GAP
    if host in _API_HOSTS or (host.endswith(".tumblr.com") and "/api/read" in str(url)):
        return API_GAP
    return SITE_GAP


def _retry_after(text, now_wall) -> float:
    """Return the seconds a Retry-After header asks for (delta or HTTP date), or 0 when absent or unreadable."""
    text = str(text or "").strip()
    if not text:
        return 0.0
    if text.isdigit():
        return float(text)
    try:
        return max(0.0, parsedate_to_datetime(text).timestamp() - now_wall)
    except (TypeError, ValueError, IndexError, OverflowError):
        return 0.0


def is_challenge(result) -> bool:
    """Return True when a successful HTML response is a bot-check page rather than the content asked for."""
    if "html" not in str(getattr(result, "content_type", "") or ""):
        return False
    head = bytes(getattr(result, "body", b"") or b"")[:CHALLENGE_SCAN]
    return any(marker in head for marker in CHALLENGE_MARKERS)


class Pacer:
    """Wraps a fetcher: one request per host at a time, a minimum gap between them, and a cooldown after pushback.

    clock and sleep are injectable for tests; wall gives epoch seconds for Retry-After dates.
    """

    def __init__(self, fetcher, *, clock=time.monotonic, sleep=time.sleep, wall=time.time, cooldown=COOLDOWN):
        self._fetcher = fetcher
        self._clock = clock
        self._sleep = sleep
        self._wall = wall
        self._cooldown = cooldown
        self._guard = threading.Lock()
        self._locks = {}
        self._next = {}
        self._cooling = {}

    def _lock_for(self, host):
        with self._guard:
            return self._locks.setdefault(host, threading.Lock())

    def cooling_until(self, url_or_host) -> float:
        """Return the clock time a host's cooldown ends, or 0 when it is not cooling."""
        host = host_of(url_or_host) if "/" in str(url_or_host) else str(url_or_host).lower()
        until = self._cooling.get(host, 0.0)
        return until if until > self._clock() else 0.0

    def is_cooling(self, url_or_host) -> bool:
        """Return True while the host of url_or_host is cooling down."""
        return self.cooling_until(url_or_host) > 0

    def _cool(self, host, seconds, why):
        seconds = min(max(seconds, self._cooldown), MAX_COOLDOWN)
        self._cooling[host] = self._clock() + seconds
        logger.warning("pacer: %s pushed back (%s); cooling down for %ds", host, why, int(seconds))

    def __call__(self, url, **kwargs):
        host = host_of(url)
        if not host:
            return self._fetcher(url, **kwargs)
        with self._lock_for(host):
            now = self._clock()
            until = self._cooling.get(host, 0.0)
            if until > now:
                raise HostCooling(host, until, now)
            wait = self._next.get(host, 0.0) - now
            if wait > 0:
                self._sleep(wait)
            try:
                result = self._fetcher(url, **kwargs)
            except FetchError as exc:
                status = getattr(exc, "status", 0)
                if status in PUSHBACK_STATUSES:
                    self._cool(host, _retry_after(getattr(exc, "retry_after", ""), self._wall()), f"HTTP {status}")
                raise
            finally:
                self._next[host] = self._clock() + gap_for(url)
            if is_challenge(result):
                self._cool(host, 0.0, "challenge page")
                raise FetchError("http_status", "HTTP 403 challenge page", 403)
            return result


_shared = None
_shared_guard = threading.Lock()


def shared(fetcher):
    """Return the one process-wide Pacer around fetcher, creating it on first use."""
    global _shared
    with _shared_guard:
        if _shared is None:
            _shared = Pacer(fetcher)
        return _shared
