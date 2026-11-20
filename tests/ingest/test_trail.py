"""Tests for trails: where an image leads, one request per checked place, the per-trail budget, cooldowns, and keeping images."""

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.core.fetchguard import FetchError  # noqa: E402
from bridge.ingest import feed, trail, tumblr  # noqa: E402
from bridge.library import creators  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402


def reply(data, content_type="application/json"):
    body = data if isinstance(data, bytes) else json.dumps(data).encode()
    return SimpleNamespace(body=body, final_url="", status=200, content_type=content_type)


def block(number, owner="maker", source=""):
    return {"id": number, "title": f"Block {number}", "created_at": "2026-01-02T00:00:00Z", "user": {"slug": owner},
            "source": {"url": source} if source else {},
            "image": {"src": f"https://images.are.na/{number}.jpg", "large": {"src": f"https://images.are.na/{number}-l.jpg"}}}


def tumblr_reply(host, posts, total):
    data = {"tumblelog": {"title": host}, "posts-total": total, "posts": posts}
    return reply(f"var tumblr_api_read = {json.dumps(data)};".encode(), "text/javascript")


def photo_post(number, host, reblog_from="", reblog_root=""):
    post = {"id": str(number), "url": f"https://{host}/post/{number}", "photo-url-1280": f"https://64.media.tumblr.com/{number}.jpg",
            "photo-url-500": f"https://64.media.tumblr.com/{number}-500.jpg", "tags": ["type"], "date-gmt": "2026-01-02 00:00:00 GMT"}
    if reblog_from:
        post.update({"reblogged-from-url": reblog_from, "reblogged-root-url": reblog_root})
    return post


RSS = (b'<?xml version="1.0"?><rss><channel><title>Studio</title><item><title>One</title><link>https://studio.example/1</link>'
       b'<guid>1</guid><description>&lt;img src="https://studio.example/1.jpg"&gt;</description></item></channel></rss>')


class FakeWeb:
    """A fetcher with canned replies that records each request and can report hosts as cooling."""

    def __init__(self):
        self.calls = []
        self.cooling = set()
        self.replies = {
            "https://api.are.na/v3/blocks/7/connections": reply({"data": [
                {"slug": "big-chan", "title": "Big Chan", "counts": {"contents": 40}, "owner": {"slug": "curator"}}]}),
            "https://api.are.na/v3/channels/my-chan/contents": reply({"data": [block(1), block(2)], "meta": {"total_count": 2, "total_pages": 1}}),
            "https://api.are.na/v3/channels/big-chan/contents": reply({"data": [block(3)], "meta": {"total_count": 140, "total_pages": 2}}),
            "https://api.are.na/v3/users/maker/contents": reply({"data": [block(4)], "meta": {"total_pages": 1}}),
            "https://studio.example/": reply(RSS, "application/rss+xml"),
            "https://blog.tumblr.com/api/read/json": tumblr_reply("blog.tumblr.com", [photo_post(10, "blog.tumblr.com", "https://other.tumblr.com/post/9", "https://root.tumblr.com/post/1")], 120),
            "https://other.tumblr.com/api/read/json": tumblr_reply("other.tumblr.com", [photo_post(11, "other.tumblr.com")], 1),
            "https://root.tumblr.com/api/read/json": tumblr_reply("root.tumblr.com", [], 0),
        }

    def is_cooling(self, host):
        return host in self.cooling

    def __call__(self, url, **kwargs):
        self.calls.append(url)
        found = self.replies.get(url.split("?")[0])
        if isinstance(found, Exception):
            raise found
        if found is None:
            raise FetchError("http_status", "HTTP 404", 404)
        return found


