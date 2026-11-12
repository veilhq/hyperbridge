"""Tests for URL normalizing, queueing, metadata extraction and the capture pipeline."""

import io
import json
import sys
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import capture  # noqa: E402
from bridge.core import db  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402

PAGE_URL = "https://example.com/post"
IMAGE_URL = "https://example.com/cover.png"

SAMPLE_HTML = b"""<html><head>
<title>Fallback title</title>
<meta property="og:title" content="OG Title">
<meta property="og:description" content="OG description">
<meta property="og:site_name" content="Example Press">
<meta property="og:type" content="article">
<meta property="og:image" content="/cover.png">
<meta name="author" content="Ada Lovelace">
<meta property="article:published_time" content="2021-05-04T10:00:00Z">
</head><body></body></html>"""


def png_bytes(width=64, height=32, mode="RGB", fmt="PNG"):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new(mode, (width, height), "red").save(buffer, fmt)
    return buffer.getvalue()


def reply(url, body, content_type, status=200):
    return SimpleNamespace(final_url=url, status=status, content_type=content_type, body=body)


class FakeFetcher:
    """Serves canned responses by URL and records the requests."""

    def __init__(self, responses):
        self.responses = responses
        self.calls = []

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        value = self.responses[url]
        if isinstance(value, Exception):
            raise value
        return value


class NormalizeUrlTests(unittest.TestCase):
    def test_lowercases_scheme_and_host_and_strips_fragment(self):
        self.assertEqual(capture.normalize_url("HTTPS://Example.COM/Path#frag"), "https://example.com/Path")

    def test_strips_default_ports_only(self):
        self.assertEqual(capture.normalize_url("http://example.com:80/a"), "http://example.com/a")
        self.assertEqual(capture.normalize_url("https://example.com:443/a"), "https://example.com/a")
        self.assertEqual(capture.normalize_url("https://example.com:8443/a"), "https://example.com:8443/a")

    def test_drops_tracking_params_and_sorts_the_rest(self):
        url = "https://example.com/a?b=2&utm_source=x&a=1&fbclid=z&gclid=q&ref=t"
        self.assertEqual(capture.normalize_url(url), "https://example.com/a?a=1&b=2")

    def test_trailing_slash_stripped_except_root(self):
        self.assertEqual(capture.normalize_url("https://example.com/a/b/"), "https://example.com/a/b")
        self.assertEqual(capture.normalize_url("https://example.com"), "https://example.com/")
        self.assertEqual(capture.normalize_url("https://example.com/"), "https://example.com/")

    def test_rejects_non_http(self):
        for bad in ("ftp://example.com/a", "javascript:alert(1)", "file:///etc/passwd", "example.com", ""):
            with self.assertRaises(ValueError, msg=bad):
                capture.normalize_url(bad)


class AddLinkTests(LibraryCase):
    def test_inserts_pending_entry_and_queues_job(self):
        result = capture.add_link(self.conn, "https://Example.com/post/?utm_source=a")
        self.assertTrue(result["created"])
        self.assertFalse(result["already_captured"])
        entry = self.conn.execute("SELECT * FROM entries WHERE id = ?", (result["entry_id"],)).fetchone()
        self.assertEqual(entry["state"], "pending")
        self.assertEqual(entry["source_key"], "https://example.com/post")
        self.assertEqual(entry["domain"], "example.com")
        self.assertEqual(len(entry["uid"]), 32)
        job = self.conn.execute("SELECT * FROM jobs").fetchone()
        self.assertEqual((job["kind"], job["state"], job["entry_id"]), ("capture", "queued", entry["id"]))

    def test_duplicate_returns_existing_entry_without_new_job(self):
        first = capture.add_link(self.conn, "https://example.com/post")
        second = capture.add_link(self.conn, "https://EXAMPLE.com/post/#top")
        self.assertEqual(second["entry_id"], first["entry_id"])
        self.assertTrue(second["already_captured"])
        self.assertFalse(second["created"])
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0], 1)

    def test_invalid_url_raises(self):
        with self.assertRaises(ValueError):
            capture.add_link(self.conn, "ftp://example.com/x")


