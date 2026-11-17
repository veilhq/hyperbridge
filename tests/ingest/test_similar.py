"""Tests for Find similar: ranking the feed against a set and weighting its sources."""

import json
import random
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import arena  # noqa: E402
from bridge.ingest import feed  # noqa: E402
from bridge.ingest import similar  # noqa: E402
from bridge.library import library  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402

NOW = "2026-11-15T10:00:00"


class SimilarCase(LibraryCase):
    def make_set(self, name="Concrete"):
        return self.conn.execute("INSERT INTO sets (name, description, created_at) VALUES (?, '', ?)", (name, NOW)).lastrowid

    def member(self, set_id, title="", tags=(), collection="", creator="", source_url=""):
        entry = self.add_entry(title=title, creator=creator)
        self.conn.execute("UPDATE entries SET collection = ?, source_url = ? WHERE id = ?", (collection, source_url, entry))
        if tags:
            library.add_entry_tags(self.conn, entry, list(tags))
        self.conn.execute("INSERT INTO set_entries (set_id, entry_id, placed_at) VALUES (?, ?, ?)", (set_id, entry, NOW))
        return entry

    def feed_item(self, url, tags=(), collection="", title="", creator="", source_id="arena", state="new", page_url=""):
        cursor = self.conn.execute(
            "INSERT INTO feed_items (source_id, url, thumb, width, height, title, creator, page_url, term, created_at,"
            " source_ref, collection, posted_at, tags, state) VALUES (?, ?, ?, 10, 10, ?, ?, ?, '', ?, '', ?, '', ?, ?)",
            (source_id, url, url, title, creator, page_url, NOW, collection, json.dumps(list(tags)), state))
        return cursor.lastrowid

    def block_member(self, set_id, block_id, **fields):
        entry = self.member(set_id, **fields)
        self.conn.execute("UPDATE entries SET source_service = 'arena', source_ref = ? WHERE id = ?", (str(block_id), entry))
        return entry


class WordTests(unittest.TestCase):
    def test_folds_plurals_and_drops_noise(self):
        self.assertEqual(similar.words("Brutalist Posters of the 1970s via Tumblr"), {"brutalist", "poster", "1970"})

    def test_ies_plural(self):
        self.assertEqual(similar.words("galleries"), {"gallery"})


class ProfileTests(SimilarCase):
    def test_empty_set_has_no_profile(self):
        self.assertEqual(similar.profile(self.conn, self.make_set()), {})

    def test_shares_reflect_how_many_images_carry_a_term(self):
        set_id = self.make_set()
        self.member(set_id, tags=["concrete", "brutalism"])
        self.member(set_id, tags=["concrete"])
        wanted = similar.profile(self.conn, set_id)
        self.assertEqual(wanted["concrete"], 1.0)
        self.assertEqual(wanted["brutalism"], 0.5)
        self.assertEqual(wanted["tag:concrete"], 1.0)

    def test_service_tags_are_ignored(self):
        set_id = self.make_set()
        self.member(set_id, tags=["pinterest", "are.na"])
        self.assertEqual(similar.profile(self.conn, set_id), {})

    def test_filename_titles_are_ignored(self):
        set_id = self.make_set()
        self.member(set_id, title="IMG_20240101_1234.jpg")
        self.assertEqual(similar.profile(self.conn, set_id), {})