class TrailCase(LibraryCase):
    def setUp(self):
        super().setUp()
        self.web = FakeWeb()
        trail._SPENT.clear()
        self.addCleanup(trail._SPENT.clear)

    def feed_item(self, **fields):
        item = {"source_id": "arena", "url": "https://images.are.na/start.jpg", "thumb": "", "width": 1, "height": 1,
                "title": "Start", "creator": "", "page_url": "https://www.are.na/maker/my-chan", "term": "",
                "collection": "My Chan", "source_ref": "7", "creator_handle": "https://www.are.na/maker",
                "source_link": "https://studio.example/work/1"}
        item.update(fields)
        feed.store(self.conn, [item])
        return self.conn.execute("SELECT id FROM feed_items WHERE url = ?", (item["url"],)).fetchone()[0]

    def by_kind(self, result):
        return {hop["kind"]: hop for hop in result["hops"]}


class HopTests(TrailCase):
    def test_stored_fields_list_places_without_any_request(self):
        found = self.by_kind(trail.hops(self.conn, {"feed": self.feed_item()}, self.web))
        self.assertEqual(found["channel"]["url"], "https://www.are.na/maker/my-chan")
        self.assertEqual(found["user"]["url"], "https://www.are.na/maker")
        self.assertEqual(found["site"]["url"], "https://studio.example/")
        self.assertTrue(all(hop["state"] == "unchecked" for hop in found.values()))
        self.assertEqual(self.web.calls, [])

    def test_pinterest_images_start_a_trail_but_never_lead_to_pinterest(self):
        self.add_entry(creator="Ada Lovelace")
        start = self.feed_item(source_id="pinterest", url="https://i.pinimg.com/a.jpg", page_url="https://www.pinterest.com/me/board/",
                               creator="Ada Lovelace", creator_handle="", source_link="", source_ref="55")
        result = trail.check(self.conn, {"feed": start}, "t1", self.web)
        self.assertEqual([hop["kind"] for hop in result["hops"]], ["creator"])
        self.assertEqual(self.web.calls, [])

    def test_tumblr_hops_include_the_blog_and_where_it_was_reblogged_from(self):
        start = self.feed_item(source_id="tumblr", url="https://64.media.tumblr.com/s.jpg", page_url="https://blog.tumblr.com/post/1",
                               creator_handle="https://blog.tumblr.com/", source_link="", source_ref="1",
                               reblog_from="https://other.tumblr.com/post/9", reblog_root="https://root.tumblr.com/post/1")
        urls = [hop["url"] for hop in trail.hops(self.conn, {"feed": start}, self.web)["hops"]]
        self.assertEqual(urls, ["https://blog.tumblr.com/", "https://other.tumblr.com/", "https://root.tumblr.com/"])

    def test_library_tags_and_credit_lead_to_other_saved_images(self):
        first = self.add_entry(creator="Studio Wren")
        second = self.add_entry(creator="Studio Wren")
        for entry in (first, second):
            self.conn.execute("INSERT OR IGNORE INTO tags (name) VALUES ('poster')")
            self.conn.execute("INSERT INTO entry_tags (entry_id, tag_id) SELECT ?, id FROM tags WHERE name = 'poster'", (entry,))
        found = self.by_kind(trail.hops(self.conn, {"entry": first}, self.web))
        self.assertEqual((found["creator"]["count"], found["tag"]["count"]), (1, 1))
        step = trail.images(self.conn, found["tag"], "t1", self.web)
        self.assertEqual([image["id"] for image in step["images"]], [second, first])


