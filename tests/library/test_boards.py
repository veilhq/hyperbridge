"""Tests for scratch boards: storage as JSON Canvas documents and promoting a board to a set."""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.library import boards  # noqa: E402
from bridge.library import sets  # noqa: E402
from tests.library.test_library import LibraryOpsCase  # noqa: E402


def image(node_id, entry, x=0, y=0):
    return {"id": node_id, "type": "file", "file": f"hyperbridge:entry/{entry}", "entry": entry,
            "x": x, "y": y, "width": 240, "height": 180}


class BoardTests(LibraryOpsCase):
    def test_create_names_untitled_boards_in_sequence(self):
        self.assertEqual(boards.create_board()["board"]["name"], "Untitled 01")
        self.assertEqual(boards.create_board("  Coastal   brutalism ")["board"]["name"], "Coastal brutalism")
        self.assertEqual(boards.create_board()["board"]["name"], "Untitled 03")

    def test_new_board_has_an_empty_canvas(self):
        made = boards.create_board("A")["board"]
        self.assertEqual(boards.get_board(made["id"])["doc"], {"nodes": [], "edges": []})
        self.assertEqual(made["items"], 0)
        self.assertIsNone(boards.get_board(999))

    def test_save_round_trips_the_document_and_counts_images(self):
        board = boards.create_board("A")["board"]["id"]
        doc = {"nodes": [image("n1", 4), image("n2", 4), {"id": "t", "type": "text", "text": "Hi", "x": 0, "y": 0,
                                                            "width": 180, "height": 180, "color": "#FFB000"}],
               "edges": []}
        saved = boards.save_board(board, json.dumps(doc))
        self.assertTrue(saved["ok"])
        self.assertEqual(saved["board"]["items"], 1)
        self.assertEqual(boards.get_board(board)["doc"], doc)

    def test_save_refuses_non_documents_and_missing_boards(self):
        board = boards.create_board("A")["board"]["id"]
        self.assertFalse(boards.save_board(board, "not json")["ok"])
        self.assertFalse(boards.save_board(board, {"nodes": "x"})["ok"])
        self.assertFalse(boards.save_board(999, {"nodes": []})["ok"])

    def test_list_puts_the_latest_touched_first(self):
        first = boards.create_board("First")["board"]["id"]
        boards.create_board("Second")
        self.conn.execute("UPDATE boards SET updated_at = '2099-01-01T00:00:00' WHERE id = ?", (first,))
        self.assertEqual([item["name"] for item in boards.list_boards()], ["First", "Second"])

    def test_rename_and_delete(self):
        board = boards.create_board("A")["board"]["id"]
        self.assertFalse(boards.rename_board(board, "  ")["ok"])
        self.assertEqual(boards.rename_board(board, "B")["board"]["name"], "B")
        self.assertTrue(boards.delete_board(board))
        self.assertFalse(boards.delete_board(board))
        self.assertEqual(boards.list_boards(), [])

    def test_add_lays_images_in_a_row_below_existing_content(self):
        board = boards.create_board("A")["board"]["id"]
        boards.save_board(board, {"nodes": [image("n1", 4, x=48, y=0)], "edges": []})
        result = boards.add_entries(board, [{"id": 5, "width": 400, "height": 200}, {"id": 4}, {"id": 6}])
        self.assertTrue(result["ok"])
        self.assertEqual(result["added"], 2)
        self.assertEqual(result["board"]["items"], 3)
        nodes = boards.get_board(board)["doc"]["nodes"][1:]
        self.assertEqual([(n["entry"], n["x"], n["y"], n["height"]) for n in nodes], [(5, 48, 228, 120), (6, 312, 228, 180)])

    def test_add_starts_an_empty_board_at_the_origin_and_wraps_rows(self):
        board = boards.create_board("A")["board"]["id"]
        boards.add_entries(board, [{"id": i, "width": 100, "height": 100} for i in range(1, 8)])
        nodes = boards.get_board(board)["doc"]["nodes"]
        self.assertEqual((nodes[0]["x"], nodes[0]["y"]), (0, 0))
        self.assertEqual((nodes[6]["x"], nodes[6]["y"]), (0, 264))

    def test_add_reports_nothing_new_and_missing_boards(self):
        board = boards.create_board("A")["board"]["id"]
        boards.add_entries(board, [{"id": 2}])
        self.assertEqual(boards.add_entries(board, [{"id": 2}, {"id": True}])["added"], 0)
        self.assertFalse(boards.add_entries(999, [{"id": 2}])["ok"])

    def test_entry_ids_skip_other_nodes_and_bad_values(self):
        doc = {"nodes": [image("a", 3), {"id": "b", "type": "file", "entry": True}, {"id": "c", "type": "text", "entry": 9},
                         image("d", 1), image("e", 3), "junk"]}
        self.assertEqual(boards.entry_ids(doc), [3, 1])


class PromoteTests(LibraryOpsCase):
    def test_promote_places_images_in_the_given_order_and_deletes_the_board(self):
        a, b, c = self.add_entry("A"), self.add_entry("B"), self.add_entry("C")
        board = boards.create_board("Mood")["board"]["id"]
        boards.save_board(board, {"nodes": [image("1", a), image("2", b), image("3", c)], "edges": []})
        result = boards.promote_board(board, "  Mood set ", [c, 999, a])
        self.assertTrue(result["ok"])
        self.assertEqual(result["set"]["name"], "Mood set")
        self.assertEqual(result["count"], 3)
        self.assertIsNone(boards.get_board(board))
        placed = {row[0] for row in self.conn.execute(
            "SELECT entry_id FROM set_entries WHERE set_id = ?", (result["set"]["id"],))}
        self.assertEqual(placed, {a, b, c})

    def test_promote_falls_back_to_the_board_name(self):
        entry = self.add_entry("A")
        board = boards.create_board("Type specimens")["board"]["id"]
        boards.save_board(board, {"nodes": [image("1", entry)]})
        self.assertEqual(boards.promote_board(board, "", None)["set"]["name"], "Type specimens")

    def test_promote_keeps_the_board_when_it_fails(self):
        entry = self.add_entry("A")
        empty = boards.create_board("Empty")["board"]["id"]
        self.assertEqual(boards.promote_board(empty, "X")["error"], "Add images before promoting.")
        sets.create_set("Taken")
        board = boards.create_board("B")["board"]["id"]
        boards.save_board(board, {"nodes": [image("1", entry)]})
        self.assertEqual(boards.promote_board(board, "taken")["error"], "That set exists.")
        self.assertIsNotNone(boards.get_board(board))
        self.assertIsNotNone(boards.get_board(empty))
        self.assertFalse(boards.promote_board(999, "X")["ok"])


if __name__ == "__main__":
    unittest.main()