class RankTests(SimilarCase):
    def setUp(self):
        super().setUp()
        self.set_id = self.make_set()
        self.member(self.set_id, tags=["concrete", "brutalism"], collection="Brutal Buildings")
        self.member(self.set_id, tags=["concrete"])

    def test_only_matching_unseen_items_are_ranked_best_first(self):
        weak = self.feed_item("https://x/weak.jpg", tags=["concrete", "cat", "dog", "food", "sunset", "beach"])
        strong = self.feed_item("https://x/strong.jpg", tags=["concrete", "brutalism"])
        self.feed_item("https://x/off.jpg", tags=["kittens"])
        self.feed_item("https://x/gone.jpg", tags=["concrete"], state="dismissed")
        result = similar.list_items(self.conn, self.set_id)
        self.assertEqual([item["id"] for item in result["items"]], [strong, weak])
        self.assertEqual(result["total"], 2)
        self.assertIn("concrete", result["items"][0]["matched"])

    def test_untagged_items_match_on_their_collection(self):
        channel = self.feed_item("https://x/block.jpg", collection="Brutal Buildings")
        result = similar.list_items(self.conn, self.set_id)
        self.assertEqual([item["id"] for item in result["items"]], [channel])

    def test_only_arena_images_are_ranked(self):
        self.feed_item("https://x/post.jpg", tags=["concrete"], source_id="tumblr")
        self.feed_item("https://x/pin.jpg", tags=["concrete"], source_id="pinterest")
        self.assertEqual(similar.list_items(self.conn, self.set_id)["total"], 0)

    def test_leading_terms_are_reported(self):
        terms = similar.list_items(self.conn, self.set_id)["terms"]
        self.assertEqual(terms[0], "concrete")

    def test_paging(self):
        for index in range(5):
            self.feed_item(f"https://x/{index}.jpg", tags=["concrete"])
        page = similar.list_items(self.conn, self.set_id, offset=3, limit=10)
        self.assertEqual((len(page["items"]), page["total"]), (2, 5))


class SetTagTests(SimilarCase):
    def setUp(self):
        super().setUp()
        self.set_id = self.make_set()
        self.member(self.set_id, tags=["concrete", "kittens"])
        self.conn.execute("UPDATE sets SET tags = ? WHERE id = ?", (json.dumps(["Brutalist Poster", "concrete"]), self.set_id))

    def test_own_tags_outweigh_terms_read_from_images(self):
        wanted = similar.profile(self.conn, self.set_id)
        self.assertEqual((wanted["tag:brutalist poster"], wanted["concrete"]), (1.0, 1.0))
        self.assertEqual(wanted["kitten"], similar.INFERRED_WEIGHT)

    def test_a_tagged_set_lists_only_items_matching_its_tags(self):
        hit = self.feed_item("https://x/hit.jpg", collection="Swiss Poster")
        self.feed_item("https://x/miss.jpg", tags=["kittens"])
        result = similar.list_items(self.conn, self.set_id)
        self.assertEqual([item["id"] for item in result["items"]], [hit])
        self.assertEqual(result["terms"], ["Brutalist Poster", "concrete"])

    def test_searches_use_the_tags_as_written(self):
        phrases = similar.tag_queries(similar.set_tags(self.conn, self.set_id), random.Random(1), count=5)
        self.assertEqual(sorted(phrases), ["Brutalist Poster", "concrete"])

    def test_a_tag_not_yet_searched_makes_the_set_due(self):
        similar.search(self.conn, self.set_id, search_fetcher, random.Random(1))
        self.assertFalse(similar.list_items(self.conn, self.set_id)["stale"])
        self.conn.execute("UPDATE sets SET tags = ? WHERE id = ?", (json.dumps(["Brutalist Poster", "concrete", "raw"]), self.set_id))
        self.assertTrue(similar.list_items(self.conn, self.set_id)["stale"])

    def test_an_empty_tagged_set_can_still_search(self):
        empty = self.make_set("Empty")
        self.conn.execute("UPDATE sets SET tags = '[\"concrete\"]' WHERE id = ?", (empty,))
        self.assertEqual(similar.search(self.conn, empty, search_fetcher, random.Random(1))["queries"], ["concrete"])


class SourceWeightTests(SimilarCase):
    def test_named_and_origin_sources_outweigh_others(self):
        set_id = self.make_set()
        self.member(set_id, tags=["concrete"], source_url="https://www.are.na/someone/raw-forms")
        followed = [
            {"url": "https://www.are.na/someone/raw-forms", "label": "Raw Forms"},
            {"url": "https://concrete-daily.tumblr.com", "label": "concrete daily"},
            {"url": "https://www.are.na/someone/flowers", "label": "Flowers"},
        ]
        weights = similar.source_weights(self.conn, set_id, followed)
        self.assertEqual(weights["https://www.are.na/someone/flowers"], 1.0)
        self.assertGreater(weights["https://www.are.na/someone/raw-forms"], 1.0)
        self.assertGreater(weights["https://concrete-daily.tumblr.com"], 1.0)


