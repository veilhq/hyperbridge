"""Tests for local-network share and fetch."""

import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core import db  # noqa: E402
from bridge.exchange import lan  # noqa: E402
from bridge.core import storage  # noqa: E402
from tests.exchange.test_transfer import TransferCase, use_library  # noqa: E402


class LanCase(TransferCase):
    """The share runs on server threads against the laptop folder; the main thread is the other machine."""

    def setUp(self):
        super().setUp()
        self.uids, _ = self.seed_laptop()
        main_thread = threading.current_thread()

        def folder():
            return self.main if threading.current_thread() is main_thread else self.laptop

        for target in (db, storage):
            patcher = mock.patch.object(target, "data_dir", folder)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.conn = use_library(str(self.main))
        self.addCleanup(self.conn.close)
        self.share = lan.Share()
        self.addCleanup(self.share.stop)
        self.address = f"127.0.0.1:{self.share.port}"


class FetchTests(LanCase):
    def test_fetch_brings_only_missing_entries(self):
        first = self.uids[0]
        self.conn.execute("INSERT INTO entries (uid, title, source_key, state, created_at, updated_at) VALUES (?, 'Mine', 'key0', 'captured', '', '')", (storage.new_uid(),))
        result = lan.fetch(self.conn, self.address, self.share.code)
        self.assertEqual(result["added"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertIsNone(self.conn.execute("SELECT id FROM entries WHERE uid = ?", (first,)).fetchone())
        row = self.conn.execute("SELECT id FROM entries WHERE uid = ?", (self.uids[1],)).fetchone()
        asset = self.conn.execute("SELECT path FROM assets WHERE entry_id = ?", (row["id"],)).fetchone()
        self.assertEqual((self.main / asset["path"]).read_bytes(), b"image-Second")

    def test_second_fetch_adds_nothing(self):
        lan.fetch(self.conn, self.address, self.share.code)
        again = lan.fetch(self.conn, self.address, self.share.code)
        self.assertEqual((again["added"], again["skipped"]), (0, 2))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 2)

    def test_wrong_code_is_refused(self):
        with self.assertRaises(lan.LanError):
            lan.fetch(self.conn, self.address, "000000" if self.share.code != "000000" else "111111")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)

    def test_share_closes_after_repeated_wrong_codes(self):
        for _ in range(lan.MAX_FAILURES):
            request = urllib.request.Request(f"http://{self.address}/manifest", headers={"X-Code": "bad"})
            with self.assertRaises(urllib.error.HTTPError):
                urllib.request.urlopen(request, timeout=5)
        self.share._stopped.wait(5)
        with self.assertRaises(lan.LanError):
            lan.fetch(self.conn, self.address, self.share.code)

    def test_stopped_share_cannot_be_reached(self):
        self.share.stop()
        with self.assertRaises(lan.LanError):
            lan.fetch(self.conn, self.address, self.share.code)


class AddressTests(unittest.TestCase):
    def test_parse_accepts_scheme_and_rejects_junk(self):
        self.assertEqual(lan._parse_address("http://192.168.1.5:8000/"), ("192.168.1.5", 8000))
        for bad in ("", "nohost", "1.2.3.4:", "1.2.3.4:99999"):
            with self.assertRaises(lan.LanError):
                lan._parse_address(bad)

    def test_public_addresses_are_refused(self):
        with self.assertRaises(lan.LanError):
            lan._require_private("8.8.8.8")
        lan._require_private("192.168.1.5")


if __name__ == "__main__":
    unittest.main()
