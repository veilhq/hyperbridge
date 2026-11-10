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

import db
import transfer

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


class Share:
    """A short-lived read-only server: it hands out a manifest and requested entry bundles to whoever has the code."""

    def __init__(self):
        self.code = f"{secrets.randbelow(10 ** 6):06d}"
        self.failures = 0
        self.server = ThreadingHTTPServer(("0.0.0.0", 0), _handler_for(self))
        self.port = self.server.server_address[1]
        self.address = f"{local_address()}:{self.port}"
        self._stopped = threading.Event()
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self._timer = threading.Timer(SHARE_SECONDS, self.stop)
        self._timer.daemon = True
        self._timer.start()

    def stop(self) -> None:
        """Close the server; safe to call more than once."""
        if self._stopped.is_set():
            return
        self._stopped.set()
        self._timer.cancel()
        self.server.shutdown()
        self.server.server_close()


def _handler_for(share: "Share"):
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
            if hmac.compare_digest(self.headers.get("X-Code", "").encode(), share.code.encode()):
                return True
            share.failures += 1
            if share.failures >= MAX_FAILURES:
                threading.Thread(target=share.stop, daemon=True).start()
            self._reply(403)
            return False

        def do_GET(self):
            if self.path != "/manifest":
                self._reply(404)
                return
            if not self._authorized():
                return
            conn = db.connect()
            try:
                manifest = {"format": transfer.FORMAT, "schema": db.schema_version(conn), "entries": transfer.list_keys(conn)}
            finally:
                conn.close()
            self._reply(200, json.dumps(manifest).encode())

        def do_POST(self):
            if self.path != "/bundle":
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


def _request(opener, url: str, code: str, body: bytes | None = None):
    request = urllib.request.Request(url, data=body, headers={"X-Code": code, "Content-Type": "application/json"})
    try:
        return opener.open(request, timeout=30)
    except urllib.error.HTTPError as err:
        raise LanError("Wrong code." if err.code == 403 else "The other machine refused the request.") from err
    except OSError as err:
        raise LanError("Could not reach that machine. Is Share running there?") from err


def fetch(conn, address: str, code: str) -> dict:
    """Download the entries this library lacks from a sharing machine and merge them in; returns counts."""
    host, port = _parse_address(address)
    _require_private(host)
    opener = urllib.request.build_opener(_NoRedirect)
    base = f"http://{host}:{port}"
    with _request(opener, f"{base}/manifest", str(code or "").strip()) as reply:
        try:
            manifest = json.loads(reply.read(50_000_000))
            remote = manifest["entries"]
        except (ValueError, KeyError, TypeError) as err:
            raise LanError("That machine did not send a library.") from err
    if int(manifest.get("schema") or 0) > len(db.list_migrations()):
        raise LanError("That library comes from a newer Hyperbridge. Update this copy first.")
    uids = {row[0] for row in conn.execute("SELECT uid FROM entries")}
    keys = {row[0] for row in conn.execute("SELECT source_key FROM entries WHERE source_key IS NOT NULL")}
    missing = [item["uid"] for item in remote
               if item.get("uid") not in uids and not (item.get("source_key") and item["source_key"] in keys)]
    totals = {"added": 0, "skipped": len(remote) - len(missing), "sets": 0}
    for start in range(0, len(missing), BATCH):
        batch = json.dumps({"uids": missing[start:start + BATCH]}).encode()
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / "bundle.zip"
            with _request(opener, f"{base}/bundle", str(code).strip(), batch) as reply, open(bundle, "wb") as out:
                if int(reply.headers.get("Content-Length") or 0) > MAX_BUNDLE_BYTES:
                    raise LanError("That transfer is too large.")
                shutil.copyfileobj(reply, out)
            result = transfer.import_library(conn, bundle)
        totals["added"] += result["added"]
        totals["skipped"] += result["skipped"]
        totals["sets"] += result["sets"]
    return totals
