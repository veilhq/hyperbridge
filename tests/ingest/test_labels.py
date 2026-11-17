"""Tests for AI-generation labels on discovery feed images."""

import io
import struct
import sys
import unittest
import zlib
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import feed  # noqa: E402
from bridge.ingest import labels  # noqa: E402
from bridge.ingest import similar  # noqa: E402
from tests.ingest.test_similar import SimilarCase  # noqa: E402

AI_TYPE = b"http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"
CAMERA_TYPE = b"http://cv.iptc.org/newscodes/digitalsourcetype/digitalCapture"


def png(*text_chunks) -> bytes:
    """Build a real one-pixel PNG with the given (keyword, value) text chunks before its pixels."""
    from PIL import Image

    plain = io.BytesIO()
    Image.new("RGB", (1, 1)).save(plain, "PNG")
    body = plain.getvalue()
    extra = b""
    for keyword, value in text_chunks:
        data = keyword + b"\x00" + value
        extra += struct.pack(">I", len(data)) + b"tEXt" + data + struct.pack(">I", zlib.crc32(b"tEXt" + data))
    header_end = 8 + 25
    return body[:header_end] + extra + body[header_end:]


def jpeg_with_xmp(source_type, c2pa=False) -> bytes:
    """Return JPEG-like bytes carrying an XMP packet, and a C2PA manifest box when asked."""
    xmp = b'<x:xmpmeta xmlns:x="adobe:ns:meta/"><Iptc4xmpExt:DigitalSourceType>' + source_type + b"</Iptc4xmpExt:DigitalSourceType></x:xmpmeta>"
    manifest = b"jumb\x00\x00c2pa\x00" + b'{"digitalSourceType":"' + source_type + b'"}' if c2pa else b""
    return b"\xff\xd8\xff\xe1" + xmp + manifest + b"\xff\xd9"


class LabelTests(unittest.TestCase):
    def test_iptc_ai_source_type(self):
        self.assertEqual(labels.ai_label(jpeg_with_xmp(AI_TYPE)), labels.IPTC)

    def test_composite_with_ai_counts(self):
        composite = b"http://cv.iptc.org/newscodes/digitalsourcetype/compositeWithTrainedAlgorithmicMedia"
        self.assertEqual(labels.ai_label(jpeg_with_xmp(composite)), labels.IPTC)

    def test_c2pa_manifest(self):
        self.assertEqual(labels.ai_label(jpeg_with_xmp(AI_TYPE, c2pa=True)), labels.C2PA)

    def test_camera_source_type_is_unlabeled(self):
        self.assertEqual(labels.ai_label(jpeg_with_xmp(CAMERA_TYPE)), "")

    def test_generator_settings_in_png(self):
        self.assertEqual(labels.ai_label(png((b"parameters", b"a cat, Steps: 20, Sampler: Euler"))), labels.GENERATOR)
        self.assertEqual(labels.ai_label(png((b"workflow", b"{}"))), labels.GENERATOR)
        self.assertEqual(labels.ai_label(png((b"Software", b"NovelAI"))), labels.GENERATOR)

    def test_ordinary_png_text_is_unlabeled(self):
        self.assertEqual(labels.ai_label(png((b"Software", b"GIMP 2.10"), (b"Title", b"Poster"))), "")

    def test_truncated_png_reads_what_it_has(self):
        body = png((b"Title", b"x" * 100), (b"parameters", b"a cat"))
        self.assertEqual(labels.ai_label(body[:60]), "")
        self.assertEqual(labels.ai_label(body), labels.GENERATOR)

    def test_empty_bytes(self):
        self.assertEqual(labels.ai_label(b""), "")


class CheckTests(SimilarCase):
    def fetcher(self, bodies):
        calls = []

        def fetch(url, **kwargs):
            calls.append((url, kwargs))
            if url not in bodies:
                raise OSError("unreachable")
            return SimpleNamespace(body=bodies[url])
        return fetch, calls

    def test_records_labels_and_marks_every_image_checked(self):
        labeled = self.feed_item("https://x/ai.jpg")
        plain = self.feed_item("https://x/plain.jpg")
        down = self.feed_item("https://x/down.jpg")
        fetch, calls = self.fetcher({"https://x/ai.jpg": jpeg_with_xmp(AI_TYPE), "https://x/plain.jpg": b"\xff\xd8\xff\xd9"})
        self.assertEqual(labels.check_new(self.conn, fetch), 1)
        rows = {row["id"]: (row["ai_label"], row["ai_checked"]) for row in self.conn.execute("SELECT id, ai_label, ai_checked FROM feed_items")}
        self.assertEqual(rows, {labeled: (labels.IPTC, 1), plain: ("", 1), down: ("", 1)})
        self.assertTrue(all(kwargs["partial"] and kwargs["max_bytes"] == labels.HEAD_BYTES for _, kwargs in calls))

    def test_checked_and_handled_images_are_not_fetched_again(self):
        self.feed_item("https://x/a.jpg")
        self.feed_item("https://x/b.jpg", state="dismissed")
        fetch, calls = self.fetcher({"https://x/a.jpg": b""})
        labels.check_new(self.conn, fetch)
        labels.check_new(self.conn, fetch)
        self.assertEqual([url for url, _ in calls], ["https://x/a.jpg"])


class FeedListTests(SimilarCase):
    def setUp(self):
        super().setUp()
        self.shown = self.feed_item("https://x/shown.jpg", tags=["concrete"])
        self.flagged = self.feed_item("https://x/flagged.jpg", tags=["concrete"])
        self.conn.execute("UPDATE feed_items SET ai_label = ?, ai_checked = 1 WHERE id = ?", (labels.C2PA, self.flagged))

    def test_discover_holds_back_labeled_images(self):
        result = feed.list_items(self.conn)
        self.assertEqual(([item["id"] for item in result["items"]], result["total"], result["flagged"]), ([self.shown], 1, 1))

    def test_discover_shows_labeled_images_with_their_reason_when_asked(self):
        result = feed.list_items(self.conn, show_flagged=True)
        self.assertEqual([(item["id"], item["ai_label"]) for item in result["items"]], [(self.shown, ""), (self.flagged, labels.C2PA)])
        self.assertEqual((result["total"], result["flagged"]), (2, 1))

    def test_find_similar_holds_back_labeled_matches(self):
        set_id = self.make_set()
        self.member(set_id, tags=["concrete"])
        result = similar.list_items(self.conn, set_id)
        self.assertEqual(([item["id"] for item in result["items"]], result["flagged"]), ([self.shown], 1))
        shown_all = similar.list_items(self.conn, set_id, show_flagged=True)
        self.assertEqual(sorted(item["id"] for item in shown_all["items"]), [self.shown, self.flagged])


if __name__ == "__main__":
    unittest.main()