class ExtractMetadataTests(unittest.TestCase):
    def test_open_graph_fields(self):
        meta = capture.extract_metadata(SAMPLE_HTML, PAGE_URL)
        self.assertEqual(meta["title"], "OG Title")
        self.assertEqual(meta["description"], "OG description")
        self.assertEqual(meta["publisher"], "Example Press")
        self.assertEqual(meta["type"], "article")
        self.assertEqual(meta["creator"], "Ada Lovelace")
        self.assertEqual(meta["year"], "2021")
        self.assertEqual(meta["image_url"], "https://example.com/cover.png")

    def test_long_title_is_cut_at_a_word_boundary(self):
        long_title = "Spring catalogue " * 20
        html = ('<html><head><meta property="og:title" content="%s"></head></html>' % long_title).encode()
        title = capture.extract_metadata(html, PAGE_URL)["title"]
        self.assertLessEqual(len(title), capture.MAX_TITLE)
        self.assertTrue(title.endswith("..."))
        self.assertIn(title[:-3].split()[-1], ("Spring", "catalogue"))

    def test_short_title_is_untouched(self):
        self.assertEqual(capture.shorten_title("Short"), "Short")

    def test_json_ld_fills_gaps(self):
        data = {
            "@context": "https://schema.org",
            "@graph": [{
                "@type": "Article", "headline": "LD Headline", "description": "LD text",
                "author": {"@type": "Person", "name": "Grace Hopper"},
                "publisher": {"@type": "Organization", "name": "LD Pub"},
                "datePublished": "1999-12-31", "image": ["https://cdn.example.com/x.jpg"],
            }],
        }
        html = f'<script type="application/ld+json">{json.dumps(data)}</script>'.encode()
        meta = capture.extract_metadata(html, PAGE_URL)
        self.assertEqual(meta["title"], "LD Headline")
        self.assertEqual(meta["creator"], "Grace Hopper")
        self.assertEqual(meta["publisher"], "LD Pub")
        self.assertEqual(meta["type"], "Article")
        self.assertEqual(meta["year"], "1999")
        self.assertEqual(meta["image_url"], "https://cdn.example.com/x.jpg")

    def test_falls_back_to_title_tag_and_meta_description(self):
        html = b"<html><head><title>  Plain\n title </title><meta name='description' content='d'></head></html>"
        meta = capture.extract_metadata(html, PAGE_URL)
        self.assertEqual(meta["title"], "Plain title")
        self.assertEqual(meta["description"], "d")
        self.assertEqual(meta["image_url"], "")

    def test_tolerates_bad_encoding_bad_json_and_huge_input(self):
        html = b"<title>Caf\xe9 \xff</title><script type='application/ld+json'>{not json</script>"
        self.assertIn("Caf", capture.extract_metadata(html, PAGE_URL)["title"])
        huge = b"<title>Big</title>" + b"<p>x</p>" * 1_000_000
        self.assertEqual(capture.extract_metadata(huge, PAGE_URL)["title"], "Big")
        self.assertEqual(capture.extract_metadata(b"", PAGE_URL)["title"], "")

    def test_non_http_image_is_dropped(self):
        html = b"<meta property='og:image' content='data:image/png;base64,AAAA'>"
        self.assertEqual(capture.extract_metadata(html, PAGE_URL)["image_url"], "")