class CheckTests(TrailCase):
    def test_each_place_costs_one_request_and_held_channels_come_counted(self):
        result = trail.check(self.conn, {"feed": self.feed_item()}, "t1", self.web)
        self.assertEqual(self.web.calls, [
            "https://api.are.na/v3/blocks/7/connections?per=50",
            "https://api.are.na/v3/channels/my-chan/contents?per=100&page=1",
            "https://api.are.na/v3/users/maker/contents?per=100&page=1",
            "https://studio.example/"])
        counts = {hop["url"]: hop["count"] for hop in result["hops"]}
        self.assertEqual(counts["https://www.are.na/curator/big-chan"], 40)
        self.assertEqual(counts["https://www.are.na/maker/my-chan"], 2)
        self.assertEqual(counts["https://studio.example/"], 1)
        self.assertEqual(result["left"], trail.BUDGET - 4)

    def test_a_place_checked_today_is_served_without_asking_again(self):
        start = self.feed_item()
        trail.check(self.conn, {"feed": start}, "t1", self.web)
        self.web.calls.clear()
        trail.check(self.conn, {"feed": start}, "t2", self.web)
        step = trail.images(self.conn, {"kind": "channel", "url": "https://www.are.na/maker/my-chan"}, "t2", self.web)
        self.assertEqual(len(step["images"]), 2)
        self.assertEqual(self.web.calls, [])

    def test_empty_and_missing_places_are_dropped(self):
        start = self.feed_item(source_link="https://gone.example/x")
        result = trail.check(self.conn, {"feed": start}, "t1", self.web)
        self.assertNotIn("https://gone.example/", [hop["url"] for hop in result["hops"]])

    def test_once_the_budget_is_spent_places_stay_unchecked_until_picked(self):
        start = self.feed_item()
        with mock.patch.object(trail, "BUDGET", 2):
            result = trail.check(self.conn, {"feed": start}, "t1", self.web)
            self.assertEqual(len(self.web.calls), 2)
            states = {hop["url"]: hop["state"] for hop in result["hops"]}
            self.assertEqual(states["https://studio.example/"], "unchecked")
            step = trail.images(self.conn, {"kind": "site", "url": "https://studio.example/"}, "t1", self.web)
        self.assertEqual(len(step["images"]), 1)
        self.assertEqual(len(self.web.calls), 3)

    def test_a_cooling_host_is_left_alone_and_said_so(self):
        self.web.cooling.add("api.are.na")
        result = trail.check(self.conn, {"feed": self.feed_item()}, "t1", self.web)
        states = {hop["kind"]: hop["state"] for hop in result["hops"]}
        self.assertEqual((states["channel"], states["user"], states["site"]), ("cooling", "cooling", "ready"))
        self.assertEqual(self.web.calls, ["https://studio.example/"])

    def test_pushback_is_not_retried_and_the_place_is_not_written_off(self):
        for status in (429, 403):
            with self.subTest(status=status):
                self.conn.execute("DELETE FROM trail_places")
                self.web.calls.clear()
                self.web.replies["https://studio.example/"] = FetchError("http_status", f"HTTP {status}", status)
                start = self.feed_item(source_service="", source_id="rss", page_url="https://studio.example/1",
                                       url=f"https://studio.example/{status}.jpg", source_link="", creator_handle="")
                trail.check(self.conn, {"feed": start}, f"t{status}", self.web)
                self.assertEqual(self.web.calls, ["https://studio.example/"])
                self.assertIsNone(self.conn.execute("SELECT 1 FROM trail_places WHERE url = 'https://studio.example/'").fetchone())

    def test_tags_lead_out_to_are_na_channels_found_by_searching_them(self):
        self.web.replies["https://api.are.na/v2/search/channels"] = reply({"channels": [
            {"slug": "brutal-forms", "title": "Brutalism Forms", "length": 88, "user": {"slug": "curator"}},
            {"slug": "concrete", "title": "Concrete", "length": 12, "user": {"slug": "curator"}}]})
        start = self.feed_item(source_id="pinterest", url="https://i.pinimg.com/b.jpg", page_url="https://www.pinterest.com/me/board/",
                               creator_handle="", source_link="", source_ref="56", tags=["brutalism", "ok"])
        listed = trail.hops(self.conn, {"feed": start}, self.web)
        self.assertTrue(listed["pending"])
        result = trail.check(self.conn, {"feed": start}, "t1", self.web)
        self.assertEqual(len(self.web.calls), 1)
        self.assertIn("q=brutalism", self.web.calls[0])
        channels = [hop for hop in result["hops"] if hop["kind"] == "channel"]
        self.assertEqual([(hop["url"], hop["count"], hop["state"], hop["via"]) for hop in channels],
                         [("https://www.are.na/curator/brutal-forms", 88, "ready", "brutalism")])
        self.web.calls.clear()
        again = trail.hops(self.conn, {"feed": start}, self.web)
        self.assertFalse(again["pending"])
        self.assertEqual(len([hop for hop in again["hops"] if hop["kind"] == "channel"]), 1)
        self.assertEqual(self.web.calls, [])

    def test_a_tag_search_that_fails_is_not_retried_today(self):
        start = self.feed_item(source_id="pinterest", url="https://i.pinimg.com/c.jpg", page_url="https://www.pinterest.com/me/board/",
                               creator_handle="", source_link="", source_ref="57", tags=["brutalism"])
        trail.check(self.conn, {"feed": start}, "t1", self.web)
        self.assertEqual(len(self.web.calls), 1)
        self.assertFalse(trail.hops(self.conn, {"feed": start}, self.web)["pending"])

    def test_tags_that_only_name_a_site_are_not_searched(self):
        start = self.feed_item(source_id="pinterest", url="https://i.pinimg.com/d.jpg", page_url="https://www.pinterest.com/me/board/",
                               creator_handle="", source_link="", source_ref="58",
                               tags=["Are.na", "INSTAGRAM", "x", "brutalism"])
        trail.check(self.conn, {"feed": start}, "t1", self.web)
        self.assertEqual(len(self.web.calls), 1)
        self.assertIn("q=brutalism", self.web.calls[0])

    def test_later_pages_are_read_only_when_asked(self):
        start = self.feed_item()
        trail.check(self.conn, {"feed": start}, "t1", self.web)
        place = {"kind": "channel", "url": "https://www.are.na/curator/big-chan"}
        first = trail.images(self.conn, place, "t1", self.web)
        self.assertTrue(first["more"])
        self.web.replies["https://api.are.na/v3/channels/big-chan/contents"] = reply({"data": [block(5)], "meta": {"total_pages": 2}})
        second = trail.images(self.conn, place, "t1", self.web, more=True)
        self.assertEqual([image["url"] for image in second["images"]],
                         ["https://images.are.na/3.jpg", "https://images.are.na/5.jpg"])
        self.assertFalse(second["more"])


