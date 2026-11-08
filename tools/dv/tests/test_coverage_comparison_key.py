# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Report-parsed grades of one build against one policy share one comparison key.

Run from the repository root:

    python3 -m unittest discover tools/dv/tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from runlib.coverage_parsers.imc import parse_imc_details  # noqa: E402
from runlib.coverage_parsers.urg import parse_urg_details  # noqa: E402
from runlib.coverage_policy import apply_coverage_policy  # noqa: E402
from test_coverage_thresholds import policy  # noqa: E402
from test_urg_cover_properties import ASSERTS, DASHBOARD  # noqa: E402

MORE_MATCHES = ASSERTS.replace("937667    1204", "937667    1205")

IMC_DETAIL = "metric=toggle source=rtl/dut.sv line=12 count={count} goal=1 locator=dut.a\n"


class ReportParsedKey(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def report(self, run: str, files: dict[str, str]) -> Path:
        report = Path(self.tmp.name) / "runs" / run / "cov" / "report"
        report.mkdir(parents=True)
        for name, text in files.items():
            (report / name).write_text(text)
        return report

    def urg_key(self, run: str, asserts: str = ASSERTS, **grade) -> str:
        details = parse_urg_details(
            dut="smc",
            tool="vcs",
            target=grade.pop("target", "default"),
            build_fingerprint=grade.pop("fingerprint", "fp1"),
            report_dir=self.report(run, {"dashboard.txt": DASHBOARD, "asserts.txt": asserts}),
            log_path=None,
        )
        return apply_coverage_policy(details, policy(**grade)).comparison_key

    def test_urg_location_and_hit_counts_leave_the_key(self):
        self.assertEqual(self.urg_key("first"), self.urg_key("second", MORE_MATCHES))

    def test_urg_build_target_and_policy_change_the_key(self):
        base = self.urg_key("base")
        self.assertNotEqual(base, self.urg_key("build", fingerprint="fp2"))
        self.assertNotEqual(base, self.urg_key("target", target="other"))
        self.assertNotEqual(base, self.urg_key("policy", sha="other-policy"))
        self.assertNotEqual(base, self.urg_key("epoch", scope_epoch="fixture-v2"))

    def test_imc_location_and_hit_counts_leave_the_key(self):
        keys = [
            parse_imc_details(
                dut="smc",
                tool="xcelium",
                target="default",
                build_fingerprint="fp1",
                report_dir=self.report(run, {"coverage_detail.txt": IMC_DETAIL.format(count=n)}),
                log_path=None,
            ).comparison_key
            for run, n in (("first", 0), ("second", 7))
        ]
        self.assertEqual(keys[0], keys[1])


if __name__ == "__main__":
    unittest.main()
