# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import copy
import sys
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from packet_diagrams import render, validate  # noqa: E402


class PacketDiagramTests(unittest.TestCase):
    def setUp(self):
        self.packet = {
            "id": "example",
            "title": "Example packet",
            "words": [
                {
                    "word": "0",
                    "fields": [
                        {"name": "RESERVED", "bits": [31, 8]},
                        {"name": "VALUE", "bits": [7, 0]},
                    ],
                }
            ],
        }

    def test_rejects_gaps_overlaps_and_reversed_ranges(self):
        for bits in ([6, 0], [8, 0], [0, 7], [7, 1]):
            with self.subTest(bits=bits):
                packet = copy.deepcopy(self.packet)
                packet["words"][0]["fields"][1]["bits"] = bits
                with self.assertRaises(ValueError):
                    validate(packet)

    def test_rejects_unsafe_asset_names(self):
        self.packet["id"] = "../example"
        with self.assertRaises(ValueError):
            render(self.packet)

    def test_variable_payload_and_optional_field_have_text_equivalents(self):
        self.packet["words"] += [
            {"ellipsis": True},
            {
                "word": "n + 1",
                "fields": [
                    {"name": "RETURN_ARG", "bits": [31, 0], "optional": True},
                ],
            },
        ]
        svg = ET.fromstring(render(self.packet))
        desc = svg.find("{http://www.w3.org/2000/svg}desc").text
        self.assertIn("bits 31 to 8: RESERVED; bits 7 to 0: VALUE", desc)
        self.assertIn("Intermediate words omitted.", desc)
        self.assertIn("Word n + 1: bits 31 to 0: RETURN_ARG (optional)", desc)

    def test_rectangles_preserve_bit_widths(self):
        svg = ET.fromstring(render(self.packet))
        rects = svg.findall("{http://www.w3.org/2000/svg}rect")[1:]
        self.assertEqual(float(rects[0].get("width")) / float(rects[1].get("width")), 3)
        self.assertEqual(
            float(rects[0].get("x")) + float(rects[0].get("width")),
            float(rects[1].get("x")),
        )


if __name__ == "__main__":
    unittest.main()
