"""Paired machines: find each other on the local network, pair once with a code, then sync new entries in both directions."""

import hmac
import hashlib
import ipaddress
import json
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import uuid
from http.server import ThreadingHTTPServer
from pathlib import Path

from bridge.core import db
from bridge.exchange import lan
from bridge.ingest import capture

DISCOVERY_PORT = 47621
INBOX_PORT = 47622
MAX_CAPTURE_URLS = 200
MAX_CAPTURE_URL_LENGTH = 4000
TOKEN_FAILURES = 5
TOKEN_LOCKOUT_SECONDS = 60
BEACON_SECONDS = 3
SEEN_SECONDS = 12
PAIRING_SECONDS = 300
SIGNATURE_SKEW = 120
ACTIVE_SECONDS = 6
APP_TAG = "hyperbridge"
DENIED = "That machine does not recognize this one. Pair the two again."


class PeerStore:
    """This machine's identity and the secrets it shares with paired machines, kept in one small file."""

    def __init__(self, path: Path | None = None, name: str | None = None, kind: str | None = None):
        self.kind = _kind(kind or detect_kind())
        self.path = Path(path) if path else db.data_dir() / "sync.json"
        self._lock = threading.Lock()
        self._data = self._read()
        if not self._data.get("id"):
            self._data["id"] = uuid.uuid4().hex
        if name or not self._data.get("name"):
            self._data["name"] = name or socket.gethostname()
        self._data.setdefault("peers", {})
        self._write()

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self._data, indent=2), encoding="utf-8")
        temp.replace(self.path)

    @property
    def id(self) -> str:
        return self._data["id"]

    @property
    def name(self) -> str:
        return self._data["name"]

    def peers(self) -> dict:
        with self._lock:
            return {key: dict(value) for key, value in self._data["peers"].items()}

    def secret_for(self, peer_id: str) -> str | None:
        with self._lock:
            peer = self._data["peers"].get(peer_id)
            return peer["secret"] if peer else None

    def add(self, peer_id: str, name: str, secret: str, kind: str = "computer") -> None:
        with self._lock:
            self._data["peers"][peer_id] = {"name": name, "secret": secret, "kind": _kind(kind)}
            self._write()

    def set_kind(self, peer_id: str, kind: str) -> None:
        """Remember what kind of computer a paired machine is, so it still shows while offline."""
        with self._lock:
            peer = self._data["peers"].get(peer_id)
            if peer and peer.get("kind") != _kind(kind):
                peer["kind"] = _kind(kind)
                self._write()

    def remove(self, peer_id: str) -> None:
        with self._lock:
            self._data["peers"].pop(peer_id, None)
            self._write()

    def new_phone_token(self) -> str:
        """Replace the phone capture token with a fresh one and return it; only its hash is kept."""
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._data["phone"] = {"hash": _token_hash(token)}
            self._write()
        return token

    def clear_phone_token(self) -> None:
        with self._lock:
            self._data.pop("phone", None)
            self._write()

    def has_phone_token(self) -> bool:
        with self._lock:
            return bool((self._data.get("phone") or {}).get("hash"))

    def phone_token_ok(self, token: str) -> bool:
        with self._lock:
            stored = (self._data.get("phone") or {}).get("hash") or ""
        return bool(stored and token) and hmac.compare_digest(stored.encode(), _token_hash(token).encode())


def detect_kind() -> str:
    """Return "laptop" when this computer has a battery, else "desktop"; "computer" when that cannot be told."""
    try:
        if sys.platform == "win32":
            import ctypes

            class Power(ctypes.Structure):
                _fields_ = [("ac", ctypes.c_ubyte), ("flag", ctypes.c_ubyte), ("percent", ctypes.c_ubyte),
                            ("saver", ctypes.c_ubyte), ("life", ctypes.c_ulong), ("full", ctypes.c_ulong)]
            status = Power()
            if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)) or status.flag == 255:
                return "computer"
            return "desktop" if status.flag & 128 else "laptop"
        if sys.platform.startswith("linux"):
            return "laptop" if list(Path("/sys/class/power_supply").glob("BAT*")) else "desktop"
        if sys.platform == "darwin":
            model = subprocess.run(["sysctl", "-n", "hw.model"], capture_output=True, text=True, timeout=5).stdout
            return "laptop" if "book" in model.lower() else "desktop"
    except Exception:  # noqa: BLE001 - an unknown kind only changes the icon
        pass
    return "computer"


