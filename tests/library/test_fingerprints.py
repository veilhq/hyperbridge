"""Tests for image fingerprints: hashing, near matches, backfill and the duplicate lookup."""

import hashlib
import io
import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hyperbridge  # noqa: E402
from bridge.library import fingerprints  # noqa: E402
from tests.library.test_library import LibraryOpsCase  # noqa: E402


def picture(seed, size=(240, 180), fmt="PNG", quality=95):
    """Return a smooth, textured test image built from a seeded grid of random greys."""
    from PIL import Image

    rng = random.Random(seed)
    grid = Image.new("L", (12, 9))
    grid.putdata([rng.randrange(256) for _ in range(12 * 9)])
    image = grid.resize(size, Image.Resampling.BICUBIC).convert("RGB")
    buffer = io.BytesIO()
    image.save(buffer, fmt, **({"quality": quality} if fmt == "JPEG" else {}))
    return buffer.getvalue()


def plain(color=(200, 30, 30)):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(buffer, "PNG")
    return buffer.getvalue()


class HashTests(unittest.TestCase):
    def test_a_resized_recompressed_copy_stays_near(self):
        original = fingerprints.difference_hash(picture(1))
        copy = fingerprints.difference_hash(picture(1, size=(120, 90), fmt="JPEG", quality=60))
        self.assertIsNotNone(original)
        self.assertLessEqual(fingerprints.distance(original, copy), fingerprints.NEAR_BITS)

    def test_different_pictures_are_far_apart(self):
        first = fingerprints.difference_hash(picture(1))
        for seed in range(2, 8):
            self.assertGreater(fingerprints.distance(first, fingerprints.difference_hash(picture(seed))), fingerprints.NEAR_BITS)

    def test_plain_or_unreadable_images_have_no_visual_hash(self):
        self.assertIsNone(fingerprints.difference_hash(plain()))
        self.assertIsNone(fingerprints.difference_hash(b"not an image"))

    def test_fingerprint_pairs_the_content_hash_with_the_visual_hash(self):
        body = picture(3)
        digest, visual = fingerprints.fingerprint(body)
        self.assertEqual(digest, hashlib.sha256(body).hexdigest())
        self.assertEqual(visual, fingerprints.difference_hash(body))
        self.assertTrue(-(1 << 63) <= visual < (1 << 63))

    def test_distance_handles_signed_values_and_missing_hashes(self):
        self.assertEqual(fingerprints.distance(-1, 0), 64)
        self.assertEqual(fingerprints.distance(5, 4), 1)
        self.assertIsNone(fingerprints.distance(None, 4))


class DuplicateTests(LibraryOpsCase):
    def store(self, title, body):
        entry_id = self.add_entry(title)
        self.add_asset(entry_id, data=body)
        return entry_id

    def test_backfill_fingerprints_originals_only_once(self):
        entry_id = self.store("A", picture(1))
        self.add_asset(entry_id, kind="thumbnail", data=picture(1, size=(60, 45)))
        self.assertEqual(fingerprints.backfill(self.conn), 1)
        self.assertEqual(fingerprints.backfill(self.conn), 0)
        row = self.conn.execute("SELECT sha256, dhash FROM assets WHERE kind = 'original'").fetchone()
        self.assertEqual(row["sha256"], hashlib.sha256(picture(1)).hexdigest())
        self.assertIsNotNone(row["dhash"])

    def test_exact_and_near_copies_are_flagged_both_ways(self):
        first = self.store("First", picture(1))
        exact = self.store("Exact", picture(1))
        near = self.store("Near", picture(1, size=(120, 90), fmt="JPEG", quality=60))
        other = self.store("Other", picture(2))
        fingerprints.backfill(self.conn)
        self.assertEqual(fingerprints.duplicates(self.conn, first), [{"id": exact, "title": "Exact"}, {"id": near, "title": "Near"}])
        self.assertEqual([item["id"] for item in fingerprints.duplicates(self.conn, near)], [first, exact])
        self.assertEqual(fingerprints.duplicates(self.conn, other), [])

    def test_plain_images_match_only_byte_for_byte(self):
        red = self.store("Red", plain())
        same = self.store("Same red", plain())
        blue = self.store("Blue", plain((30, 30, 200)))
        fingerprints.backfill(self.conn)
        self.assertEqual([item["id"] for item in fingerprints.duplicates(self.conn, red)], [same])
        self.assertEqual(fingerprints.duplicates(self.conn, blue), [])

    def test_an_entry_never_lists_itself(self):
        entry_id = self.store("Pair", picture(1))
        self.add_asset(entry_id, position=1, data=picture(1))
        fingerprints.backfill(self.conn)
        self.assertEqual(fingerprints.duplicates(self.conn, entry_id), [])

    def test_get_entry_carries_the_duplicates(self):
        first = self.store("First", picture(4))
        second = self.store("", picture(4))
        fingerprints.backfill(self.conn)
        entry = hyperbridge.HyperbridgeAPI().get_entry(first)
        self.assertEqual(entry["duplicates"], [{"id": second, "title": ""}])


if __name__ == "__main__":
    unittest.main()
