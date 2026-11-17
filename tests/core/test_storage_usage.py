"""Tests for the disk usage readout, per-machine preferences and downscaling large captures."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hyperbridge  # noqa: E402
from bridge.core import db, prefs, storage  # noqa: E402
from bridge.ingest import capture  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402
from tests.ingest.test_capture import png_bytes  # noqa: E402


def noisy_jpeg(width, height):
    """A JPEG that does not compress to nothing, so shrinking it saves bytes."""
    import io
    import random

    from PIL import Image

    rng = random.Random(3)
    image = Image.frombytes("RGB", (width, height), bytes(rng.getrandbits(8) for _ in range(width * height * 3)))
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


class PrefsTests(LibraryCase):
    def test_defaults_until_set_and_survive_reload(self):
        self.assertFalse(prefs.get("downscale_originals"))
        prefs.set("downscale_originals", True)
        self.assertTrue(prefs.load()["downscale_originals"])

    def test_unreadable_file_falls_back_to_defaults(self):
        (db.data_dir() / "preferences.json").write_text("not json", encoding="utf-8")
        self.assertEqual(prefs.load(), prefs.DEFAULTS)

    def test_unknown_keys_are_refused(self):
        with self.assertRaises(KeyError):
            prefs.set("nope", 1)

    def test_view_defaults_validate_choices_and_types(self):
        prefs.set("library_order", "title")
        prefs.set("library_columns", -2)
        prefs.set("sets_rail_collapsed", True)
        self.assertEqual(prefs.view_defaults()["library_order"], "title")
        self.assertEqual(prefs.view_defaults()["library_columns"], -2)
        self.assertTrue(prefs.view_defaults()["sets_rail_collapsed"])
        for key, value in (("library_order", "sideways"), ("library_columns", 9), ("library_columns", "1"), ("lightbox_fit", 0)):
            with self.assertRaises(ValueError):
                prefs.set(key, value)
        self.assertEqual(prefs.get("library_order"), "title")

    def test_disallowed_saved_values_fall_back_per_key(self):
        (db.data_dir() / "preferences.json").write_text(
            '{"library_order": "sideways", "library_group": "year", "library_columns": true}', encoding="utf-8")
        values = prefs.load()
        self.assertEqual(values["library_order"], prefs.DEFAULTS["library_order"])
        self.assertEqual(values["library_group"], "year")
        self.assertEqual(values["library_columns"], 0)

    def test_view_defaults_leave_out_storage_preferences(self):
        self.assertNotIn("downscale_originals", prefs.view_defaults())
        self.assertEqual(set(prefs.view_defaults()), set(prefs.VIEW_DEFAULTS))


class DefaultsApiTests(LibraryCase):
    def test_set_default_round_trips_and_reports_errors(self):
        api = hyperbridge.HyperbridgeAPI()
        self.assertEqual(api.get_defaults()["sets_sort"], "recent")
        result = api.set_default("sets_sort", "size")
        self.assertTrue(result["ok"])
        self.assertEqual(result["defaults"]["sets_sort"], "size")
        self.assertFalse(api.set_default("sets_sort", "shape")["ok"])
        self.assertFalse(api.set_default("downscale_originals", True)["ok"])
        self.assertEqual(api.get_defaults()["sets_sort"], "size")

    def test_launch_html_carries_the_saved_defaults(self):
        prefs.set("lightbox_fit", "fit")
        html = hyperbridge.with_defaults(hyperbridge.HTML)
        self.assertNotIn(hyperbridge.DEFAULTS_SLOT, html)
        self.assertIn('"lightbox_fit": "fit"', html)


class UsageTests(LibraryCase):
    def test_usage_sums_assets_by_kind_and_the_database(self):
        capture.add_image(self.conn, png_bytes(300, 200), "")
        self.conn.commit()
        usage = storage.usage(self.conn)
        stored = dict(self.conn.execute("SELECT kind, SUM(bytes) FROM assets GROUP BY kind").fetchall())
        self.assertEqual((usage["originals"], usage["thumbnails"]), (stored["original"], stored["thumbnail"]))
        self.assertGreater(usage["database"], 0)
        self.assertEqual(usage["total"], usage["originals"] + usage["thumbnails"] + usage["screenshots"] + usage["database"])

    def test_api_reports_usage_and_toggles_downscale(self):
        api = hyperbridge.HyperbridgeAPI()
        self.assertFalse(api.get_storage()["downscale"])
        self.assertTrue(api.set_downscale(True)["downscale"])
        self.assertTrue(api.get_storage()["downscale"])


class DownscaleTests(LibraryCase):
    def setUp(self):
        super().setUp()
        self.edge = capture.DOWNSCALE_EDGE
        capture.DOWNSCALE_EDGE = 64
        self.addCleanup(setattr, capture, "DOWNSCALE_EDGE", self.edge)

    def original(self, entry_id):
        return self.conn.execute("SELECT width, height, bytes FROM assets WHERE entry_id = ? AND kind = 'original'",
                                 (entry_id,)).fetchone()

    def test_large_captures_keep_full_size_until_switched_on(self):
        body = noisy_jpeg(200, 100)
        kept = self.original(capture.add_image(self.conn, body, "")["entry_id"])
        self.assertEqual((kept["width"], kept["height"], kept["bytes"]), (200, 100, len(body)))
        prefs.set("downscale_originals", True)
        shrunk = self.original(capture.add_image(self.conn, body, "")["entry_id"])
        self.assertEqual((shrunk["width"], shrunk["height"]), (64, 32))
        self.assertLess(shrunk["bytes"], len(body))

    def test_small_and_animated_images_are_left_alone(self):
        prefs.set("downscale_originals", True)
        small = png_bytes(40, 20)
        self.assertEqual(capture._downscale(small, "PNG", 40, 20), (small, 40, 20))
        gif = png_bytes(200, 100, fmt="GIF")
        self.assertEqual(capture._downscale(gif, "GIF", 200, 100), (gif, 200, 100))


if __name__ == "__main__":
    unittest.main()