def _kind(value) -> str:
    return value if value in ("laptop", "desktop") else "computer"


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _signature(secret: str, method: str, path: str, stamp: str) -> str:
    return hmac.new(secret.encode(), f"{method}\n{path}\n{stamp}".encode(), hashlib.sha256).hexdigest()


class Sync:
    """Always-on while Bridge is open: serves paired machines, announces itself, and lists the others it hears."""

    def __init__(self, store_path: Path | None = None, name: str | None = None,
                 discovery_port: int = DISCOVERY_PORT, broadcast: str = "255.255.255.255", kind: str | None = None,
                 port: int = 0):
        self.store = PeerStore(store_path, name, kind)
        self.discovery_port = discovery_port
        self.broadcast = broadcast
        self.received = 0
        self.failures = 0
        self._running = 0
        self._served = 0.0
        self.code: str | None = None
        self.pairing_until = 0.0
        self.found: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._stopped = threading.Event()
        self.token_failures = 0
        self.token_locked_until = 0.0
        try:
            self.server = ThreadingHTTPServer(("0.0.0.0", port), lan._handler_for(self))
        except OSError:
            self.server = ThreadingHTTPServer(("0.0.0.0", 0), lan._handler_for(self))
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        threading.Thread(target=self._beacon, daemon=True).start()
        threading.Thread(target=self._listen, daemon=True).start()

    # ---- pairing window -------------------------------------------------
    def start_pairing(self) -> dict:
        """Open a five-minute window in which another machine can pair using the returned code."""
        self.code = f"{secrets.randbelow(10 ** 6):06d}"
        self.failures = 0
        self.pairing_until = time.monotonic() + PAIRING_SECONDS
        return {"code": self.code, "seconds": PAIRING_SECONDS}

    def stop_pairing(self) -> None:
        self.code = None
        self.pairing_until = 0.0

    def pairing_seconds(self) -> int:
        left = int(self.pairing_until - time.monotonic())
        if left <= 0:
            self.code = None
            return 0
        return left

    # ---- server side ------------------------------------------------------
    def _code_ok(self, request) -> bool:
        if not self.pairing_seconds():
            return False
        return hmac.compare_digest(request.headers.get("X-Code", "").encode(), (self.code or "").encode())

    def syncing(self) -> bool:
        """True while this machine is syncing or a paired machine has read from it within the last few seconds."""
        return self._running > 0 or time.monotonic() - self._served < ACTIVE_SECONDS

    def _signed_ok(self, request) -> bool:
        secret = self.store.secret_for(request.headers.get("X-Peer", ""))
        stamp = request.headers.get("X-Time", "")
        if not secret or not stamp.isdigit() or abs(time.time() - int(stamp)) > SIGNATURE_SKEW:
            return False
        expected = _signature(secret, request.command, request.path, stamp)
        return hmac.compare_digest(request.headers.get("X-Sig", "").encode(), expected.encode())

    def _refuse(self, request) -> bool:
        if self.pairing_seconds():
            self.failures += 1
            if self.failures >= lan.MAX_FAILURES:
                self.stop_pairing()
        request._reply(403)
        return False

    def authorize(self, request) -> bool:
        """Accept a request signed by a paired machine, or one carrying the open pairing code."""
        if self._signed_ok(request):
            self._served = time.monotonic()
            return True
        if self._code_ok(request):
            return True
        return self._refuse(request)

    def post(self, request) -> bool:
        """Handle /pair (code, creates the pairing), /pull (signed, asks this machine to pull from the sender) and /capture (phone token, adds links)."""
        if request.path == "/capture":
            return self._on_capture(request)
        if request.path == "/pair":
            return self._on_pair(request)
        if request.path == "/pull":
            return self._on_pull(request)
        return False

    def _on_pair(self, request) -> bool:
        if not self._code_ok(request):
            return self._refuse(request) or True
        body = request.json_body() or {}
        peer_id, name = str(body.get("id") or ""), str(body.get("name") or "")[:100]
        if not peer_id or peer_id == self.store.id:
            request._reply(400)
            return True
        secret = secrets.token_hex(32)
        self.store.add(peer_id, name or "Another machine", secret, str(body.get("kind") or ""))
        self.stop_pairing()
        request._reply(200, json.dumps({"id": self.store.id, "name": self.store.name, "kind": self.store.kind, "secret": secret}).encode())
        return True

    def _on_capture(self, request) -> bool:
        """Add the links a phone sends ({"urls": [...]} or {"url": "..."}); needs the phone token, reads nothing back."""
        if not self._phone_allowed(request):
            return True
        body = request.json_body()
        urls = body.get("urls") if body and "urls" in body else [body.get("url")] if body else None
        if not isinstance(urls, list) or not urls or len(urls) > MAX_CAPTURE_URLS:
            request._reply(400, json.dumps({"error": "Send a list of links."}).encode())
            return True
        results = []
        conn = db.connect()
        try:
            for url in urls:
                text = str(url or "").strip()
                if not text or len(text) > MAX_CAPTURE_URL_LENGTH:
                    results.append({"url": text[:200], "status": "invalid"})
                    continue
                try:
                    added = capture.add_link(conn, text)
                except ValueError:
                    results.append({"url": text, "status": "invalid"})
                    continue
                results.append({"url": text, "status": "new" if added["created"] else "known"})
        finally:
            conn.close()
        added = sum(1 for item in results if item["status"] == "new")
        self.received += added
        request._reply(200, json.dumps({"results": results, "added": added}).encode())
        return True

    def _phone_allowed(self, request) -> bool:
        """Check the sender is on a private network and holds the phone token; repeated wrong tokens lock requests out briefly."""
        try:
            address = ipaddress.ip_address(request.client_address[0])
        except ValueError:
            address = None
        if not address or not (address.is_private or address.is_loopback):
            request._reply(403)
            return False
        if time.monotonic() < self.token_locked_until:
            request._reply(429)
            return False
        if self.store.phone_token_ok(request.headers.get("X-Token", "")):
            self.token_failures = 0
            return True
        self.token_failures += 1
        if self.token_failures >= TOKEN_FAILURES:
            self.token_failures = 0
            self.token_locked_until = time.monotonic() + TOKEN_LOCKOUT_SECONDS
        request._reply(403)
        return False

    def _on_pull(self, request) -> bool:
        if not self._signed_ok(request):
            return self._refuse(request) or True
        body = request.json_body() or {}
        port = body.get("port")
        if not isinstance(port, int) or not 0 < port < 65536:
            request._reply(400)
            return True
        peer_id = request.headers.get("X-Peer", "")
        self._running += 1
        try:
            result = self.pull_from(peer_id, f"{request.client_address[0]}:{port}")
        except lan.LanError as err:
            request._reply(502, json.dumps({"error": str(err)}).encode())
            return True
        finally:
            self._running -= 1
        request._reply(200, json.dumps(result).encode())
        return True

    # ---- client side ------------------------------------------------------
    def _signer(self, peer_id: str):
        secret = self.store.secret_for(peer_id)
        if not secret:
            raise lan.LanError(DENIED)

        def sign(method: str, path: str) -> dict:
            stamp = str(int(time.time()))
            return {"X-Peer": self.store.id, "X-Time": stamp, "X-Sig": _signature(secret, method, path, stamp)}
        return sign

    def pull_from(self, peer_id: str, address: str) -> dict:
        """Merge the entries a paired machine has that this library lacks, and the edits and deletions it made more recently; the count is added to received when anything arrived."""
        host, port = lan._parse_address(address)
        lan._require_private(host)
        conn = db.connect()
        try:
            result = lan.pull(conn, f"http://{host}:{port}", self._signer(peer_id), denied=DENIED, update=True)
        finally:
            conn.close()
        self.received += result["added"]
        return result

    def pair(self, machine_id: str, code: str) -> dict:
        """Pair with a machine that is showing a pairing code; both sides keep the new shared secret."""
        machine = self.machines().get(machine_id)
        if not machine:
            raise lan.LanError("That machine is no longer visible. Check that it is open on the same network.")
        host, port = lan._parse_address(machine["address"])
        lan._require_private(host)
        body = json.dumps({"id": self.store.id, "name": self.store.name, "kind": self.store.kind}).encode()
        opener = urllib.request.build_opener(lan._NoRedirect)
        with lan._request(opener, f"http://{host}:{port}/pair", {"X-Code": str(code or "").strip()}, body) as reply:
            try:
                answer = json.loads(reply.read(100_000))
                self.store.add(str(answer["id"]), str(answer["name"])[:100], str(answer["secret"]), str(answer.get("kind") or ""))
            except (ValueError, KeyError, TypeError) as err:
                raise lan.LanError("That machine did not complete pairing.") from err
        return {"id": answer["id"], "name": answer["name"]}

    def sync_with(self, machine_id: str) -> dict:
        """Pull a paired machine's new entries, then ask it to pull ours; returns counts for each direction."""
        self._running += 1
        try:
            return self._sync_with(machine_id)
        finally:
            self._running -= 1
            self._served = 0.0

    def _sync_with(self, machine_id: str) -> dict:
        machine = self.machines().get(machine_id)
        if not machine or not machine["paired"]:
            raise lan.LanError("That machine is not visible right now. Check that it is open on the same network.")
        pulled = self.pull_from(machine_id, machine["address"])
        pushed, push_error = None, ""
        host, port = lan._parse_address(machine["address"])
        sign = self._signer(machine_id)
        opener = urllib.request.build_opener(lan._NoRedirect)
        try:
            with lan._request(opener, f"http://{host}:{port}/pull", sign("POST", "/pull"),
                              json.dumps({"port": self.port}).encode(), denied=DENIED, timeout=600) as reply:
                pushed = json.loads(reply.read(100_000))
        except (lan.LanError, ValueError) as err:
            push_error = str(err) or "Could not send entries to that machine."
        return {"pulled": pulled, "pushed": pushed, "push_error": push_error}

    # ---- discovery ----------------------------------------------------------
    def _beacon(self) -> None:
        while not self._stopped.is_set():
            payload = json.dumps({"app": APP_TAG, "id": self.store.id, "name": self.store.name, "kind": self.store.kind,
                                  "port": self.port, "pairing": bool(self.pairing_seconds())}).encode()
            for ip in lan.local_addresses():
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.bind((ip, 0))
                    sock.sendto(payload, (self.broadcast, self.discovery_port))
                except OSError:
                    pass
                finally:
                    sock.close()
            self._stopped.wait(BEACON_SECONDS)

    def _listen(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("", self.discovery_port))
            sock.settimeout(1)
        except OSError:
            sock.close()
            return
        try:
            while not self._stopped.is_set():
                try:
                    data, (ip, _) = sock.recvfrom(2048)
                    info = json.loads(data)
                    address = ipaddress.ip_address(ip)
                except (OSError, ValueError):
                    continue
                if info.get("app") != APP_TAG or info.get("id") == self.store.id or not isinstance(info.get("port"), int):
                    continue
                if not (address.is_private or address.is_loopback):
                    continue
                with self._lock:
                    self.found[str(info["id"])] = {"name": str(info.get("name") or "")[:100], "address": f"{ip}:{info['port']}",
                                                   "kind": _kind(info.get("kind")),
                                                   "pairing": bool(info.get("pairing")), "seen": time.monotonic()}
                self.store.set_kind(str(info["id"]), info.get("kind"))
        finally:
            sock.close()

    def machines(self) -> dict[str, dict]:
        """Machines to show: every paired one (online or not) and any unpaired one that has a pairing window open."""
        now = time.monotonic()
        with self._lock:
            live = {key: value for key, value in self.found.items() if now - value["seen"] <= SEEN_SECONDS}
        result = {}
        for peer_id, peer in self.store.peers().items():
            seen = live.get(peer_id)
            result[peer_id] = {"id": peer_id, "name": peer["name"], "paired": True, "online": bool(seen),
                               "kind": _kind(seen.get("kind") if seen else peer.get("kind")), "address": seen["address"] if seen else "", "pairing": False}
        for peer_id, seen in live.items():
            if peer_id not in result and seen["pairing"]:
                result[peer_id] = {"id": peer_id, "name": seen["name"], "paired": False, "online": True,
                                   "kind": _kind(seen.get("kind")), "address": seen["address"], "pairing": True}
        return result

    def status(self) -> dict:
        """Everything the settings view shows: this machine, the pairing window and the machines around."""
        seconds = self.pairing_seconds()
        return {"name": self.store.name, "pairing_seconds": seconds, "code": self.code if seconds else "",
                "machines": list(self.machines().values()), "received": self.received,
                "phone": {"enabled": self.store.has_phone_token(), "port": self.port, "addresses": lan.local_addresses()}}

    def stop(self) -> None:
        """Close the server and stop announcing; safe to call more than once."""
        if self._stopped.is_set():
            return
        self._stopped.set()
        self.server.shutdown()
        self.server.server_close()
