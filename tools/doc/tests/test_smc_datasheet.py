# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import unittest
from pathlib import Path


class SmcDatasheetTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = Path(__file__).resolve().parents[3]
        self.source = (self.root / "doc/datasheets/src/smc.adoc").read_text(encoding="utf-8")
        self.diagram = (self.root / "doc/datasheets/assets/smc-block-diagram.svg").read_text(
            encoding="utf-8"
        )

    def test_review_language_is_consistent(self) -> None:
        self.assertIn("checked-in production Boot ROM image", self.source)
        self.assertIn("Production Boot ROM source, build flow, and documentation", self.source)
        self.assertNotIn("optional SEP", self.source)
        self.assertNotIn("management firmware", self.source)
        self.assertNotIn("straps", self.source)
        self.assertNotIn("Work-in-progress boot-ROM", self.source)
        self.assertIn("SMC in a chiplet system", self.diagram)
        self.assertIn("Dashed boundary: one chiplet.", self.diagram)
        self.assertNotIn("OCAH chiplet", self.diagram)
        self.assertNotIn("Optional SEP", self.diagram)

    def test_points_to_the_live_verification_dashboard(self) -> None:
        # Verification and maturity status is published on the live dashboard
        # rather than as hardcoded counts.
        self.assertIn("dashboard.html", self.source)
        self.assertIn("current verification and maturity status", self.source.lower())

    def test_does_not_hardcode_maturity_status(self) -> None:
        self.assertNotIn("OCAH SMC is beta RTL.", self.source)


if __name__ == "__main__":
    unittest.main()