def reply(data):
    return SimpleNamespace(body=json.dumps(data).encode(), final_url="", status=200, content_type="application/json")


def search_fetcher(url, headers=None):
    if "/v2/search/channels" in url:
        return reply({"channels": [{"slug": "coffee", "title": "Espresso Yourself", "length": 900, "status": "open", "user": {"slug": "maker"}},
                                   {"slug": "concrete-things", "title": "Concrete Things", "length": 3, "status": "closed", "user": {"slug": "maker"}},
                                   {"slug": "secret", "title": "Concrete", "length": 3, "status": "private", "user": {"slug": "maker"}}]})
    if "/contents" in url:
        return reply({"data": [{"id": 7, "title": "slab", "image": {"src": "https://arena.example/slab.jpg"}}]})
    if "api.are.na/v3/channels/" in url:
        return reply({"title": "Concrete Things", "counts": {"contents": 1}})
    raise AssertionError(url)


class SearchTests(SimilarCase):
    def setUp(self):
        super().setUp()
        self.set_id = self.make_set()
        self.member(self.set_id, tags=["concrete"], creator="Somebody")

    def test_arena_channel_search_skips_private_and_off_topic_channels(self):
        self.assertEqual(arena.search_channels("concrete", search_fetcher), ["https://www.are.na/maker/concrete-things"])

    def test_arena_phrase_with_no_channels_is_searched_word_by_word(self):
        asked = []

        def fetcher(url, headers=None):
            asked.append(url)
            if "q=raw+concrete" in url:
                return reply({"channels": []})
            return search_fetcher(url, headers)
        self.assertEqual(arena.search_channels("raw concrete", fetcher), ["https://www.are.na/maker/concrete-things"])
        self.assertEqual(len(asked), 3)

    def test_queries_skip_creators(self):
        phrases = similar.queries(similar.profile(self.conn, self.set_id), random.Random(1), count=5)
        self.assertEqual(phrases, ["concrete"])

    def test_queries_offer_pairs_of_leading_terms(self):
        phrases = similar.queries({"concrete": 1.0, "poster": 1.0}, random.Random(1), count=3)
        self.assertEqual(sorted(phrases), ["concrete", "concrete poster", "poster"])

    def test_queries_favor_phrases_not_yet_searched(self):
        wanted = {"concrete": 1.0, "poster": 0.5}
        picks = [similar.queries(wanted, random.Random(seed), count=1, used=["concrete", "concrete poster"])[0] for seed in range(40)]
        self.assertGreater(picks.count("poster"), picks.count("concrete"))

    def test_searching_again_adds_to_earlier_finds(self):
        similar.search(self.conn, self.set_id, search_fetcher, random.Random(1))

        def more(url, headers=None):
            if "/contents" in url:
                return reply({"data": [{"id": 8, "title": "beam", "image": {"src": "https://arena.example/beam.jpg"}}]})
            return search_fetcher(url, headers)
        similar.search(self.conn, self.set_id, more, random.Random(2))
        self.assertEqual(similar.list_items(self.conn, self.set_id)["total"], 2)

    def test_search_finds_belong_to_the_set_and_stay_out_of_discover(self):
        result = similar.search(self.conn, self.set_id, search_fetcher, random.Random(1))
        self.assertEqual((result["added"], result["failed"], result["queries"]), (1, 0, ["concrete"]))
        self.assertEqual(similar.list_items(self.conn, self.set_id)["total"], 1)
        self.assertEqual(feed.list_items(self.conn)["total"], 0)
        other = self.make_set("Other")
        self.member(other, tags=["concrete"])
        self.assertEqual(similar.list_items(self.conn, other)["total"], 0)

    def test_finds_offer_their_channel_until_it_or_its_owner_is_followed(self):
        similar.search(self.conn, self.set_id, search_fetcher, random.Random(1))
        item = similar.list_items(self.conn, self.set_id)["items"][0]
        self.assertEqual((item["follow_url"], item["follow_label"]), ("https://www.are.na/maker/concrete-things", "Concrete Things"))
        self.conn.execute("INSERT INTO followed_sources (kind, url, label, created_at) VALUES ('user', 'https://www.are.na/maker', 'maker', ?)", (NOW,))
        self.assertNotIn("follow_url", similar.list_items(self.conn, self.set_id)["items"][0])

    def test_an_unreachable_arena_counts_as_a_failed_search(self):
        def down(url, headers=None):
            raise OSError("down")
        result = similar.search(self.conn, self.set_id, down, random.Random(1))
        self.assertEqual((result["added"], result["failed"]), (0, 1))

    def test_search_is_due_until_the_set_has_been_searched(self):
        self.assertTrue(similar.list_items(self.conn, self.set_id)["stale"])
        similar.search(self.conn, self.set_id, search_fetcher, random.Random(1))
        self.assertFalse(similar.list_items(self.conn, self.set_id)["stale"])


