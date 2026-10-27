# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unit tests for the covergroup bins a Verilator coverage grade counts.

Verilator writes every covergroup bin to coverage.dat, its ignore, illegal and default
bins included, each tagged with `bin_type`. None is a coverage goal, so the summary
figures and the detailed observations both leave them out.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.coverage import parse_coverage_report  # noqa: E402
from runlib.coverage_parsers.verilator import parse_verilator_details  # noqa: E402

# (bin, bin_type, count): four goals, three hit, beside a hit ignore bin, an illegal bin and a
# hit default bin.
BINS = (
    ("a0", None, 3),
    ("a1", None, 1),
    ("a2", None, 2),
    ("a3", None, 0),
    ("a4", "ignore", 5),
    ("bad", "illegal", 0),
    ("other", "default", 4),
)


def coverage_dat() -> str:
    lines = ["# SystemC::Coverage-3"]
    for name, bin_type, count in BINS:
        fields = [
            ("t", "covergroup"),
            ("page", "v_covergroup/cg"),
            ("f", "probe.sv"),
            ("l", "6"),
            ("bin", name),
            *([("bin_type", bin_type)] if bin_type else []),
            ("h", f"cg.cp_a.{name}"),
        ]
        key = "".join(f"\x01{field}\x02{value}" for field, value in fields)
        lines.append(f"C '{key}' {count}")
    return "\n".join(lines) + "\n"


class NonGoalBins(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.merged = Path(tmp.name) / "merged.dat"
        self.merged.write_text(coverage_dat(), encoding="utf-8")

    def test_the_summary_counts_goal_bins_only(self):
        metrics, overall = parse_coverage_report(
            parser="verilator", report_dir=self.merged.parent, merged=self.merged
        )
        self.assertEqual(metrics, {"functional": 75.0})
        self.assertEqual(overall, 75.0)

    def test_the_details_observe_goal_bins_only(self):
        details = parse_verilator_details(
            dut="fixture", tool="verilator", target=None, build_fingerprint=None, merged=self.merged
        )
        self.assertEqual(
            sorted((o.hierarchy, o.covered) for o in details.observations),
            [
                ("cg.cp_a.a0", True),
                ("cg.cp_a.a1", True),
                ("cg.cp_a.a2", True),
                ("cg.cp_a.a3", False),
            ],
        )
        self.assertEqual(details.warnings, [])


if __name__ == "__main__":
    unittest.main()
