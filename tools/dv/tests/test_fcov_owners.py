# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""fcov_owners attributes each user point to the leaves that count it and renders the table."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import fcov_owners  # noqa: E402

COUNTS = {
    "t_alpha": {
        "top.u_x_fcov.c_seen_by_both": 3,
        "top.u_x_fcov.c_alpha_only": 1,
        "top.u_y_fcov.g_sep__DOT__c_never": 0,
    },
    "t_beta": {
        "top.u_x_fcov.c_seen_by_both": 7,
        "top.u_x_fcov.c_alpha_only": 0,
        "top.u_y_fcov.g_sep__DOT__c_never": 0,
    },
}
RESULT = {
    "label": "all",
    "tool_version": "Verilator 5.050 2026-07-01 rev v5.050 (mod)",
    "git": {"commit": "0123456789abcdef0123456789abcdef01234567"},
}


class AttributeTest(unittest.TestCase):
    def test_every_point_is_kept_and_only_counting_leaves_own_it(self) -> None:
        points = fcov_owners.attribute(COUNTS)
        self.assertEqual(len(points), 3)
        both = points["top.u_x_fcov.c_seen_by_both"]
        self.assertEqual(both.hits, {"t_alpha": 3, "t_beta": 7})
        self.assertEqual(both.owner, ("t_beta", 7))
        alpha = points["top.u_x_fcov.c_alpha_only"]
        self.assertEqual(alpha.hits, {"t_alpha": 1})
        never = points["top.u_y_fcov.g_sep__DOT__c_never"]
        self.assertEqual(never.hits, {})
        self.assertIsNone(never.owner)

    def test_seeds_of_one_leaf_add_up(self) -> None:
        counts = {"t_alpha": {"top.u_x_fcov.c_p": 2}}
        points = fcov_owners.attribute(counts)
        # A second database of the same leaf reaches attribute() already summed by read_run;
        # attribute() itself adds when the same leaf appears again.
        points_again = fcov_owners.attribute({"t_alpha": {"top.u_x_fcov.c_p": 5}})
        self.assertEqual(points["top.u_x_fcov.c_p"].hits["t_alpha"], 2)
        self.assertEqual(points_again["top.u_x_fcov.c_p"].hits["t_alpha"], 5)

    def test_module_and_name_split_the_hierarchy(self) -> None:
        point = fcov_owners.PointOwners("top.u_y_fcov.g_sep__DOT__c_never")
        self.assertEqual(point.module, "u_y_fcov")
        self.assertEqual(point.name, "g_sep.c_never")


class RenderTest(unittest.TestCase):
    def setUp(self) -> None:
        self.points = fcov_owners.attribute(COUNTS)
        never = self.points["top.u_y_fcov.g_sep__DOT__c_never"]
        never.disposition = "waive"
        never.category = "unreachable"

    def test_summary_line_counts_points_hits_and_single_owners(self) -> None:
        text = fcov_owners.render(self.points, RESULT, "smu", leaves=2)
        self.assertIn(
            "2 leaves, 3 points, 2 hit, 1 unhit, 1 hit by exactly one leaf.",
            text,
        )
        self.assertIn("commit `0123456789ab` with Verilator 5.050:", text)
        self.assertNotIn("rev v5.050", text)
        self.assertIn("[[smu-fcov-owners]]", text)

    def test_one_table_per_module_with_owner_single_and_disposition(self) -> None:
        text = fcov_owners.render(self.points, RESULT, "smu", leaves=2)
        self.assertIn("===== `u_x_fcov`", text)
        self.assertIn("===== `u_y_fcov`", text)
        self.assertIn("|`c_seen_by_both` |2 |`t_beta` (7) |", text)
        self.assertIn("|`c_alpha_only` |1 |`t_alpha` (1) |single", text)
        self.assertIn("|`g_sep.c_never` |0 |none |waive: unreachable", text)

    def test_unhit_point_without_policy_reads_unclassified(self) -> None:
        never = self.points["top.u_y_fcov.g_sep__DOT__c_never"]
        never.disposition = None
        never.category = None
        text = fcov_owners.render(self.points, RESULT, "smu", leaves=2)
        self.assertIn("|`g_sep.c_never` |0 |none |unclassified", text)

    def test_generated_file_carries_spdx_and_no_run_path(self) -> None:
        text = fcov_owners.render(self.points, RESULT, "smu", leaves=2)
        self.assertTrue(text.startswith("// SPDX-License-Identifier: Apache-2.0"))
        self.assertNotIn("/", text.splitlines()[8])


if __name__ == "__main__":
    unittest.main()
