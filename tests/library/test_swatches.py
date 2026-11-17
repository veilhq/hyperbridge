"""Tests for swatch extraction, hue families, backfill and grouped listing."""

import io
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import hyperbridge  # noqa: E402
from bridge.library import sets, swatches  # noqa: E402
from tests.library.test_library import LibraryOpsCase  # noqa: E402


def png(color):
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (16, 16), color).save(buffer, "PNG")
    return buffer.getvalue()


class SwatchTests(LibraryOpsCase):
    def test_extract_returns_the_dominant_color(self):
        self.assertEqual(swatches.extract(png((255, 0, 0)))[0], "#ff0000")
        self.assertEqual(swatches.extract(b"not an image"), [])

    def test_family_names_hues_and_neutrals(self):
        self.assertEqual(swatches.family("#ff0000"), "Red")
        self.assertEqual(swatches.family("#00ff00"), "Green")
        self.assertEqual(swatches.family("#0000ff"), "Blue")
        self.assertEqual(swatches.family("#808080"), "Neutral")
        self.assertEqual(swatches.entry_family("[]"), swatches.NO_COLOR)

    def test_backfill_fills_only_entries_without_swatches(self):
        blank = self.add_entry("A")
        self.add_asset(blank, data=png((0, 0, 255)))
        done = self.add_entry("B")
        self.add_asset(done, data=png((255, 0, 0)))
        self.conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", (json.dumps(["#123456"]), done))
        self.assertEqual(swatches.backfill(self.conn), 1)
        self.assertEqual(library_swatches(self.conn, blank)[0], "#0000ff")
        self.assertEqual(library_swatches(self.conn, done), ["#123456"])

    def test_list_orders_by_age_title_and_source(self):
        first, second, third = self.add_entry("Banana"), self.add_entry("apple"), self.add_entry("")
        self.conn.execute("UPDATE entries SET domain = 'z.com', created_at = '2020' WHERE id = ?", (first,))
        self.conn.execute("UPDATE entries SET domain = 'a.com', created_at = '2021' WHERE id = ?", (second,))
        self.conn.execute("UPDATE entries SET domain = 'm.com', created_at = '2022' WHERE id = ?", (third,))
        self.conn.commit()
        api = hyperbridge.HyperbridgeAPI()
        titles = lambda order: [e["title"] for e in api.list_entries(order=order)["entries"]]
        self.assertEqual(titles(""), ["", "apple", "Banana"])
        self.assertEqual(titles("oldest"), ["Banana", "apple", ""])
        self.assertEqual(titles("title"), ["apple", "Banana", ""])
        self.assertEqual(titles("source"), ["apple", "", "Banana"])
        self.assertEqual(titles("junk"), ["", "apple", "Banana"])

    def test_random_order_is_stable_for_a_seed_and_pages_without_overlap(self):
        for index in range(30):
            self.add_entry(f"E{index}")
        self.conn.commit()
        api = hyperbridge.HyperbridgeAPI()
        ids = lambda seed, offset=0, limit=60: [e["id"] for e in api.list_entries(order="random", seed=seed, offset=offset, limit=limit)["entries"]]
        whole = ids(7)
        self.assertEqual(whole, ids(7))
        self.assertEqual(sorted(whole), sorted(ids(8)))
        self.assertNotEqual(whole, ids(8))
        self.assertNotEqual(whole, sorted(whole))
        self.assertEqual(ids(7, 0, 10) + ids(7, 10, 10) + ids(7, 20, 10), whole)

    def test_list_orders_by_color_as_a_gradient(self):
        shades = {"none": None, "white": "#ffffff", "blue": "#0000ff", "green": "#00ff00", "red": "#ff0000", "black": "#000000"}
        for name, shade in shades.items():
            entry = self.add_entry(name)
            self.conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", (json.dumps([shade] if shade else []), entry))
        self.conn.commit()
        titles = [e["title"] for e in hyperbridge.HyperbridgeAPI().list_entries(order="color")["entries"]]
        self.assertEqual(titles, ["red", "green", "blue", "black", "white", "none"])

    def test_list_groups_by_color_year_and_source(self):
        red, blue = self.add_entry("Red"), self.add_entry("Blue")
        self.conn.execute("UPDATE entries SET swatches = ?, year = '2020', domain = 'b.com' WHERE id = ?",
                          (json.dumps(["#ff0000"]), red))
        self.conn.execute("UPDATE entries SET swatches = ?, year = '2024', domain = 'a.com' WHERE id = ?",
                          (json.dumps(["#0000ff"]), blue))
        self.conn.commit()
        api = hyperbridge.HyperbridgeAPI()
        labels = lambda group: [e["group"] for e in api.list_entries(group=group)["entries"]]
        self.assertEqual(labels("color"), ["Red", "Blue"])
        self.assertEqual(labels("year"), ["2024", "2020"])
        self.assertEqual(sorted(labels("source")), ["a.com", "b.com"])
        made = sets.create_set("Years")
        sets.place(red, made["set"]["id"])
        sets.place(blue, made["set"]["id"])
        self.assertEqual(api.list_entries(set_id=made["set"]["id"])["years"], ["2020", "2024"])
        self.assertEqual(api.list_entries()["entries"][0]["group"], "")

    def test_source_groups_run_largest_first_and_pages_continue_in_order(self):
        for title, domain in (("A1", "a.com"), ("B1", "b.com"), ("B2", "b.com"), ("N1", ""), ("B3", "b.com"), ("A2", "a.com")):
            entry = self.add_entry(title)
            self.conn.execute("UPDATE entries SET domain = ? WHERE id = ?", (domain, entry))
        self.conn.commit()
        api = hyperbridge.HyperbridgeAPI()
        labels = [e["group"] for e in api.list_entries(group="source")["entries"]]
        self.assertEqual(labels, ["b.com"] * 3 + ["a.com"] * 2 + ["No source"])
        paged = api.list_entries(group="source", limit=2, offset=2)
        self.assertEqual([e["group"] for e in paged["entries"]], ["b.com", "a.com"])
        self.assertEqual(paged["total"], 6)

    def test_color_columns_follow_swatch_changes(self):
        entry = self.add_entry("Shifting")
        self.conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", (json.dumps(["#0000ff"]), entry))
        row = self.conn.execute("SELECT color_rank, color_family FROM entries WHERE id = ?", (entry,)).fetchone()
        self.assertEqual(swatches.family_name(row["color_family"]), "Blue")
        self.assertEqual(row["color_rank"], swatches.color_rank(json.dumps(["#0000ff"])))
        self.conn.execute("UPDATE entries SET swatches = '[]' WHERE id = ?", (entry,))
        row = self.conn.execute("SELECT color_rank, color_family FROM entries WHERE id = ?", (entry,)).fetchone()
        self.assertEqual((row["color_rank"], swatches.family_name(row["color_family"])), (swatches.NO_COLOR_RANK, swatches.NO_COLOR))

    def test_near_matches_similar_shades_only(self):
        self.assertTrue(swatches.near(json.dumps(["#ff0000", "#00ff00"]), "#f81010"))
        self.assertFalse(swatches.near(json.dumps(["#0000ff"]), "#ff0000"))
        self.assertFalse(swatches.near("[]", "#ff0000"))
        self.assertFalse(swatches.near("bad", "#ff0000"))

    def test_list_filters_by_similar_color(self):
        red, blue = self.add_entry("Red"), self.add_entry("Blue")
        self.conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", (json.dumps(["#ee1111", "#ffffff"]), red))
        self.conn.execute("UPDATE entries SET swatches = ? WHERE id = ?", (json.dumps(["#0000ff"]), blue))
        self.conn.commit()
        api = hyperbridge.HyperbridgeAPI()
        result = api.list_entries(color="#ff0000")
        self.assertEqual([e["id"] for e in result["entries"]], [red])
        self.assertEqual(result["total"], 1)
        self.assertEqual(api.list_entries(color="nope")["total"], 2)


def library_swatches(conn, entry_id):
    return json.loads(conn.execute("SELECT swatches FROM entries WHERE id = ?", (entry_id,)).fetchone()[0])


if __name__ == "__main__":
    unittest.main()