class RunCaptureTests(LibraryCase):
    def queue(self, url=PAGE_URL):
        result = capture.add_link(self.conn, url)
        job = self.conn.execute("SELECT id FROM jobs WHERE entry_id = ?", (result["entry_id"],)).fetchone()
        return result["entry_id"], job["id"]

    def entry(self, entry_id):
        return self.conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()

    def assets(self, entry_id):
        rows = self.conn.execute("SELECT * FROM assets WHERE entry_id = ?", (entry_id,)).fetchall()
        return {row["kind"]: row for row in rows}

    def test_page_capture_stores_metadata_and_assets(self):
        entry_id, job_id = self.queue()
        fetcher = FakeFetcher({
            "https://example.com/post": reply(PAGE_URL, SAMPLE_HTML, "text/html"),
            IMAGE_URL: reply(IMAGE_URL, png_bytes(1200, 600), "image/png"),
        })
        capture.run_capture(self.conn, job_id, fetcher)
        entry = self.entry(entry_id)
        self.assertEqual((entry["state"], entry["title"], entry["creator"]), ("captured", "OG Title", "Ada Lovelace"))
        assets = self.assets(entry_id)
        self.assertEqual(set(assets), {"original", "thumbnail"})
        self.assertEqual((assets["original"]["width"], assets["original"]["height"]), (1200, 600))
        self.assertEqual(max(assets["thumbnail"]["width"], assets["thumbnail"]["height"]), capture.THUMB_EDGE)
        for row in assets.values():
            self.assertTrue(row["path"].startswith(f"assets/{entry['uid'][:2]}/{entry['uid']}/"))
            self.assertTrue((Path(db.data_dir()) / row["path"]).is_file())
            self.assertGreater(row["bytes"], 0)
        job = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual((job["state"], job["attempts"], job["error"]), ("done", 1, ""))

    def test_page_with_several_images_stores_each_and_skips_bad_ones(self):
        entry_id, job_id = self.queue()
        page = (
            b'<meta property="og:image" content="https://cdn.example/1.png">'
            b'<meta property="og:image" content="https://cdn.example/2.png">'
            b'<meta property="og:image" content="https://cdn.example/bad.png">'
            b'<meta property="og:image" content="https://cdn.example/3.png">'
        )
        fetcher = FakeFetcher({
            "https://example.com/post": reply(PAGE_URL, page, "text/html"),
            "https://cdn.example/1.png": reply("https://cdn.example/1.png", png_bytes(100, 50), "image/png"),
            "https://cdn.example/2.png": reply("https://cdn.example/2.png", png_bytes(90, 60), "image/png"),
            "https://cdn.example/bad.png": reply("https://cdn.example/bad.png", b"nope", "image/png"),
            "https://cdn.example/3.png": reply("https://cdn.example/3.png", png_bytes(80, 80), "image/png"),
        })
        capture.run_capture(self.conn, job_id, fetcher)
        rows = self.conn.execute(
            "SELECT position, kind FROM assets WHERE entry_id = ? ORDER BY position, kind", (entry_id,)
        ).fetchall()
        self.assertEqual(
            [(row["position"], row["kind"]) for row in rows],
            [(0, "original"), (0, "thumbnail"), (1, "original"), (2, "original")],
        )
        self.assertEqual(self.entry(entry_id)["state"], "captured")

    def test_direct_image_url_is_captured_as_the_image(self):
        url = "https://example.com/art/photo.png"
        entry_id, job_id = self.queue(url)
        fetcher = FakeFetcher({url: reply(url, png_bytes(100, 50), "image/png")})
        capture.run_capture(self.conn, job_id, fetcher)
        self.assertEqual(fetcher.calls, [url])
        self.assertEqual(self.entry(entry_id)["state"], "captured")
        self.assertEqual(self.entry(entry_id)["title"], "photo")
        self.assertEqual(set(self.assets(entry_id)), {"original", "thumbnail"})

    def test_non_image_body_is_rejected(self):
        url = "https://example.com/fake.png"
        entry_id, job_id = self.queue(url)
        fetcher = FakeFetcher({url: reply(url, b"<html>not an image</html>", "image/png")})
        capture.run_capture(self.conn, job_id, fetcher)
        self.assertEqual(self.entry(entry_id)["state"], "failed")
        self.assertEqual(self.assets(entry_id), {})
        job = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual(job["state"], "failed")
        self.assertIn("not a usable image", job["error"])

    def test_preview_image_that_is_not_an_image_fails(self):
        entry_id, job_id = self.queue()
        fetcher = FakeFetcher({
            "https://example.com/post": reply(PAGE_URL, SAMPLE_HTML, "text/html"),
            IMAGE_URL: reply(IMAGE_URL, b"<html></html>", "text/html"),
        })
        capture.run_capture(self.conn, job_id, fetcher)
        self.assertEqual(self.entry(entry_id)["state"], "failed")

    def test_oversized_pixel_count_is_rejected(self):
        url = "https://example.com/huge.png"
        entry_id, job_id = self.queue(url)
        fetcher = FakeFetcher({url: reply(url, png_bytes(200, 200), "image/png")})
        original = capture.MAX_PIXELS
        capture.MAX_PIXELS = 1000
        self.addCleanup(setattr, capture, "MAX_PIXELS", original)
        capture.run_capture(self.conn, job_id, fetcher)
        self.assertEqual(self.entry(entry_id)["state"], "failed")
        self.assertEqual(self.assets(entry_id), {})
        error = self.conn.execute("SELECT error FROM jobs WHERE id = ?", (job_id,)).fetchone()[0]
        self.assertIn("pixel limit", error)

    def test_manual_fields_are_not_overwritten(self):
        entry_id, job_id = self.queue()
        self.conn.execute(
            "UPDATE entries SET title = 'My title', manual_fields = ? WHERE id = ?",
            (json.dumps(["title"]), entry_id),
        )
        fetcher = FakeFetcher({
            "https://example.com/post": reply(PAGE_URL, SAMPLE_HTML.replace(b"/cover.png", b""), "text/html"),
        })
        capture.run_capture(self.conn, job_id, fetcher)
        entry = self.entry(entry_id)
        self.assertEqual(entry["title"], "My title")
        self.assertEqual(entry["description"], "OG description")
        self.assertEqual(entry["state"], "captured")

    def test_fetch_error_marks_entry_and_job_failed(self):
        entry_id, job_id = self.queue()
        fetcher = FakeFetcher({"https://example.com/post": RuntimeError("blocked address")})
        capture.run_capture(self.conn, job_id, fetcher)
        self.assertEqual(self.entry(entry_id)["state"], "failed")
        job = self.conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        self.assertEqual(job["state"], "failed")
        self.assertIn("blocked address", job["error"])


