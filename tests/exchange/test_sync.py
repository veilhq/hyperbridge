"""Tests for pairing, signed sync and machine discovery."""

import json
import sqlite3
import socket
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.library import library  # noqa: E402
from bridge.exchange import lan  # noqa: E402
from bridge.exchange import sync  # noqa: E402
from bridge.exchange import transfer  # noqa: E402
from tests.exchange.test_lan import LanCase  # noqa: E402


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

    def test_both_machines_report_syncing_while_it_runs_and_clear_after(self):
        self.pair()
        seen = {}

        def slow_pull(peer_id, address):
            seen["there"] = self.there.syncing()
            seen["home"] = self.home.syncing()
            return {"added": 0, "skipped": 0, "updated": 0, "sets": 0}

        self.assertFalse(self.home.syncing())
        with mock.patch.object(self.there, "pull_from", side_effect=slow_pull):
            self.home.sync_with(self.there.store.id)
        self.assertEqual(seen, {"there": True, "home": True})
        self.assertFalse(self.home.syncing())

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


class DeletionSyncTests(SyncCase):
    def laptop_db(self):
        conn = sqlite3.connect(str(self.laptop / "hyperbridge.db"), isolation_level=None)
        self.addCleanup(conn.close)
        return conn

    def count(self, conn, uid):
        return conn.execute("SELECT COUNT(*) FROM entries WHERE uid = ?", (uid,)).fetchone()[0]

    def test_a_deletion_on_the_laptop_removes_the_entry_here(self):
        self.pair()
        self.home.sync_with(self.there.store.id)
        self.assertEqual(self.count(self.conn, self.uids[0]), 1)
        laptop = self.laptop_db()
        laptop.execute("DELETE FROM entries WHERE uid = ?", (self.uids[0],))
        laptop.execute("INSERT INTO entry_deletions (uid, deleted_at) VALUES (?, '2999-01-01T00:00:00')", (self.uids[0],))
        result = self.home.sync_with(self.there.store.id)
        self.assertEqual(result["pulled"]["deleted"], 1)
        self.assertEqual(self.count(self.conn, self.uids[0]), 0)
        self.assertEqual(self.count(self.conn, self.uids[1]), 1)
        self.assertFalse((self.main / "assets" / self.uids[0]).exists() if (self.main / "assets").exists() else False)

    def test_a_deletion_here_is_not_undone_and_reaches_the_laptop(self):
        self.pair()
        self.home.sync_with(self.there.store.id)
        entry_id = self.conn.execute("SELECT id FROM entries WHERE uid = ?", (self.uids[0],)).fetchone()[0]
        self.assertTrue(library.discard_entry(entry_id))
        result = self.home.sync_with(self.there.store.id)
        self.assertEqual(result["pulled"]["added"], 0)
        self.assertEqual(self.count(self.conn, self.uids[0]), 0)
        self.assertEqual([item["uid"] for item in transfer.list_deletions(self.conn)], [self.uids[0]])

    def test_a_set_rename_and_delete_on_the_laptop_reach_this_machine(self):
        self.pair()
        self.home.sync_with(self.there.store.id)
        laptop = self.laptop_db()
        laptop.execute("UPDATE sets SET name = 'Prints', updated_at = '2999-01-01T00:00:00'")
        laptop.execute("INSERT INTO sets (name, description, created_at) VALUES ('Extra', '', '2000-01-01T00:00:00')")
        result = self.home.sync_with(self.there.store.id)
        self.assertGreaterEqual(result["pulled"]["sets"], 1)
        self.assertEqual([row[0] for row in self.conn.execute("SELECT name FROM sets ORDER BY name")], ["Extra", "Prints"])
        extra = laptop.execute("SELECT uid FROM sets WHERE name = 'Extra'").fetchone()[0]
        laptop.execute("DELETE FROM sets WHERE name = 'Extra'")
        laptop.execute("INSERT INTO set_deletions (uid, deleted_at) VALUES (?, '2999-01-01T00:00:00')", (extra,))
        self.home.sync_with(self.there.store.id)
        self.assertEqual([row[0] for row in self.conn.execute("SELECT name FROM sets")], ["Prints"])

    def test_an_entry_edited_after_the_deletion_survives(self):
        self.pair()
        self.home.sync_with(self.there.store.id)
        laptop = self.laptop_db()
        laptop.execute("DELETE FROM entries WHERE uid = ?", (self.uids[0],))
        laptop.execute("INSERT INTO entry_deletions (uid, deleted_at) VALUES (?, '2000-01-01T00:00:00')", (self.uids[0],))
        self.conn.execute("UPDATE entries SET title = 'Kept', updated_at = '2999-01-01T00:00:00' WHERE uid = ?", (self.uids[0],))
        self.home.sync_with(self.there.store.id)
        self.assertEqual(self.count(self.conn, self.uids[0]), 1)


