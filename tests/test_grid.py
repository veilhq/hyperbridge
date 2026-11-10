"""Tests for which stored file a library grid card shows."""

import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hyperbridge  # noqa: E402


def row(original, size, thumb="t/thumbnail-0.webp"):
    return {"original_path": original, "original_bytes": size, "thumb_path": thumb}


class GridPathTests(unittest.TestCase):
    def test_small_gifs_keep_their_original_so_they_animate(self):
        self.assertEqual(hyperbridge._grid_path(row("e/original-0.gif", 1000)), "e/original-0.gif")

    def test_large_gifs_and_other_formats_use_the_thumbnail(self):
        self.assertEqual(hyperbridge._grid_path(row("e/original-0.gif", hyperbridge.GIF_GRID_BYTES + 1)), "t/thumbnail-0.webp")
        self.assertEqual(hyperbridge._grid_path(row("e/original-0.png", 10)), "t/thumbnail-0.webp")
        self.assertEqual(hyperbridge._grid_path(row(None, None)), "t/thumbnail-0.webp")


if __name__ == "__main__":
    unittest.main()
