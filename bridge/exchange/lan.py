"""Local-network transfer: share this library for a few minutes, or fetch the entries it lacks from another machine."""

import hmac
import ipaddress
import json
import secrets
import shutil
import socket
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from bridge.core import db
from bridge.exchange import transfer

SHARE_SECONDS = 300
MAX_FAILURES = 5
MAX_BODY = 1_000_000
MAX_BUNDLE_BYTES = 4_000_000_000
BATCH = 100


class LanError(Exception):
    """A LAN transfer that cannot proceed; the message is safe to show."""


def local_address() -> str:
    """Return this machine's LAN address (no traffic is sent), or loopback when there is none."""
    for probe in ("10.255.255.255", "8.8.8.8"):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect((probe, 1))
            return sock.getsockname()[0]
        except OSError:
            continue
        finally:
            sock.close()
    return "127.0.0.1"


def local_addresses() -> list[str]:
    """Return every private IPv4 address of this machine, the default-route one first, so either network can be used."""
    found = [local_address()]
    candidates = []
    try:
        candidates += [info[4][0] for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET)]
        import psutil  # optional: lists every adapter, which the hostname lookup can miss

        candidates += [item.address for items in psutil.net_if_addrs().values() for item in items if item.family == socket.AF_INET]
    except (OSError, ImportError):
        pass
    for ip in candidates:
        address = ipaddress.ip_address(ip)
        if ip not in found and address.is_private and not (address.is_loopback or address.is_link_local):
            found.append(ip)
    return found


class Share:
    """A short-lived read-only server: it hands out a manifest and requested entry bundles to whoever has the code."""

    def __init__(self):
        self.code = f"{secrets.randbelow(10 ** 6):06d}"
        self.failures = 0
        self.server = ThreadingHTTPServer(("0.0.0.0", 0), _handler_for(self))
        self.port = self.server.server_address[1]
        self.addresses = [f"{ip}:{self.port}" for ip in local_addresses()]
        self.address = self.addresses[0]
        self._stopped = threading.Event()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self._timer = threading.Timer(SHARE_SECONDS, self.stop)
        self._timer.daemon = True
        self._timer.start()

    def authorize(self, request) -> bool:
        """Accept a request carrying the share code; five wrong codes close the share."""
        if hmac.compare_digest(request.headers.get("X-Code", "").encode(), self.code.encode()):
            return True
        self.failures += 1
        if self.failures >= MAX_FAILURES:
            threading.Thread(target=self.stop, daemon=True).start()
        request._reply(403)
        return False

    def stop(self) -> None:
        """Close the server; safe to call more than once."""
        if self._stopped.is_set():
            return
        self._stopped.set()
        self._timer.cancel()
        self.server.shutdown()
        self.server.server_close()


def _handler_for(share):
    """Build the request handler for a server whose authorize(request) decides who may read; share.post(request) may add routes."""

    class Handler(BaseHTTPRequestHandler):
        timeout = 30

        def log_message(self, *args):
            return

        def _reply(self, status: int, body: bytes = b"{}") -> None:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _authorized(self) -> bool:
            return share.authorize(self)

        def json_body(self):
            """Return the small JSON object in the request body, or None when it is missing or malformed."""
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                return None
            try:
                body = json.loads(self.rfile.read(length))
            except ValueError:
                return None
            return body if isinstance(body, dict) else None

        def do_GET(self):
            if self.path != "/manifest":
                self._reply(404)
                return
            if not self._authorized():
                return
            conn = db.connect()
            try:
                manifest = {"format": transfer.FORMAT, "schema": db.schema_version(conn), "entries": transfer.list_keys(conn),
                            "deleted": transfer.list_deletions(conn), "sets": transfer.list_set_heads(conn),
                            "deleted_sets": transfer.list_set_deletions(conn)}
            finally:
                conn.close()
            self._reply(200, json.dumps(manifest).encode())

        def do_POST(self):
            if self.path != "/bundle":
                extra = getattr(share, "post", None)
                if not (extra and extra(self)):
                    self._reply(404)
                return
            if not self._authorized():
                return
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY:
                self._reply(413)
                return
            try:
                uids = json.loads(self.rfile.read(length)).get("uids")
            except (ValueError, AttributeError):
                uids = None
            if not isinstance(uids, list) or not all(isinstance(uid, str) for uid in uids):
                self._reply(400)
                return
            conn = db.connect()
            try:
                with tempfile.TemporaryDirectory() as folder:
                    bundle = Path(folder) / "bundle.zip"
                    transfer.export_library(conn, bundle, only_uids=set(uids))
                    self.send_response(200)
                    self.send_header("Content-Type", "application/zip")
                    self.send_header("Content-Length", str(bundle.stat().st_size))
                    self.end_headers()
                    with open(bundle, "rb") as source:
                        shutil.copyfileobj(source, self.wfile)
            finally:
                conn.close()

    return Handler


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def _parse_address(address: str) -> tuple[str, int]:
    """Split host:port, tolerating a leading http://; raises LanError when malformed."""
    text = (address or "").strip().replace("http://", "").strip("/")
    host, _, port = text.rpartition(":")
    if not host or not port.isdigit() or not 0 < int(port) < 65536:
        raise LanError("Enter the address as shown on the other machine, like 192.168.1.20:51234.")
    return host, int(port)


