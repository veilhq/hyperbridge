"""Tests for the sources Discover finds on its own and how keeps and skips steer the feed."""

import random
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import feed  # noqa: E402
from bridge.ingest import sources  # noqa: E402
from bridge.library import library  # noqa: E402
from tests.ingest.test_similar import NOW, SimilarCase, neighbor_fetcher  # noqa: E402

RAW = "https://www.are.na/maker/raw-forms"
SLABS = "https://www.are.na/maker/slabs"
MAKER = "https://www.are.na/maker"
FOLLOWED = "https://www.are.na/me/chan"


class SourcesCase(SimilarCase):
    def saved_block(self, block_id, tags=()):
        entry = self.add_entry(title="x")
        self.conn.execute("UPDATE entries SET source_service = 'arena', source_ref = ? WHERE id = ?", (str(block_id), entry))
        if tags:
            library.add_tags([entry], ", ".join(tags))
        return entry

    def follow(self, url, kind="channel"):
        self.conn.execute("INSERT INTO followed_sources (kind, url, label, created_at) VALUES (?, ?, 'x', ?)", (kind, url, NOW))

    def candidate(self, url, strength=1.0, state="candidate", label=""):
        self.conn.execute("INSERT INTO candidate_sources (url, label, found_by, strength, state, found_at) VALUES (?, ?, 'neighbor', ?, ?, ?)",
                          (url, label, strength, state, NOW))

    def pulled(self, origin, state, count=1):
        for _ in range(count):
            self.conn.execute("INSERT INTO feed_items (source_id, url, created_at, state, origin_url) VALUES ('arena', ?, ?, ?, ?)",
                              (f"https://x/{random.random()}.jpg", NOW, state, origin))

    def candidates(self):
        return {row["url"]: (row["found_by"], row["state"]) for row in self.conn.execute("SELECT * FROM candidate_sources")}


class DiscoverTests(SourcesCase):
    def test_saves_lead_to_the_channels_holding_them_their_owners_and_tag_searches(self):
        self.saved_block(101, tags=["concrete"])
        self.saved_block(102)
        sources.discover(self.conn, neighbor_fetcher, random.Random(1))
        found = self.candidates()
        self.assertEqual(found[RAW], ("neighbor", "candidate"))
        self.assertEqual(found[SLABS], ("neighbor", "candidate"))
        self.assertEqual(found[MAKER], ("owner", "candidate"))
        self.assertEqual(found["https://www.are.na/maker/concrete-things"], ("search", "candidate"))
        self.assertNotIn("https://www.are.na/maker/secret", found)

    def test_followed_channels_and_owners_are_not_suggested(self):
        self.saved_block(101)
        self.follow(MAKER, "user")
        sources.discover(self.conn, neighbor_fetcher, random.Random(1))
        self.assertEqual(self.candidates(), {})

    def test_turned_down_sources_stay_turned_down_when_found_again(self):
        self.saved_block(101)
        self.candidate(RAW, state="declined")
        sources.discover(self.conn, neighbor_fetcher, random.Random(1))
        self.assertEqual(self.candidates()[RAW][1], "declined")

    def test_discovery_waits_between_looks_unless_forced(self):
        self.saved_block(101)
        self.assertGreater(sources.discover(self.conn, neighbor_fetcher, random.Random(1)), 0)
        self.assertEqual(sources.discover(self.conn, neighbor_fetcher, random.Random(1)), 0)
        self.assertGreater(sources.discover(self.conn, neighbor_fetcher, random.Random(1), force=True), 0)

    def test_closer_channels_are_stronger_than_giant_catch_alls(self):
        self.saved_block(101)
        self.saved_block(102)
        sources.discover(self.conn, neighbor_fetcher, random.Random(1))
        strength = {row[0]: row[1] for row in self.conn.execute("SELECT url, strength FROM candidate_sources")}
        self.assertGreater(strength[RAW], strength["https://www.are.na/maker/everything"])


