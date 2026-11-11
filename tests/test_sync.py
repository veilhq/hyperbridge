"""Tests for pairing, signed sync and machine discovery."""

import json
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import lan  # noqa: E402
import sync  # noqa: E402
from tests.test_lan import LanCase  # noqa: E402


def free_udp_port() -> int:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


class SyncCase(LanCase):
    """Two Sync machines: this thread's (home) and one whose server runs on threads (laptop)."""

    def setUp(self):
        super().setUp()
        port = free_udp_port()
        self.home = sync.Sync(self.main / "sync.json", "home", discovery_port=port, broadcast="127.0.0.1")
        self.there = sync.Sync(self.laptop / "sync.json", "laptop", discovery_port=port, broadcast="127.0.0.1")
        self.addCleanup(self.home.stop)
        self.addCleanup(self.there.stop)
        self.laptop_address = f"127.0.0.1:{self.there.port}"

    def see_laptop(self, pairing=False):
        self.home.found[self.there.store.id] = {"name": "laptop", "address": self.laptop_address,
                                                 "pairing": pairing, "seen": time.monotonic()}

    def pair(self):
        code = self.there.start_pairing()["code"]
        self.see_laptop(pairing=True)
        self.home.pair(self.there.store.id, code)
        self.see_laptop()


class PairingTests(SyncCase):
    def test_correct_code_stores_matching_secrets(self):
        self.pair()
        self.assertEqual(self.home.store.secret_for(self.there.store.id), self.there.store.secret_for(self.home.store.id))
        self.assertTrue(self.home.store.secret_for(self.there.store.id))

    def test_wrong_code_is_refused_and_stores_nothing(self):
        code = self.there.start_pairing()["code"]
        self.see_laptop(pairing=True)
        with self.assertRaises(lan.LanError):
            self.home.pair(self.there.store.id, "000000" if code != "000000" else "111111")
        self.assertEqual(self.home.store.peers(), {})
        self.assertEqual(self.there.store.peers(), {})

    def test_window_is_single_use(self):
        self.pair()
        self.assertEqual(self.there.pairing_seconds(), 0)
        with self.assertRaises(lan.LanError):
            self.home.pair(self.there.store.id, "123456")

    def test_repeated_wrong_codes_close_the_window(self):
        self.there.start_pairing()
        self.see_laptop(pairing=True)
        for _ in range(lan.MAX_FAILURES):
            with self.assertRaises(lan.LanError):
                self.home.pair(self.there.store.id, "bad")
        self.assertEqual(self.there.pairing_seconds(), 0)

    def test_unpaired_machine_without_window_is_not_listed(self):
        self.see_laptop()
        self.assertNotIn(self.there.store.id, self.home.machines())


class SignedRequestTests(SyncCase):
    def get(self, headers):
        request = urllib.request.Request(f"http://{self.laptop_address}/manifest", headers=headers)
        return urllib.request.urlopen(request, timeout=5)

    def signed(self, stamp=None, secret=None):
        stamp = str(int(time.time()) if stamp is None else stamp)
        secret = secret or self.home.store.secret_for(self.there.store.id)
        return {"X-Peer": self.home.store.id, "X-Time": stamp, "X-Sig": sync._signature(secret, "GET", "/manifest", stamp)}

    def test_paired_peer_can_pull(self):
        self.pair()
        result = self.home.pull_from(self.there.store.id, self.laptop_address)
        self.assertEqual(result["added"], 2)
        self.assertEqual(self.home.received, 2)

    def test_second_pull_adds_nothing(self):
        self.pair()
        self.home.pull_from(self.there.store.id, self.laptop_address)
        self.assertEqual(self.home.pull_from(self.there.store.id, self.laptop_address)["added"], 0)

    def test_bad_signature_is_refused(self):
        self.pair()
        with self.assertRaises(urllib.error.HTTPError) as caught:
            self.get(self.signed(secret="0" * 64))
        self.assertEqual(caught.exception.code, 403)

    def test_stale_timestamp_is_refused(self):
        self.pair()
        with self.assertRaises(urllib.error.HTTPError):
            self.get(self.signed(stamp=int(time.time()) - sync.SIGNATURE_SKEW - 30))

    def test_unknown_peer_is_refused(self):
        with self.assertRaises(urllib.error.HTTPError):
            self.get({"X-Peer": "nobody", "X-Time": str(int(time.time())), "X-Sig": "x"})

    def test_unpaired_side_reports_pair_again(self):
        self.pair()
        self.there.store.remove(self.home.store.id)
        with self.assertRaises(lan.LanError) as caught:
            self.home.pull_from(self.there.store.id, self.laptop_address)
        self.assertEqual(str(caught.exception), sync.DENIED)


class SyncWithTests(SyncCase):
    def test_sync_pulls_then_asks_peer_to_pull(self):
        self.pair()
        with mock.patch.object(self.there, "pull_from", return_value={"added": 3, "skipped": 0, "sets": 0}) as pulled:
            result = self.home.sync_with(self.there.store.id)
        self.assertEqual(result["pulled"]["added"], 2)
        self.assertEqual(result["pushed"]["added"], 3)
        self.assertEqual(result["push_error"], "")
        peer_id, address = pulled.call_args.args
        self.assertEqual(peer_id, self.home.store.id)
        self.assertTrue(address.endswith(f":{self.home.port}"))

    def test_unsigned_pull_request_is_refused(self):
        self.pair()
        request = urllib.request.Request(f"http://{self.laptop_address}/pull", data=json.dumps({"port": self.home.port}).encode(),
                                         headers={"Content-Type": "application/json"})
        with self.assertRaises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(caught.exception.code, 403)

    def test_unpaired_machine_cannot_sync(self):
        self.see_laptop()
        with self.assertRaises(lan.LanError):
            self.home.sync_with(self.there.store.id)


class DiscoveryTests(SyncCase):
    def test_listener_records_a_beacon(self):
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        beacon = {"app": "hyperbridge", "id": "abc", "name": "other", "port": 4242, "pairing": True}
        deadline = time.monotonic() + 5
        while "abc" not in self.home.found and time.monotonic() < deadline:
            sender.sendto(json.dumps(beacon).encode(), ("127.0.0.1", self.home.discovery_port))
            time.sleep(0.1)
        self.assertEqual(self.home.found["abc"]["address"], "127.0.0.1:4242")
        self.assertIn("abc", self.home.machines())

    def test_foreign_and_own_beacons_are_ignored(self):
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.addCleanup(sender.close)
        for beacon in ({"app": "other", "id": "x", "port": 1}, {"app": "hyperbridge", "id": self.home.store.id, "port": 1}):
            sender.sendto(json.dumps(beacon).encode(), ("127.0.0.1", self.home.discovery_port))
        time.sleep(0.5)
        self.assertEqual(self.home.found, {})

    def test_stale_machines_drop_off(self):
        self.home.found["old"] = {"name": "old", "address": "127.0.0.1:1", "pairing": True, "seen": time.monotonic() - sync.SEEN_SECONDS - 1}
        self.assertNotIn("old", self.home.machines())

    def test_paired_machine_stays_listed_offline(self):
        self.pair()
        self.home.found.clear()
        listed = self.home.machines()[self.there.store.id]
        self.assertTrue(listed["paired"])
        self.assertFalse(listed["online"])
