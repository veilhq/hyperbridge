"""Tests for the combined startup backfill runner."""

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bridge.ingest import backfill  # noqa: E402


class RunAllTests(unittest.TestCase):
    def run_with(self, local, source, enrich_step):
        order = []

        def named(name, behavior):
            def step(*args):
                order.append(name)
                if behavior == "fail":
                    raise RuntimeError(name)
            return step

        with mock.patch.object(backfill, "local_steps", lambda conn: [(n, named(n, b)) for n, b in local]), \
                mock.patch.object(backfill, "source_steps", lambda conn, fetcher: [(n, named(n, b)) for n, b in source]), \
                mock.patch.object(backfill.enrich, "backfill", named("enrich", enrich_step)):
            failed = backfill.run_all(object(), fetcher=object())
        return order, failed

    def test_runs_local_steps_then_sources_then_enrichment(self):
        order, failed = self.run_with([("a", "ok"), ("b", "ok")], [("c", "ok")], "ok")
        self.assertEqual((order, failed), (["a", "b", "c", "enrich"], []))

    def test_a_failing_step_is_reported_and_the_rest_still_run(self):
        order, failed = self.run_with([("a", "fail"), ("b", "ok")], [("c", "fail")], "ok")
        self.assertEqual((order, failed), (["a", "b", "c", "enrich"], ["a", "c"]))


if __name__ == "__main__":
    unittest.main()
