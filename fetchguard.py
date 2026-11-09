"""SSRF-safe HTTP fetcher: validated, IP-pinned, size- and time-bounded GET requests."""

import http.client
import ipaddress
import socket
import ssl
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

DEFAULT_UA = "Hyperbridge/1.0 (personal local tool)"
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}
_CHUNK = 64 * 1024


def _tls_context() -> ssl.SSLContext:
    """Default verifying context, plus the certifi bundle when present (Windows stores load roots lazily)."""
    context = ssl.create_default_context()
    try:
        import certifi

        context.load_verify_locations(certifi.where())
    except ImportError:
        pass
    return context


class FetchError(Exception):
    """Raised for any refused or failed fetch; .reason is a short machine-readable code."""

    def __init__(self, reason: str, message: str = ""):
        super().__init__(message or reason)
        self.reason = reason


@dataclass
class FetchResult:
    """A completed fetch: requested and final URL, status, lowercased media type, body."""

    url: str
    final_url: str
    status: int
    content_type: str
    body: bytes


def _check_address(text: str) -> None:
    """Raise blocked_address unless text is a public, globally routable IP."""
    try:
        addr = ipaddress.ip_address(text.split("%", 1)[0])
    except ValueError:
        raise FetchError("blocked_address", f"unparseable address {text!r}") from None
    if isinstance(addr, ipaddress.IPv6Address):
        mapped = addr.ipv4_mapped or addr.sixtofour
        if mapped is not None:
            addr = mapped
    if (
        addr.is_loopback
        or addr.is_private
        or addr.is_link_local
        or addr.is_multicast
        or addr.is_reserved
        or addr.is_unspecified
        or not addr.is_global
    ):
        raise FetchError("blocked_address", f"address {text} is not publicly routable")


def _default_resolver(host: str) -> list[str]:
    """Resolve host to a de-duplicated list of IP strings via getaddrinfo."""
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise FetchError("dns", f"cannot resolve {host}: {exc}") from None
    return list(dict.fromkeys(info[4][0] for info in infos))


class _PinnedHTTPConnection(http.client.HTTPConnection):
    """HTTP connection that dials a fixed IP while keeping the hostname for the Host header."""

    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout)
        self._pinned_ip = ip

    def connect(self):
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout)


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    """HTTPS connection that dials a fixed IP and verifies TLS against the hostname."""

    def __init__(self, host, port, ip, timeout):
        super().__init__(host, port, timeout=timeout, context=_tls_context())
        self._pinned_ip = ip

    def connect(self):
        raw = socket.create_connection((self._pinned_ip, self.port), self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class _ConnReader:
    """Reader over an HTTP response that closes its connection when closed."""

    def __init__(self, conn, response):
        self._conn = conn
        self._response = response

    def read(self, size):
        return self._response.read(size)

    def close(self):
        self._conn.close()


def _real_open(scheme, host, port, ip, path, headers, timeout):
    """Connect to the pinned ip, send GET, return (status, headers, reader)."""
    cls = _PinnedHTTPSConnection if scheme == "https" else _PinnedHTTPConnection
    conn = cls(host, port, ip, timeout)
    try:
        conn.request("GET", path, headers=headers)
        response = conn.getresponse()
    except BaseException:
        conn.close()
        raise
    header_map = {key.lower(): value for key, value in response.getheaders()}
    return response.status, header_map, _ConnReader(conn, response)


def _split(url: str):
    """Validate scheme, userinfo and host of url; return (scheme, host, port, path)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        raise FetchError("scheme", f"malformed URL {url!r}") from None
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https"):
        raise FetchError("scheme", f"scheme {scheme!r} is not allowed")
    if parts.username is not None or parts.password is not None or "@" in parts.netloc:
        raise FetchError("blocked_address", "URLs with credentials are not allowed")
    if not parts.hostname:
        raise FetchError("scheme", "URL has no host")
    path = parts.path or "/"
    if parts.query:
        path += "?" + parts.query
    return scheme, parts.hostname, port or (443 if scheme == "https" else 80), path


def _read_body(reader, max_bytes, deadline) -> bytes:
    """Stream up to max_bytes from reader, honoring the deadline; raise too_large past the cap."""
    chunks, total = [], 0
    while True:
        if time.monotonic() > deadline:
            raise FetchError("timeout", "deadline exceeded while reading body")
        chunk = reader.read(_CHUNK)
        if not chunk:
            return b"".join(chunks)
        total += len(chunk)
        if total > max_bytes:
            raise FetchError("too_large", f"body exceeds {max_bytes} bytes")
        chunks.append(chunk)


def safe_fetch(
    url,
    *,
    max_bytes=10 * 1024 * 1024,
    timeout=10.0,
    max_redirects=5,
    resolver=None,
    opener=None,
    user_agent=DEFAULT_UA,
) -> FetchResult:
    """GET url over http/https, refusing non-public addresses, and return a FetchResult.

    Each hop resolves the host once, requires every address to be public, and connects
    to the first validated IP (pinned). Redirects are re-validated up to max_redirects.
    Cookies and credentials are never sent. timeout is an overall deadline in seconds.

    resolver: callable(host) -> list of IP strings (default: socket.getaddrinfo).
    opener: callable(scheme, host, port, ip, path, headers, timeout) -> (status, headers,
    reader), replacing connect+request. headers is a dict of lowercased response header
    names; reader has read(size) -> bytes (b"" at EOF) and optional close().
    Raises FetchError with .reason in: scheme, blocked_address, dns, too_large,
    too_many_redirects, timeout, http_status, network.
    """
    resolve = resolver or _default_resolver
    open_hop = opener or _real_open
    deadline = time.monotonic() + timeout
    request_headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    current = url
    for hop in range(max_redirects + 1):
        scheme, host, port, path = _split(current)
        try:
            addresses = resolve(host)
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError("dns", f"cannot resolve {host}: {exc}") from None
        if not addresses:
            raise FetchError("dns", f"no addresses for {host}")
        for address in addresses:
            _check_address(address)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise FetchError("timeout", "deadline exceeded")
        reader = None
        try:
            status, headers, reader = open_hop(
                scheme, host, port, addresses[0], path, dict(request_headers), remaining
            )
            if status in _REDIRECT_STATUSES and headers.get("location"):
                if hop == max_redirects:
                    raise FetchError("too_many_redirects", f"more than {max_redirects} redirects")
                current = urljoin(current, headers["location"])
                continue
            if not 200 <= status < 300:
                raise FetchError("http_status", f"HTTP {status}")
            declared = headers.get("content-length", "")
            if declared.strip().isdigit() and int(declared) > max_bytes:
                raise FetchError("too_large", f"Content-Length {declared} exceeds {max_bytes}")
            body = _read_body(reader, max_bytes, deadline)
            media = headers.get("content-type", "").split(";", 1)[0].strip().lower()
            return FetchResult(url, current, status, media, body)
        except FetchError:
            raise
        except (TimeoutError, socket.timeout):
            raise FetchError("timeout", "network timeout") from None
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            raise FetchError("network", str(exc)) from None
        finally:
            if reader is not None and hasattr(reader, "close"):
                reader.close()
    raise FetchError("too_many_redirects", f"more than {max_redirects} redirects")
