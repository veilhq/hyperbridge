"""Tests for renaming, merging and deleting tags."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.exchange import transfer  # noqa: E402
from bridge.library import library  # noqa: E402
from tests.core.test_db import LibraryCase  # noqa: E402


class TagManagementTests(LibraryCase):
    def setUp(self):
        super().setUp()
        self.first = self.add_entry("First")
        self.second = self.add_entry("Second")
        self.third = self.add_entry("Third")
        library.add_tags([self.first, self.second], "poster")
        library.add_tags([self.second, self.third], "Posters")
        library.add_tags([self.third], "lonely")
        self.conn.commit()

    def tags(self, entry_id):
        return sorted(row[0] for row in self.conn.execute(
            "SELECT t.name FROM entry_tags et JOIN tags t ON t.id = et.tag_id WHERE et.entry_id = ?", (entry_id,)))

    def row(self, entry_id):
        return self.conn.execute("SELECT * FROM entries WHERE id = ?", (entry_id,)).fetchone()

    def test_rename_changes_the_tag_on_every_entry(self):
        result = library.rename_tag("poster", "print")
        self.assertEqual(result, {"ok": True, "merged": False, "count": 2})
        self.assertEqual(self.tags(self.first), ["print"])
        self.assertEqual(self.tags(self.second), ["Posters", "print"])

    def test_a_case_only_rename_is_not_a_merge(self):
        result = library.rename_tag("poster", "POSTER")
        self.assertEqual((result["ok"], result["merged"]), (True, False))
        self.assertEqual(self.tags(self.first), ["POSTER"])

    def test_renaming_into_an_existing_tag_merges_without_duplicates(self):
        result = library.rename_tag("poster", "posters")
        self.assertEqual((result["ok"], result["merged"]), (True, True))
        self.assertEqual(self.tags(self.first), ["Posters"])
        self.assertEqual(self.tags(self.second), ["Posters"])
        names = [item["name"] for item in library.list_tags()]
        self.assertEqual(sorted(names), ["Posters", "lonely"])

    def test_rename_rejects_an_empty_name_and_a_missing_tag(self):
        self.assertFalse(library.rename_tag("poster", "   ")["ok"])
        self.assertFalse(library.rename_tag("nope", "x")["ok"])

    def test_delete_removes_the_tag_everywhere(self):
        self.assertEqual(library.delete_tag("poster"), 2)
        self.assertEqual(self.tags(self.first), [])
        self.assertNotIn("poster", [item["name"] for item in library.list_tags()])
        self.assertEqual(library.delete_tag("poster"), 0)

    def test_delete_single_use_tags_keeps_shared_ones(self):
        self.assertEqual(library.delete_single_use_tags(), 1)
        self.assertEqual(sorted(item["name"] for item in library.list_tags()), ["Posters", "poster"])

    def test_changed_entries_are_stamped_and_marked_so_sync_and_enrichment_respect_them(self):
        self.conn.execute("UPDATE entries SET updated_at = '2026-01-01T00:00:00'")
        self.conn.commit()
        library.delete_tag("lonely")
        row = self.row(self.third)
        self.assertGreater(row["updated_at"], "2026-01-01T00:00:00")
        self.assertIn("tags", json.loads(row["manual_fields"]))
        self.assertEqual(self.row(self.first)["updated_at"], "2026-01-01T00:00:00")
        library.rename_tag("poster", "print")
        self.assertEqual(transfer._entry_record(self.conn, self.row(self.first))["tags"], ["print"])


if __name__ == "__main__":
    unittest.main()