class RefreshTests(SimilarCase):
    def test_searches_then_pulls_from_followed_arena_sources_only(self):
        set_id = self.make_set()
        self.member(set_id, tags=["concrete"])
        self.conn.execute("INSERT INTO followed_sources (kind, url, label, created_at) VALUES ('channel', 'https://www.are.na/me/chan', 'Chan', ?)", (NOW,))
        self.conn.execute("INSERT INTO followed_sources (kind, url, label, created_at) VALUES ('blog', 'https://concrete.tumblr.com', 'concrete', ?)", (NOW,))
        item = {"source_id": "arena", "url": "https://arena.example/o.jpg", "thumb": "", "width": 1, "height": 1,
                "title": "", "creator": "", "page_url": "", "term": "", "tags": ["concrete"]}
        original = feed.pull
        pulled = []
        feed.pull = lambda url, fetcher, rng: pulled.append(url) or [item]
        self.addCleanup(setattr, feed, "pull", original)
        result = similar.refresh(self.conn, set_id, fetcher=search_fetcher, rng=random.Random(1))
        self.assertEqual((result["added"], result["jobs"], result["enabled"]), (2, 2, ["search", "arena"]))
        self.assertEqual(pulled, ["https://www.are.na/me/chan"])
        self.assertEqual(similar.list_items(self.conn, set_id)["total"], 2)


def holder(slug, length, visibility="closed", owner="maker"):
    return {"slug": slug, "title": slug.replace("-", " ").title(), "visibility": visibility, "counts": {"contents": length},
            "owner": {"slug": owner}}


HOLDERS = {101: [holder("raw-forms", 40), holder("everything", 50000), holder("secret", 30, "private")],
           102: [holder("raw-forms", 40), holder("slabs", 12)]}


def neighbor_fetcher(url, headers=None):
    if "/connections" in url:
        block = int(url.split("/blocks/")[1].split("/")[0])
        return reply({"data": HOLDERS[block], "meta": {"total_pages": 1}})
    if "/contents" in url:
        slug = url.split("/channels/")[1].split("/")[0]
        return reply({"data": [{"id": 900, "title": slug, "image": {"src": f"https://arena.example/{slug}.jpg"}}]})
    return search_fetcher(url, headers)


