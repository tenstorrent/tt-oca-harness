# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Tests for the `[coverage.<tool>]` config schema and the merge-time manifest.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runlib.config import validate_coverage_tool_table  # noqa: E402
from runlib.coverage import CoverageDiscovery, new_manifest  # noqa: E402
from runlib.models import ConfigError  # noqa: E402


class CoverageToolTable(unittest.TestCase):
    def test_waiver_files_is_not_a_key(self):
        with self.assertRaisesRegex(ConfigError, "unsupported key\\(s\\): waiver_files"):
            validate_coverage_tool_table({"waiver_files": ["w.txt"]}, "coverage.vcs")

    def test_exclude_files_is_a_list_key(self):
        validate_coverage_tool_table({"exclude_files": ["x.el"]}, "coverage.vcs")
        with self.assertRaisesRegex(ConfigError, "must be a list of strings"):
            validate_coverage_tool_table({"exclude_files": "x.el"}, "coverage.vcs")


class MergeManifest(unittest.TestCase):
    def test_waivers_key_is_present_and_empty(self):
        manifest = new_manifest(
            flow="fixture",
            tool="verilator",
            parser="verilator",
            supported_metrics=["line"],
            discovery=CoverageDiscovery(inputs=[], rejected=[], selection_source="none"),
            merged=Path("/tmp/run/cov/merged.dat"),
            root=Path("/tmp"),
            exclude_files=["run/x.el"],
        )
        self.assertEqual(manifest["waivers"], [])
        self.assertEqual(manifest["exclusions"], ["run/x.el"])
        self.assertLessEqual(
            {
                "schema_version",
                "generated_at",
                "dut",
                "tool",
                "parser",
                "status",
                "supported_metrics",
                "target",
                "build_fingerprint",
                "selection_policy",
                "selection_source",
                "inputs",
                "rejected",
                "exclusions",
                "waivers",
                "artifacts",
            },
            set(manifest),
        )


if __name__ == "__main__":
    unittest.main()