class KeepTests(TrailCase):
    def test_trail_images_stay_out_of_discover_and_latest(self):
        trail.check(self.conn, {"feed": self.feed_item()}, "t1", self.web)
        shown = {item["url"] for item in feed.list_items(self.conn)["items"]}
        self.assertEqual(shown, {"https://images.are.na/start.jpg"})
        latest = {item["url"] for item in feed.list_latest(self.conn)["items"]}
        self.assertEqual(latest, {"https://images.are.na/start.jpg"})

    def test_trail_rows_are_pruned_after_a_day_and_given_up_to_a_later_pull(self):
        trail.check(self.conn, {"feed": self.feed_item()}, "t1", self.web)
        feed.store(self.conn, [{"source_id": "arena", "url": "https://images.are.na/1.jpg", "thumb": "", "width": 1, "height": 1,
                                "title": "", "creator": "", "page_url": "", "term": ""}])
        self.assertEqual(self.conn.execute("SELECT trail FROM feed_items WHERE url = 'https://images.are.na/1.jpg'").fetchone()[0], "")
        self.conn.execute("UPDATE feed_items SET created_at = '2000-01-01T00:00:00' WHERE trail != ''")
        self.conn.execute("UPDATE trail_places SET checked_at = '2000-01-01T00:00:00'")
        feed.prune(self.conn)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM feed_items WHERE trail != ''").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM trail_places").fetchone()[0], 0)

    def test_keeping_an_image_saves_it_with_its_details_and_marks_it_saved(self):
        trail.check(self.conn, {"feed": self.feed_item()}, "t1", self.web)
        step = trail.images(self.conn, {"kind": "channel", "url": "https://www.are.na/maker/my-chan"}, "t1", self.web)
        image = step["images"][0]
        self.conn.execute("INSERT INTO sets (name, created_at) VALUES ('Mine', '2026-01-01')")
        result = trail.save(self.conn, [image["id"]], 1)
        self.assertEqual((result["added"], result["placed"]), (1, 1))
        entry_id = result["entry_ids"][str(image["id"])]
        row = self.conn.execute("SELECT title, collection, source_service, creator_handle FROM entries WHERE id = ?",
                                (entry_id,)).fetchone()
        self.assertEqual(tuple(row), ("Block 1", "My Chan", "arena", "https://www.are.na/maker"))
        again = trail.images(self.conn, {"kind": "channel", "url": "https://www.are.na/maker/my-chan"}, "t1", self.web)
        self.assertEqual(again["images"][0]["known_entry_id"], entry_id)

    def test_keeping_several_images_saves_each_once(self):
        trail.check(self.conn, {"feed": self.feed_item()}, "t1", self.web)
        step = trail.images(self.conn, {"kind": "channel", "url": "https://www.are.na/maker/my-chan"}, "t1", self.web)
        ids = [image["id"] for image in step["images"]]
        result = trail.save(self.conn, ids)
        self.assertEqual(result["added"], len(ids))
        self.assertEqual(sorted(result["entry_ids"]), sorted(str(feed_id) for feed_id in ids))
        self.assertEqual(trail.save(self.conn, ids)["added"], 0)