class NeighborTests(SimilarCase):
    def setUp(self):
        super().setUp()
        self.set_id = self.make_set()
        self.block_member(self.set_id, 101, tags=["concrete"])
        self.block_member(self.set_id, 102, tags=["concrete"])

    def shared(self):
        rows = self.conn.execute("SELECT slug, shared FROM set_neighbors WHERE set_id = ?", (self.set_id,))
        return {row["slug"]: row["shared"] for row in rows}

    def test_neighbors_count_shared_blocks_and_skip_private_channels(self):
        self.assertEqual(similar.find_neighbors(self.conn, self.set_id, neighbor_fetcher, random.Random(1)), 0)
        self.assertEqual(self.shared(), {"raw-forms": 2, "everything": 1, "slabs": 1})

    def test_a_failed_lookup_keeps_earlier_counts(self):
        similar.find_neighbors(self.conn, self.set_id, neighbor_fetcher, random.Random(1))

        def half(url, headers=None):
            if "/blocks/102/" in url:
                raise OSError("down")
            return neighbor_fetcher(url, headers)
        self.assertEqual(similar.find_neighbors(self.conn, self.set_id, half, random.Random(1)), 1)
        self.assertEqual(self.shared()["raw-forms"], 2)

    def test_close_channels_outweigh_giant_catch_alls(self):
        similar.find_neighbors(self.conn, self.set_id, neighbor_fetcher, random.Random(1))
        near = similar.neighbor_weights(self.conn, self.set_id)
        self.assertGreater(near["slabs"][0], near["everything"][0])
        self.assertGreater(near["raw-forms"][0], near["slabs"][0])

    def test_neighbor_items_are_listed_without_matching_words_and_outrank_word_matches(self):
        similar.find_neighbors(self.conn, self.set_id, neighbor_fetcher, random.Random(1))
        words_only = self.feed_item("https://x/words.jpg", tags=["concrete"])
        near = self.feed_item("https://x/near.jpg", title="untitled", page_url="https://www.are.na/maker/raw-forms")
        self.feed_item("https://x/far.jpg", title="kittens", page_url="https://www.are.na/maker/elsewhere")
        items = similar.list_items(self.conn, self.set_id)["items"]
        self.assertEqual([item["id"] for item in items], [near, words_only])
        self.assertEqual(items[0]["matched"], ["Raw Forms"])

    def test_a_tagged_set_still_lists_neighbor_items(self):
        self.conn.execute("UPDATE sets SET tags = '[\"brutalism\"]' WHERE id = ?", (self.set_id,))
        similar.find_neighbors(self.conn, self.set_id, neighbor_fetcher, random.Random(1))
        near = self.feed_item("https://x/near.jpg", tags=["kittens"], page_url="https://www.are.na/maker/slabs")
        self.assertEqual([item["id"] for item in similar.list_items(self.conn, self.set_id)["items"]], [near])

    def test_search_pulls_neighbors_and_one_phrase_from_its_closest_channel(self):
        result = similar.search(self.conn, self.set_id, neighbor_fetcher, random.Random(1))
        self.assertEqual(sorted(result["neighbors"]), ["https://www.are.na/maker/everything", "https://www.are.na/maker/raw-forms",
                                                      "https://www.are.na/maker/slabs"])
        self.assertEqual((len(result["queries"]), result["jobs"], result["failed"]), (1, 4, 0))
        urls = {row[0] for row in self.conn.execute("SELECT url FROM feed_items WHERE set_id = ?", (self.set_id,))}
        self.assertEqual(urls, {f"https://arena.example/{slug}.jpg" for slug in ("everything", "raw-forms", "slabs", "concrete-things")})

    def test_refresh_reports_neighbors(self):
        result = similar.refresh(self.conn, self.set_id, fetcher=neighbor_fetcher, rng=random.Random(1))
        self.assertEqual(result["enabled"], ["neighbors", "search"])


class QueryTermTests(unittest.TestCase):
    def test_the_phrase_an_item_was_found_by_counts_less_than_its_own_tags(self):
        row = {"tags": "[]", "collection": "Brutal Things", "term": "concrete", "creator": "", "title": ""}
        self.assertEqual(similar._item_terms(row)["tag:concrete"], similar.QUERY_TERM_WEIGHT)
        row["tags"] = json.dumps(["concrete"])
        self.assertEqual(similar._item_terms(row)["tag:concrete"], 1.0)


if __name__ == "__main__":
    unittest.main()