class ScreenshotFallbackTests(RunCaptureTests):
    NO_IMAGE_HTML = b"<html><head><title>Plain page</title></head><body></body></html>"

    def run_page(self, screenshotter):
        entry_id, job_id = self.queue()
        fetcher = FakeFetcher({PAGE_URL: reply(PAGE_URL, self.NO_IMAGE_HTML, "text/html")})
        capture.run_capture(self.conn, job_id, fetcher, screenshotter)
        return entry_id

    def test_page_without_image_uses_the_screenshot(self):
        calls = []

        def shoot(url):
            calls.append(url)
            return png_bytes(800, 1000)

        entry_id = self.run_page(shoot)
        self.assertEqual(calls, [PAGE_URL])
        self.assertEqual(set(self.assets(entry_id)), {"original", "thumbnail"})
        self.assertEqual(self.entry(entry_id)["state"], "captured")

    def test_failed_screenshot_leaves_a_captured_entry_without_image(self):
        def shoot(url):
            raise RuntimeError("no browser")

        entry_id = self.run_page(shoot)
        self.assertEqual(self.assets(entry_id), {})
        self.assertEqual(self.entry(entry_id)["state"], "captured")

    def test_page_with_a_preview_image_is_not_screenshotted(self):
        entry_id, job_id = self.queue()
        fetcher = FakeFetcher({
            PAGE_URL: reply(PAGE_URL, SAMPLE_HTML, "text/html"),
            IMAGE_URL: reply(IMAGE_URL, png_bytes(), "image/png"),
        })

        def shoot(url):
            raise AssertionError("should not be called")

        capture.run_capture(self.conn, job_id, fetcher, shoot)
        self.assertEqual(self.entry(entry_id)["state"], "captured")


