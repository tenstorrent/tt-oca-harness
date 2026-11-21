# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""Check the SMU boot specification's requirement identifiers and every citation of them."""

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SPEC = ROOT / "hw/sys/smu/boot/doc/index.adoc"
ID = r"SMU-BOOT-[A-Z0-9]+-\d{3}"
CITING = (
    "hw/**/*.adoc",
    "doc/**/*.adoc",
    "hw/**/testlists/*.toml",
    "virtual_platform/tests/**/*.toml",
)


class SmuBootRequirementTest(unittest.TestCase):
    def setUp(self):
        self.text = SPEC.read_text()
        self.defined = re.findall(rf"^\. \[\[req-({ID})\]\]\*\[({ID})\]\*", self.text, re.M)

    def test_each_requirement_is_anchored_once(self):
        self.assertTrue(self.defined)
        for anchor, tag in self.defined:
            self.assertEqual(anchor, tag)
        ids = [anchor for anchor, _ in self.defined]
        self.assertEqual(len(ids), len(set(ids)), "duplicate requirement identifier")

    def test_index_lists_exactly_the_requirements(self):
        index = self.text[self.text.index("[[smu-boot-req-index]]") :]
        listed = re.findall(rf"^\|<<req-({ID}),({ID})>>", index, re.M)
        for anchor, text in listed:
            self.assertEqual(anchor, text)
        self.assertEqual([a for a, _ in listed], [a for a, _ in self.defined])

    def test_every_citation_names_a_requirement(self):
        ids = {anchor for anchor, _ in self.defined}
        for pattern in CITING:
            for path in ROOT.glob(pattern):
                if "/gen/" in path.as_posix():
                    continue
                for cited in re.findall(ID, path.read_text()):
                    self.assertIn(cited, ids, f"{path.relative_to(ROOT)} cites {cited}")


if __name__ == "__main__":
    unittest.main()