def _require_private(host: str) -> None:
    """Refuse anything that is not a local-network address, so a typo cannot send the code to the internet."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError as err:
        raise LanError("Could not find that machine.") from err
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        if not (ip.is_private or ip.is_loopback or ip.is_link_local):
            raise LanError("That address is not on your local network.")


def _request(opener, url: str, headers: dict, body: bytes | None = None, denied: str = "Wrong code.", timeout: int = 30):
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json", **headers})
    try:
        return opener.open(request, timeout=timeout)
    except urllib.error.HTTPError as err:
        raise LanError(denied if err.code == 403 else "The other machine refused the request.") from err
    except OSError as err:
        raise LanError(
            "Could not reach that machine. Check that it is open, that both machines are on the same "
            "network (try the other address if two are listed), and that the firewall allows Python."
        ) from err


def pull(conn, base: str, sign, denied: str = "Wrong code.", update=False) -> dict:
    """Download the entries this library lacks from the server at base and merge them in; sign(method, path) gives the request headers.

    With update, entries edited more recently there also bring their fields, tags and sets here, and entries deleted
    there (and not edited here since) are deleted here too; entries deleted here stay deleted unless edited there since.
    """
    opener = urllib.request.build_opener(_NoRedirect)
    with _request(opener, f"{base}/manifest", sign("GET", "/manifest"), denied=denied) as reply:
        try:
            manifest = json.loads(reply.read(50_000_000))
            remote = manifest["entries"]
        except (ValueError, KeyError, TypeError) as err:
            raise LanError("That machine did not send a library.") from err
    if int(manifest.get("schema") or 0) > len(db.list_migrations()):
        raise LanError("That library comes from a newer Hyperbridge. Update this copy first.")
    deleted = transfer.apply_deletions(conn, manifest.get("deleted", [])) if update else 0
    set_changes = 0
    if update:
        set_changes = transfer.apply_set_deletions(conn, manifest.get("deleted_sets", [])) + transfer.merge_set_heads(conn, manifest.get("sets", []), True)
    gone = {row[0]: row[1] for row in conn.execute("SELECT uid, deleted_at FROM entry_deletions")} if update else {}
    remote = [item for item in remote if not (item.get("uid") in gone and str(item.get("updated_at") or "") <= gone[item["uid"]])]
    uids = {row[0]: row[1] or "" for row in conn.execute("SELECT uid, updated_at FROM entries")}
    keys = {row[0] for row in conn.execute("SELECT source_key FROM entries WHERE source_key IS NOT NULL")}
    missing = [item["uid"] for item in remote
               if item.get("uid") not in uids and not (item.get("source_key") and item["source_key"] in keys)]
    newer = [item["uid"] for item in remote
             if update and item.get("uid") in uids and str(item.get("updated_at") or "") > uids[item["uid"]]]
    wanted = missing + newer
    totals = {"added": 0, "skipped": len(remote) - len(wanted), "updated": 0, "deleted": deleted, "sets": set_changes}
    for start in range(0, len(wanted), BATCH):
        batch = json.dumps({"uids": wanted[start:start + BATCH]}).encode()
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / "bundle.zip"
            with _request(opener, f"{base}/bundle", sign("POST", "/bundle"), batch, denied=denied, timeout=600) as reply, open(bundle, "wb") as out:
                if int(reply.headers.get("Content-Length") or 0) > MAX_BUNDLE_BYTES:
                    raise LanError("That transfer is too large.")
                shutil.copyfileobj(reply, out)
            result = transfer.import_library(conn, bundle, update=update)
        totals["added"] += result["added"]
        totals["updated"] += result["updated"]
        totals["skipped"] += result["skipped"]
        totals["sets"] += result["sets"]
    return totals


def fetch(conn, address: str, code: str) -> dict:
    """Fetch from a machine that is sharing, using its on-screen code; returns counts."""
    host, port = _parse_address(address)
    _require_private(host)
    headers = {"X-Code": str(code or "").strip()}
    return pull(conn, f"http://{host}:{port}", lambda method, path: headers)