class PullFieldTests(TrailCase):
    def test_tumblr_items_carry_the_blog_handle_and_reblog_links(self):
        data = {"tumblelog": {"title": "Blog"}, "posts": [photo_post(1, "blog.tumblr.com", "https://a.tumblr.com/post/2", "https://b.tumblr.com/post/3")]}
        item = tumblr.page_items(data, "blog.tumblr.com")[0]
        self.assertEqual((item["creator_handle"], item["reblog_from"], item["reblog_root"]),
                         ("https://blog.tumblr.com/", "https://a.tumblr.com/post/2", "https://b.tumblr.com/post/3"))


class CreatorTests(TrailCase):
    def test_a_handle_that_reads_like_a_saved_credit_is_suggested_until_answered(self):
        saved = self.add_entry(creator="Studio Wren")
        start = self.feed_item(creator_handle="https://www.are.na/studio-wren")
        user = self.by_kind(trail.hops(self.conn, {"feed": start}, self.web))["user"]
        self.assertEqual(user["suggest"], {"name": "Studio Wren", "creator_id": None})
        person = creators.confirm(self.conn, "Studio Wren", user["url"])
        self.assertNotIn("suggest", self.by_kind(trail.hops(self.conn, {"feed": start}, self.web))["user"])
        found = self.by_kind(trail.hops(self.conn, {"feed": start}, self.web))["creator"]
        self.assertEqual(found["url"], f"creator:{person['id']}")
        step = trail.images(self.conn, found, "t1", self.web)
        self.assertEqual([image["id"] for image in step["images"]], [saved])
        self.assertEqual([place["url"] for place in step["places"]], ["https://www.are.na/studio-wren"])

    def test_a_turned_down_match_is_not_suggested_again(self):
        self.add_entry(creator="Studio Wren")
        start = self.feed_item(creator_handle="https://www.are.na/studio-wren")
        self.assertTrue(creators.reject(self.conn, "Studio Wren", "https://www.are.na/studio-wren"))
        self.assertNotIn("suggest", self.by_kind(trail.hops(self.conn, {"feed": start}, self.web))["user"])

    def test_handles_are_read_from_profile_links(self):
        self.assertEqual(creators.handle_of("https://x.com/Ada/status/1"), {"kind": "x", "value": "ada", "url": "https://x.com/Ada"})
        self.assertEqual(creators.handle_of("https://wren.tumblr.com/post/1")["kind"], "tumblr")
        self.assertEqual(creators.handle_of("https://www.studio.example/about")["value"], "studio.example")


if __name__ == "__main__":
    unittest.main()