class PhoneCaptureTests(SyncCase):
    def post(self, body, token=None):
        headers = {"Content-Type": "application/json"}
        if token is not None:
            headers["X-Token"] = token
        request = urllib.request.Request(f"http://127.0.0.1:{self.there.port}/capture", json.dumps(body).encode(), headers)
        try:
            with urllib.request.urlopen(request, timeout=10) as reply:
                return reply.status, json.loads(reply.read())
        except urllib.error.HTTPError as err:
            return err.code, None

    def laptop_urls(self):
        conn = sqlite3.connect(str(self.laptop / "hyperbridge.db"), isolation_level=None)
        self.addCleanup(conn.close)
        return {row[0] for row in conn.execute("SELECT source_key FROM entries")}

    def test_token_adds_links_and_repeats_are_known(self):
        token = self.there.store.new_phone_token()
        status, reply = self.post({"urls": ["https://example.com/a", "https://example.com/a/", "not a link"]}, token)
        self.assertEqual(status, 200)
        self.assertEqual([item["status"] for item in reply["results"]], ["new", "known", "invalid"])
        self.assertIn("https://example.com/a", self.laptop_urls())
        self.assertEqual(self.there.received, 1)

    def test_single_url_form_is_accepted(self):
        token = self.there.store.new_phone_token()
        status, reply = self.post({"url": "https://example.com/one"}, token)
        self.assertEqual((status, reply["added"]), (200, 1))

    def test_missing_wrong_or_revoked_token_adds_nothing(self):
        token = self.there.store.new_phone_token()
        before = self.laptop_urls()
        self.assertEqual(self.post({"urls": ["https://example.com/x"]})[0], 403)
        self.assertEqual(self.post({"urls": ["https://example.com/x"]}, "wrong")[0], 403)
        self.there.store.clear_phone_token()
        self.assertEqual(self.post({"urls": ["https://example.com/x"]}, token)[0], 403)
        self.assertEqual(self.laptop_urls(), before)

    def test_no_token_set_refuses_everything(self):
        self.assertEqual(self.post({"urls": ["https://example.com/x"]}, "")[0], 403)

    def test_repeated_wrong_tokens_lock_out_even_the_right_one(self):
        token = self.there.store.new_phone_token()
        for _ in range(sync.TOKEN_FAILURES):
            self.post({"urls": ["https://example.com/x"]}, "wrong")
        self.assertEqual(self.post({"urls": ["https://example.com/x"]}, token)[0], 429)

    def test_empty_and_oversized_lists_are_rejected(self):
        token = self.there.store.new_phone_token()
        self.assertEqual(self.post({"urls": []}, token)[0], 400)
        self.assertEqual(self.post({"urls": ["https://example.com/y"] * (sync.MAX_CAPTURE_URLS + 1)}, token)[0], 400)

    def test_token_is_stored_hashed(self):
        token = self.there.store.new_phone_token()
        self.assertNotIn(token, (self.laptop / "sync.json").read_text(encoding="utf-8"))
        self.assertTrue(self.there.status()["phone"]["enabled"])


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

    def test_machine_kind_is_shared_when_pairing_and_remembered_offline(self):
        self.there.store.kind = "laptop"
        self.pair()
        self.assertEqual(self.home.store.peers()[self.there.store.id]["kind"], "laptop")
        self.assertEqual(self.home.machines()[self.there.store.id]["kind"], "computer")
        self.home.found.clear()
        self.assertEqual(self.home.machines()[self.there.store.id]["kind"], "laptop")

    def test_detected_kind_is_one_of_the_known_kinds(self):
        self.assertIn(sync.detect_kind(), ("laptop", "desktop", "computer"))

    def test_paired_machine_stays_listed_offline(self):
        self.pair()
        self.home.found.clear()
        listed = self.home.machines()[self.there.store.id]
        self.assertTrue(listed["paired"])
        self.assertFalse(listed["online"])
