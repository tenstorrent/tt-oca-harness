# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""urg's cover properties are reported as the `user` family, with one observation per row."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

from runlib.coverage_parsers.urg import parse_urg_details  # noqa: E402

DASHBOARD = (
    "Dashboard\n\nTotal Coverage Summary \n"
    "SCORE  LINE   COND   TOGGLE FSM    BRANCH ASSERT GROUP  \n"
    " 71.89  98.43  83.91  20.29  64.29  94.79  86.88  54.67 \n"
)

ASSERTS = """Summary for Assertions
                 NUMBER PERCENT
Total Number          4  100.00
Uncovered             1   25.00
Success               3   75.00

-------------------------------------------------------------------------------

Summary for Cover Properties
             NUMBER PERCENT
Total Number      5  100.00
Uncovered         2   40.00
Matches           3   60.00

-------------------------------------------------------------------------------

Detail Report for Assertions

Assertions Uncovered:
            ASSERTIONS            CATEGORY SEVERITY ATTEMPTS REAL SUCCESSES FAILURES INCOMPLETE
axi_pkg.wrap_boundary.unnamed$$_0        0        0        0              0        0          0

-------------------------------------------------------------------------------

Detail Report for Cover Properties

Cover Properties Uncovered:
                            COVER PROPERTIES                            CATEGORY SEVERITY ATTEMPTS MATCHES INCOMPLETE
top.u_clk_fcov.c_clk_periph_stalled_window                                     0        0   937667       0          0
top.u_clk_fcov.c_clk_ratio_smc_equal_ref                                       0        0   937667       0          0

Cover Properties Matches:
                            COVER PROPERTIES                            CATEGORY SEVERITY ATTEMPTS MATCHES INCOMPLETE
top.u_clk_fcov.c_clk_gate_open                                                 0        0   937667    1204          0
top.u_map_fcov.c_wdt_region                                                    0        0   937667      12          0
top.u_map_fcov.c_gpio_region                                                   0        0   937667       3          0
"""

ASSERTS_WITH_EXCLUSION = ASSERTS.replace(
    "Total Number      5  100.00\nUncovered         2   40.00\nMatches           3   60.00\n",
    "Total Number      5  100.00\nUncovered         1   20.00\nExcluded          1   20.00\nMatches           3   60.00\n",
)


class UrgCoverPropertiesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.report = Path(self.tmp.name) / "report"
        self.report.mkdir()
        (self.report / "dashboard.txt").write_text(DASHBOARD)

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def parse(self, raw_report_dir: Path | None = None):
        return parse_urg_details(
            dut="smc",
            tool="vcs",
            target=None,
            build_fingerprint=None,
            report_dir=self.report,
            log_path=None,
            raw_report_dir=raw_report_dir,
        )

    def test_summary_row_becomes_the_user_family(self) -> None:
        (self.report / "asserts.txt").write_text(ASSERTS)
        details = self.parse()
        by_family = {record.metric_family: record for record in details.metrics}
        self.assertIn("user", by_family)
        user = by_family["user"]
        self.assertEqual(user.native_metric, "cover_property")
        self.assertEqual((user.covered, user.total, user.excluded), (3, 5, 0))
        self.assertEqual(user.raw_percent, 60.0)
        self.assertEqual(user.effective_percent, 60.0)
        # The dashboard's ASSERT column still reports the mixed urg figure.
        self.assertEqual(by_family["assertion"].raw_percent, 86.88)

    def test_each_detail_row_is_an_observation_with_its_hierarchy(self) -> None:
        (self.report / "asserts.txt").write_text(ASSERTS)
        details = self.parse()
        user = [o for o in details.observations if o.metric_family == "user"]
        self.assertEqual(len(user), 5)
        by_name = {o.hierarchy: o for o in user}
        self.assertFalse(by_name["top.u_clk_fcov.c_clk_periph_stalled_window"].covered)
        self.assertEqual(by_name["top.u_clk_fcov.c_clk_periph_stalled_window"].count, 0)
        self.assertTrue(by_name["top.u_map_fcov.c_gpio_region"].covered)
        self.assertEqual(by_name["top.u_map_fcov.c_gpio_region"].count, 3)
        self.assertTrue(all(o.native_metric == "cover_property" for o in user))
        # The assertion row is not a cover property and is not a user observation.
        self.assertNotIn("axi_pkg.wrap_boundary.unnamed$$_0", by_name)
        self.assertTrue(details.details_available)

    def test_excluded_properties_leave_the_effective_population(self) -> None:
        (self.report / "asserts.txt").write_text(ASSERTS_WITH_EXCLUSION)
        details = self.parse()
        user = next(record for record in details.metrics if record.metric_family == "user")
        self.assertEqual((user.covered, user.total, user.excluded), (3, 5, 1))
        self.assertEqual(user.raw_percent, 60.0)
        self.assertEqual(user.effective_percent, 75.0)

    def test_an_accepted_waiver_leaves_the_effective_population(self) -> None:
        (self.report / "asserts.txt").write_text(ASSERTS)
        details = self.parse()
        waived = next(
            observation
            for observation in details.observations
            if observation.hierarchy == "top.u_clk_fcov.c_clk_periph_stalled_window"
        )
        waived.disposition = "waive"
        waived.status = "accepted"
        details.finalize()
        user = next(record for record in details.metrics if record.metric_family == "user")
        self.assertEqual((user.covered, user.total, user.excluded), (3, 5, 0))
        self.assertEqual(user.raw_percent, 60.0)
        self.assertEqual(user.effective_percent, 75.0)

    def test_raw_report_supplies_the_raw_user_figure(self) -> None:
        (self.report / "asserts.txt").write_text(ASSERTS_WITH_EXCLUSION)
        raw = Path(self.tmp.name) / "report_raw"
        raw.mkdir()
        (raw / "dashboard.txt").write_text(DASHBOARD)
        (raw / "asserts.txt").write_text(ASSERTS)
        details = self.parse(raw_report_dir=raw)
        user = next(record for record in details.metrics if record.metric_family == "user")
        self.assertEqual(user.raw_percent, 60.0)
        self.assertEqual(user.effective_percent, 75.0)

    def test_no_asserts_file_means_no_user_family(self) -> None:
        details = self.parse()
        self.assertNotIn("user", {record.metric_family for record in details.metrics})


if __name__ == "__main__":
    unittest.main()