class WeightTests(SourcesCase):
    def test_keeps_raise_skips_lower_and_nothing_reaches_zero(self):
        self.assertEqual(sources.learned(0, 0), 1.0)
        self.assertGreater(sources.learned(3, 0), 1.0)
        self.assertLess(sources.learned(0, 3), 1.0)
        self.assertEqual(sources.learned(0, 500), sources.LEARN_FLOOR)

    def test_unseen_images_give_no_signal(self):
        self.pulled(FOLLOWED, "new", 10)
        self.assertEqual(sources.mixed_weights(self.conn, [FOLLOWED], 0)[0], {FOLLOWED: 1.0})

    def test_suggestions_take_about_their_share_and_none_when_off(self):
        self.candidate(RAW, 0.5)
        self.candidate(SLABS, 0.2)
        weights, picked = sources.mixed_weights(self.conn, [FOLLOWED], 1 / 3)
        self.assertEqual(picked, {RAW, SLABS})
        self.assertAlmostEqual((weights[RAW] + weights[SLABS]) / sum(weights.values()), 1 / 3)
        self.assertGreater(weights[RAW], weights[SLABS])
        self.assertEqual(sources.mixed_weights(self.conn, [FOLLOWED], 0), ({FOLLOWED: 1.0}, set()))

    def test_declined_and_followed_suggestions_leave_the_mix(self):
        self.candidate(RAW, state="declined")
        self.candidate(SLABS)
        self.follow(SLABS)
        sources.settle_followed(self.conn)
        self.assertEqual(sources.mixed_weights(self.conn, [FOLLOWED], 0.5)[1], set())


class OfferTests(SourcesCase):
    def test_enough_keeps_offer_one_follow_naming_the_count(self):
        self.candidate(RAW, label="Raw Forms")
        self.candidate(SLABS)
        self.pulled(RAW, "saved", 3)
        self.pulled(SLABS, "saved", 2)
        self.assertEqual(sources.next_offer(self.conn, 3, 8), {"url": RAW, "label": "Raw Forms", "keeps": 3})

    def test_skips_with_no_keeps_drop_a_suggestion(self):
        self.candidate(RAW)
        self.candidate(SLABS)
        self.pulled(RAW, "dismissed", 8)
        self.pulled(SLABS, "dismissed", 8)
        self.pulled(SLABS, "saved", 1)
        self.assertIsNone(sources.next_offer(self.conn, 3, 8))
        self.assertEqual(self.candidates()[RAW][1], "declined")
        self.assertEqual(self.candidates()[SLABS][1], "candidate")

    def test_yes_follows_and_no_is_never_offered_again(self):
        self.candidate(RAW)
        self.candidate(SLABS)
        followed = []
        result = sources.answer(self.conn, RAW, True, lambda conn, url: followed.append(url) or {"url": url})
        self.assertEqual((result["followed"], followed), (True, [RAW]))
        sources.answer(self.conn, SLABS, False, None)
        self.pulled(SLABS, "saved", 5)
        self.assertIsNone(sources.next_offer(self.conn, 3, 8))
        self.assertEqual(self.candidates(), {RAW: ("neighbor", "followed"), SLABS: ("neighbor", "declined")})


class FeedMixTests(SourcesCase):
    def setUp(self):
        super().setUp()
        self.follow(FOLLOWED)
        self.candidate(RAW, label="Raw Forms")
        self.calls = []

        def pull(url, fetcher, rng, kind=""):
            self.calls.append(url)
            return [{"source_id": "arena", "url": f"https://arena.example/{url.rsplit('/', 1)[-1]}.jpg", "thumb": "", "width": 1,
                     "height": 1, "title": "", "creator": "", "page_url": url, "term": ""}]
        original = feed.pull
        feed.pull = pull
        self.addCleanup(setattr, feed, "pull", original)

    def test_suggested_images_are_marked_with_their_source_and_followed_ones_are_not(self):
        feed.refresh(self.conn, neighbor_fetcher, random.Random(1), share=0.5)
        self.assertIn(RAW, self.calls)
        items = {item["url"]: item for item in feed.list_items(self.conn)["items"]}
        suggested, own = items["https://arena.example/raw-forms.jpg"], items["https://arena.example/chan.jpg"]
        self.assertEqual((suggested["from_candidate"], suggested["follow_url"], suggested["follow_label"]), (True, RAW, "Raw Forms"))
        self.assertNotIn("from_candidate", own)
        self.assertNotIn("follow_url", own)

    def test_off_pulls_only_followed_sources_and_finds_none(self):
        self.saved_block(101)
        feed.refresh(self.conn, neighbor_fetcher, random.Random(1), share=0)
        self.assertEqual(set(self.calls), {FOLLOWED})
        self.assertEqual(set(self.candidates()), {RAW})

    def test_pulled_images_remember_their_source(self):
        feed.refresh(self.conn, neighbor_fetcher, random.Random(1), share=0)
        self.assertEqual([row[0] for row in self.conn.execute("SELECT origin_url FROM feed_items")], [FOLLOWED])


if __name__ == "__main__":
    unittest.main()