class AddImageTests(LibraryCase):
    def test_pasted_bytes_become_a_captured_entry_with_assets(self):
        result = capture.add_image(self.conn, png_bytes(300, 200), "")
        entry = self.conn.execute("SELECT * FROM entries WHERE id = ?", (result["entry_id"],)).fetchone()
        self.assertEqual((entry["state"], entry["title"], entry["source_key"]), ("captured", "", None))
        kinds = {row[0] for row in self.conn.execute("SELECT kind FROM assets WHERE entry_id = ?", (entry["id"],))}
        self.assertEqual(kinds, {"original", "thumbnail"})

    def test_type_is_the_standard_mime_type(self):
        for fmt, expected in (("PNG", "image/png"), ("JPEG", "image/jpeg"), ("GIF", "image/gif")):
            result = capture.add_image(self.conn, png_bytes(fmt=fmt))
            row = self.conn.execute("SELECT type FROM entries WHERE id = ?", (result["entry_id"],)).fetchone()
            self.assertEqual(row[0], expected)

    def test_exif_artist_copyright_and_year_fill_the_fields(self):
        from PIL import Image

        image = Image.new("RGB", (20, 20), "red")
        exif = Image.Exif()
        exif[0x013B] = "Ada Lovelace"
        exif[0x8298] = "Analytical Press"
        exif[0x0132] = "2019:06:01 10:00:00"
        buffer = io.BytesIO()
        image.save(buffer, "JPEG", exif=exif)
        result = capture.add_image(self.conn, buffer.getvalue(), "photo.jpg")
        row = self.conn.execute("SELECT * FROM entries WHERE id = ?", (result["entry_id"],)).fetchone()
        self.assertEqual((row["creator"], row["publisher"], row["year"]), ("Ada Lovelace", "Analytical Press", "2019"))

    def test_png_text_chunks_fill_the_fields(self):
        from PIL import Image, PngImagePlugin

        meta = PngImagePlugin.PngInfo()
        meta.add_text("Author", "Grace")
        meta.add_text("Title", "Compiler")
        buffer = io.BytesIO()
        Image.new("RGB", (20, 20)).save(buffer, "PNG", pnginfo=meta)
        result = capture.add_image(self.conn, buffer.getvalue(), "x.png")
        row = self.conn.execute("SELECT * FROM entries WHERE id = ?", (result["entry_id"],)).fetchone()
        self.assertEqual((row["creator"], row["title"]), ("Grace", "Compiler"))

    def test_earlier_img_prefix_is_rewritten(self):
        self.conn.execute(
            "INSERT INTO entries (uid, type, state, created_at, updated_at) VALUES ('u1', 'img/png', 'captured', 'x', 'x')"
        )
        capture.fix_image_types(self.conn)
        self.assertEqual(self.conn.execute("SELECT type FROM entries").fetchone()[0], "image/png")

    def test_file_name_becomes_the_title(self):
        result = capture.add_image(self.conn, png_bytes(), "my_cool-shot.png")
        title = self.conn.execute("SELECT title FROM entries WHERE id = ?", (result["entry_id"],)).fetchone()[0]
        self.assertEqual(title, "my cool shot")

    def test_random_looking_file_name_leaves_the_title_empty(self):
        result = capture.add_image(self.conn, png_bytes(), "original_Ab3xK9qLm2.png")
        title = self.conn.execute("SELECT title FROM entries WHERE id = ?", (result["entry_id"],)).fetchone()[0]
        self.assertEqual(title, "")

    def test_readable_name_keeps_words_and_drops_noise(self):
        self.assertEqual(capture.readable_name("sunset-over-the-bay.png"), "sunset over the bay")
        self.assertEqual(capture.readable_name("original_Ab3xK9qLm2.jpg"), "")
        self.assertEqual(capture.readable_name("IMG_20240101_123456.jpg"), "")
        self.assertEqual(capture.readable_name("harbor%20at%20dawn_8f3a9c2e1b.webp"), "harbor at dawn")

    def test_fix_domains_points_entries_at_their_source_page(self):
        self.conn.execute(
            "INSERT INTO entries (uid, source_url, source_key, domain, state, created_at, updated_at)"
            " VALUES ('u1', 'https://www.are.na/block/1', 'https://d1.cloudfront.net/a.jpg', 'd1.cloudfront.net', 'captured', 'x', 'x')"
        )
        capture.fix_domains(self.conn)
        self.assertEqual(self.conn.execute("SELECT domain FROM entries").fetchone()[0], "are.na")

    def test_fix_file_name_titles_cleans_only_file_names(self):
        rows = [("a", "original_Ab3xK9qLm2.jpg", "[]"), ("b", "sunset-over-the-bay.png", "[]"),
                ("c", "Plain page title", "[]"), ("d", "keep_me_8f3a9c2e1b.jpg", '["title"]')]
        for uid, title, manual in rows:
            self.conn.execute("INSERT INTO entries (uid, title, manual_fields, state, created_at, updated_at) VALUES (?, ?, ?, 'captured', 'x', 'x')", (uid, title, manual))
        capture.fix_file_name_titles(self.conn)
        titles = dict(self.conn.execute("SELECT uid, title FROM entries").fetchall())
        self.assertEqual(titles, {"a": "", "b": "sunset over the bay", "c": "Plain page title", "d": "keep_me_8f3a9c2e1b.jpg"})

    def test_source_domain_drops_www(self):
        self.assertEqual(capture.source_domain("https://WWW.Cosmos.so/e/1"), "cosmos.so")
        self.assertEqual(capture.source_domain(""), "")

    def test_non_image_bytes_are_rejected_and_nothing_is_created(self):
        with self.assertRaises(capture.CaptureError):
            capture.add_image(self.conn, b"not an image", "x.png")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM entries").fetchone()[0], 0)

    def test_dropped_file_is_read_from_disk(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "drop.png"
            path.write_bytes(png_bytes())
            self.assertTrue(capture.add_image_file(self.conn, path)["entry_id"])

    def test_dropped_non_image_is_rejected_by_extension(self):
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "notes.log"
            path.write_bytes(png_bytes())
            with self.assertRaises(capture.CaptureError):
                capture.add_image_file(self.conn, path)


class ClaimTests(LibraryCase):
    def test_claim_marks_running_and_counts_attempt(self):
        capture.add_link(self.conn, "https://example.com/a")
        job = capture.claim_next_job(self.conn)
        self.assertEqual((job["state"], job["attempts"]), ("running", 1))
        self.assertIsNone(capture.claim_next_job(self.conn))

    def test_two_connections_cannot_claim_the_same_job(self):
        capture.add_link(self.conn, "https://example.com/a")
        results = []
        barrier = threading.Barrier(2)

        def claim():
            conn = db.connect()
            try:
                barrier.wait()
                results.append(capture.claim_next_job(conn))
            finally:
                conn.close()

        threads = [threading.Thread(target=claim) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len([row for row in results if row is not None]), 1)
        self.assertEqual(len(results), 2)


class WorkerTests(LibraryCase):
    def test_worker_processes_queued_and_interrupted_jobs(self):
        url = "https://example.com/art/photo.png"
        result = capture.add_link(self.conn, url)
        self.conn.execute("UPDATE jobs SET state = 'running'")
        fetcher = FakeFetcher({url: reply(url, png_bytes(40, 40), "image/png")})
        changed = threading.Event()
        worker = capture.Worker(fetcher=fetcher, on_change=changed.set, poll_interval=0.05)
        worker.start()
        self.addCleanup(worker.join, 5)
        self.addCleanup(worker.stop)
        self.assertTrue(changed.wait(10))
        deadline = time.time() + 5
        state = ""
        while time.time() < deadline and state != "captured":
            state = self.conn.execute("SELECT state FROM entries WHERE id = ?", (result["entry_id"],)).fetchone()[0]
            time.sleep(0.05)
        self.assertEqual(state, "captured")
        self.assertEqual(self.conn.execute("SELECT state FROM jobs").fetchone()[0], "done")


if __name__ == "__main__":
    unittest.main()


class InstagramTests(unittest.TestCase):
    @staticmethod
    def _embed(nodes):
        import json as _json
        media = {"shortcode": "ABC", "display_url": nodes[0]["display_url"],
                 "edge_sidecar_to_children": {"edges": [{"node": node} for node in nodes]}}
        inner = _json.dumps({"gql_data": {"shortcode_media": media}})
        return ('<script>{"contextJSON":' + _json.dumps(inner) + "}</script>").encode()

    def test_embed_url_covers_post_forms_and_ignores_other_hosts(self):
        self.assertEqual(
            capture.instagram_embed_url("https://www.instagram.com/user/p/ABC123/?hl=en"),
            "https://www.instagram.com/p/ABC123/embed/",
        )
        self.assertEqual(
            capture.instagram_embed_url("https://instagram.com/reel/XyZ_-1/"),
            "https://www.instagram.com/reel/XyZ_-1/embed/",
        )
        self.assertEqual(capture.instagram_embed_url("https://instagram.com/user/"), "")
        self.assertEqual(capture.instagram_embed_url("https://example.com/p/ABC/"), "")

    def test_media_lists_carousel_images_in_order_with_video_poster_frames(self):
        nodes = [
            {"display_url": "https://cdn.example/1.jpg", "is_video": False},
            {"display_url": "https://cdn.example/2.jpg", "is_video": True},
            {"display_url": "https://cdn.example/3.jpg", "is_video": False},
        ]
        self.assertEqual(
            capture.instagram_media(self._embed(nodes)),
            ["https://cdn.example/1.jpg", "https://cdn.example/2.jpg", "https://cdn.example/3.jpg"],
        )

    def test_media_is_empty_without_embedded_data(self):
        self.assertEqual(capture.instagram_media(b"<html></html>"), [])
        self.assertEqual(capture.instagram_media(b'{"contextJSON":"not json"}'), [])

    def test_media_falls_back_to_the_embed_page_image_when_post_data_is_null(self):
        page = (b'<img class="EmbeddedMediaImage" alt="post" src="https://cdn.example/full.jpg?a=1&amp;b=2">'
                b'<script>{"contextJSON":null}</script>')
        self.assertEqual(capture.instagram_media(page), ["https://cdn.example/full.jpg?a=1&b=2"])


class KeepDetailsTests(LibraryCase):
    def test_title_and_creator_from_a_discovery_card_survive_capture(self):
        url = "https://example.com/files/IMG_8841.png"
        added = capture.add_link(self.conn, url)
        capture.keep_details(self.conn, added["entry_id"], "Study in red", "Ada")
        job = self.conn.execute("SELECT id FROM jobs WHERE entry_id = ?", (added["entry_id"],)).fetchone()
        fetcher = FakeFetcher({url: reply(url, png_bytes(300, 200), "image/png")})
        capture.run_capture(self.conn, job["id"], fetcher)
        row = self.conn.execute("SELECT title, creator, manual_fields FROM entries WHERE id = ?", (added["entry_id"],)).fetchone()
        self.assertEqual((row["title"], row["creator"]), ("Study in red", "Ada"))
        self.assertLessEqual({"title", "creator"}, set(json.loads(row["manual_fields"])))

    def test_nothing_is_stored_or_protected_when_the_card_has_no_details(self):
        added = capture.add_link(self.conn, "https://example.com/files/pic.png")
        capture.keep_details(self.conn, added["entry_id"], "  ", "")
        row = self.conn.execute("SELECT manual_fields FROM entries WHERE id = ?", (added["entry_id"],)).fetchone()
        self.assertEqual(json.loads(row["manual_fields"] or "[]"), [])


class RequeueTests(LibraryCase):
    def test_a_saved_link_entry_is_captured_again_and_a_failure_keeps_its_image(self):
        url = "https://example.com/files/pic.png"
        added = capture.add_link(self.conn, url)
        job = self.conn.execute("SELECT id FROM jobs WHERE entry_id = ?", (added["entry_id"],)).fetchone()
        capture.run_capture(self.conn, job["id"], FakeFetcher({url: reply(url, png_bytes(40, 30), "image/png")}))
        self.assertEqual(capture.requeue(self.conn, [added["entry_id"], 9999]), 1)
        self.assertEqual(self.conn.execute("SELECT state FROM entries").fetchone()[0], "pending")
        self.assertEqual(capture.requeue(self.conn, [added["entry_id"]]), 0)
        again = self.conn.execute("SELECT id FROM jobs WHERE state = 'queued'").fetchone()
        capture.run_capture(self.conn, again["id"], FakeFetcher({url: OSError("down")}))
        self.assertEqual(self.conn.execute("SELECT state FROM entries").fetchone()[0], "captured")

    def test_pasted_images_without_a_link_are_skipped(self):
        entry = capture.add_image(self.conn, png_bytes(20, 20), "pasted.png")["entry_id"]
        self.assertEqual(capture.requeue(self.conn, [entry]), 0)


class FullSizeTests(LibraryCase):
    def test_known_hosts_map_to_their_full_size_url(self):
        cases = {
            "https://i.pinimg.com/736x/ab/cd/ef.jpg": "https://i.pinimg.com/originals/ab/cd/ef.jpg",
            "https://pbs.twimg.com/media/AAA?format=webp&name=large": "https://pbs.twimg.com/media/AAA?format=webp&name=orig",
            "https://64.media.tumblr.com/h/h-1/s1280x1920/h.jpg": "https://64.media.tumblr.com/h/h-1/s2048x3072/h.jpg",
            "https://cdn.shopify.com/s/files/1/a_grande.jpg?v=3": "https://cdn.shopify.com/s/files/1/a.jpg",
            "https://site.example/wp-content/uploads/2020/01/pic-300x200.jpg": "https://site.example/wp-content/uploads/2020/01/pic.jpg",
        }
        for small, full in cases.items():
            self.assertEqual(capture.full_size_urls(small), [full], small)
        self.assertEqual(capture.full_size_urls("https://example.com/cover.png"), [])
        self.assertEqual(capture.full_size_urls("https://i.pinimg.com/originals/ab/cd/ef.jpg"), [])

    def test_capture_stores_the_full_size_copy_and_falls_back_when_it_is_missing(self):
        small, full = "https://i.pinimg.com/736x/ab/cd/ef.jpg", "https://i.pinimg.com/originals/ab/cd/ef.jpg"
        page = b'<meta property="og:image" content="%s">' % small.encode()
        for served, expected in ((reply(full, png_bytes(2000, 1000), "image/png"), 2000), (RuntimeError("404"), 400)):
            conn_entry = capture.add_link(self.conn, "https://example.com/pin%d" % expected)
            job = self.conn.execute("SELECT id FROM jobs WHERE entry_id = ?", (conn_entry["entry_id"],)).fetchone()
            fetcher = FakeFetcher({
                "https://example.com/pin%d" % expected: reply("https://example.com/pin%d" % expected, page, "text/html"),
                small: reply(small, png_bytes(400, 200), "image/png"), full: served,
            })
            capture.run_capture(self.conn, job["id"], fetcher)
            row = self.conn.execute("SELECT width FROM assets WHERE entry_id = ? AND kind = 'original'",
                                    (conn_entry["entry_id"],)).fetchone()
            self.assertEqual(row["width"], expected)


class MultiImageTests(unittest.TestCase):
    def test_collects_every_image_meta_and_jsonld_in_order_without_duplicates(self):
        html = (
            b'<meta property="og:image" content="/a.jpg"><meta property="og:image" content="/b.jpg">'
            b'<meta name="twitter:image" content="/a.jpg">'
            b'<script type="application/ld+json">{"image": ["/c.jpg", {"url": "/d.jpg"}]}</script>'
        )
        result = capture.extract_metadata(html, "https://x.example/p")
        self.assertEqual(
            result["image_urls"],
            [f"https://x.example/{name}.jpg" for name in "abcd"],
        )
        self.assertEqual(result["image_url"], "https://x.example/a.jpg")

    def test_size_variants_of_one_pinterest_image_collapse_to_one(self):
        html = (
            b'<meta property="og:image" content="https://i.pinimg.com/736x/ab/cd/abcd1234.jpg">'
            b'<meta name="twitter:image" content="https://i.pinimg.com/564x/ab/cd/abcd1234.jpg">'
            b'<script type="application/ld+json">{"image": ["https://i.pinimg.com/originals/ab/cd/abcd1234.jpg",'
            b' "https://i.pinimg.com/736x/ef/01/ef012345.jpg"]}</script>'
        )
        result = capture.extract_metadata(html, "https://www.pinterest.com/pin/1/")
        self.assertEqual(
            result["image_urls"],
            ["https://i.pinimg.com/originals/ab/cd/abcd1234.jpg", "https://i.pinimg.com/736x/ef/01/ef012345.jpg"],
        )

    def test_post_page_collects_its_own_media_and_skips_other_posts(self):
        base = "https://pbs.twimg.com/media/"
        block = lambda name: '{"media_url_https":"%s%s.jpg","type":"photo"},' % (base, name)
        html = (
            '<meta property="og:image" content="%sAAA?format=webp&name=large">' % base
            + '<script>{"entities":[' + block("AAA") + block("BBB") + "]}" + " " * 4000
            + '{"entities":[' + block("CCC") + "]}</script>"
        ).encode()
        result = capture.extract_metadata(html, "https://x.com/u/status/1")
        self.assertEqual(
            result["image_urls"],
            [f"{base}{name}?format=webp&name=large" for name in ("AAA", "BBB")],
        )

    def test_caps_image_count(self):
        html = "".join(f'<meta property="og:image" content="/{i}.jpg">' for i in range(40)).encode()
        self.assertEqual(len(capture.extract_metadata(html, "https://x.example/")["image_urls"]), capture.MAX_IMAGES)


def animated_gif_bytes(size=(600, 400)) -> bytes:
    from PIL import Image

    frames = [Image.new("RGB", size, color) for color in ("red", "green", "blue")]
    buffer = io.BytesIO()
    frames[0].save(buffer, "GIF", save_all=True, append_images=frames[1:], duration=80, loop=0)
    return buffer.getvalue()


class AnimatedThumbnailTests(LibraryCase):
    def test_animated_gif_gets_an_animated_thumbnail(self):
        from PIL import Image

        result = capture.add_image(self.conn, animated_gif_bytes(), "spin.gif")
        row = self.conn.execute(
            "SELECT path FROM assets WHERE entry_id = ? AND kind = 'thumbnail'", (result["entry_id"],)
        ).fetchone()
        with Image.open(db.data_dir() / row[0]) as thumb:
            self.assertTrue(getattr(thumb, "is_animated", False))
            self.assertLessEqual(max(thumb.size), capture.THUMB_EDGE)

    def test_refresh_rebuilds_a_static_thumbnail(self):
        from PIL import Image

        result = capture.add_image(self.conn, animated_gif_bytes(), "spin.gif")
        row = self.conn.execute(
            "SELECT path FROM assets WHERE entry_id = ? AND kind = 'thumbnail'", (result["entry_id"],)
        ).fetchone()
        target = db.data_dir() / row[0]
        Image.new("RGB", (480, 320), "red").save(target, "WEBP")
        self.assertFalse(capture._has_animation(target))
        self.assertEqual(capture.refresh_animated_thumbnails(self.conn), 1)
        self.assertTrue(capture._has_animation(target))
        self.assertEqual(capture.refresh_animated_thumbnails(self.conn), 0)
