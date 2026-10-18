# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the regression submit order (``--leaf-order-from``).

A regression ends when its last leaf ends, so the longest leaves start first. A leaf
without an earlier duration starts before every timed leaf, and without the option the
order is the testlist order.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.cli import leaf_order  # noqa: E402


def _leaves(*items: str) -> list[dict]:
    return [{"id": i, "item": item, "seed": 100 + i} for i, item in enumerate(items)]


class LeafOrderTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.root = Path(self._dir.name)

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _result(self, stages: list[dict]) -> str:
        path = self.root / "result.json"
        path.write_text(json.dumps({"stages": stages}))
        return str(path)

    def test_without_option_keeps_testlist_order(self) -> None:
        leaves = _leaves("a", "b", "c")
        self.assertEqual(leaf_order(leaves, None, self.root), leaves)

    def test_longest_first_and_unknown_first(self) -> None:
        prior = self._result(
            [
                {"name": "sim", "item": "a", "duration_sec": 5.0},
                {"name": "sim", "item": "b", "duration_sec": 50.0},
                {"name": "sim", "item": "c", "duration_sec": 20.0},
                {"name": "sim", "item": "c", "duration_sec": 70.0},
                {"name": "hdl_compile", "item": "a", "duration_sec": 900.0},
            ]
        )
        ordered = leaf_order(_leaves("a", "b", "new", "c"), prior, self.root)
        self.assertEqual([leaf["item"] for leaf in ordered], ["new", "c", "b", "a"])

    def test_ids_and_seeds_unchanged(self) -> None:
        leaves = _leaves("a", "b")
        prior = self._result([{"name": "sim", "item": "a", "duration_sec": 9.0}])
        ordered = leaf_order(leaves, prior, self.root)
        self.assertEqual(sorted(ordered, key=lambda leaf: leaf["id"]), leaves)

    def test_unreadable_file_stops_the_run(self) -> None:
        with self.assertRaises(SystemExit):
            leaf_order(_leaves("a"), str(self.root / "missing.json"), self.root)


if __name__ == "__main__":
    unittest.main()
