"""Tests for filling missing tags and titles from an entry's recorded source."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import enrich  # noqa: E402
from bridge.library import library  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402


class EnrichTests(LibraryCase):
    def add(self, uid, **fields):
        values = {"title": "", "description": "", "creator": "", "domain": "", "source_service": "", "collection": "",
                  "manual_fields": "[]", **fields}
        cursor = self.conn.execute(
            "INSERT INTO entries (uid, title, description, creator, domain, source_service, collection, manual_fields,"
            " state, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'captured', 'x', 'x')",
            (uid, values["title"], values["description"], values["creator"], values["domain"],
             values["source_service"], values["collection"], values["manual_fields"]))
        return cursor.lastrowid

    def tags(self, entry_id):
        return sorted(row[0] for row in self.conn.execute(
            "SELECT t.name FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE et.entry_id = ?", (entry_id,)))

    def row(self, entry_id):
        return self.conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()

    def test_a_pinterest_pin_is_tagged_with_its_service_board_and_section(self):
        entry = self.add("a", source_service="pinterest", collection="Interiors / Lighting")
        self.assertTrue(enrich.enrich_entry(self.conn, self.row(entry)))
        self.assertEqual(self.tags(entry), ["interiors", "lighting", "pinterest"])

    def test_an_arena_block_gets_the_are_na_tag_and_its_channel(self):
        entry = self.add("a", source_service="arena", collection="Type specimens")
        enrich.enrich_entry(self.conn, self.row(entry))
        self.assertEqual(self.tags(entry), ["are.na", "type specimens"])

    def test_a_plain_web_save_is_tagged_with_its_site(self):
        entry = self.add("a", domain="www.behance.net")
        enrich.enrich_entry(self.conn, self.row(entry))
        self.assertEqual(self.tags(entry), ["behance.net"])

    def test_tagged_entries_and_entries_with_hand_edited_tags_are_left_alone(self):
        tagged = self.add("a", title="Kept", source_service="tumblr", collection="Blog")
        library.add_entry_tags(self.conn, tagged, ["mine"])
        cleared = self.add("b", title="Kept", source_service="tumblr", collection="Blog", manual_fields='["tags"]')
        self.assertFalse(enrich.enrich_entry(self.conn, self.row(tagged)))
        self.assertFalse(enrich.enrich_entry(self.conn, self.row(cleared)))
        self.assertEqual(self.tags(tagged), ["mine"])
        self.assertEqual(self.tags(cleared), [])

    def test_enriched_tags_are_marked_so_removing_them_sticks(self):
        entry = self.add("a", source_service="x")
        enrich.enrich_entry(self.conn, self.row(entry))
        self.assertIn("tags", json.loads(self.row(entry)["manual_fields"]))
        self.conn.execute("DELETE FROM entry_tags")
        self.assertEqual(enrich.backfill(self.conn), 0)
        self.assertEqual(self.tags(entry), [])

    def test_an_empty_or_url_title_gets_a_fallback_but_a_real_one_does_not(self):
        described = self.add("a", description="A long walk along the harbor at dawn")
        credited = self.add("b", title="https://example.com/x", creator="Ada", collection="Boards / Posters")
        site = self.add("c", domain="example.com")
        titled = self.add("d", title="Real title", description="Other text")
        for entry in (described, credited, site, titled):
            enrich.enrich_entry(self.conn, self.row(entry))
        self.assertEqual(self.row(described)["title"], "A long walk along the harbor at dawn")
        self.assertEqual(self.row(credited)["title"], "Posters by Ada")
        self.assertEqual(self.row(site)["title"], "example.com")
        self.assertEqual(self.row(titled)["title"], "Real title")

    def test_a_hand_edited_empty_title_stays_empty(self):
        entry = self.add("a", description="Text", manual_fields='["title"]')
        enrich.enrich_entry(self.conn, self.row(entry))
        self.assertEqual(self.row(entry)["title"], "")

    def test_backfill_skips_pending_entries_and_keeps_edit_times(self):
        self.add("a", source_service="pinterest", collection="Board")
        pending = self.add("b", source_service="pinterest", collection="Board")
        self.conn.execute("UPDATE entries SET state = 'pending' WHERE id = ?", (pending,))
        self.assertEqual(enrich.backfill(self.conn), 1)
        self.assertEqual(self.tags(pending), [])
        self.assertEqual({row[0] for row in self.conn.execute("SELECT updated_at FROM entries")}, {"x"})
        self.assertEqual(enrich.backfill(self.conn), 0)

    def test_editing_tags_by_hand_marks_them_as_yours(self):
        from bridge.library import library as lib
        entry = self.add("a")
        self.conn.commit()
        lib.update_entry(entry, {"tags": "one, two"})
        self.assertIn("tags", json.loads(self.row(entry)["manual_fields"]))


if __name__ == "__main__":
    unittest.main()
