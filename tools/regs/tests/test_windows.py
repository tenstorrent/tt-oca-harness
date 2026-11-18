# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.regs.common.memorymap import compile_root
from tools.regs.common.windows import WindowSizer

REGBLOCK_UDP = Path(__file__).resolve().parents[3] / "hw/common/regs/regblock_udps.rdl"

BLOCKS = """
addrmap small {
    reg { field { sw = rw; hw = r; } value[31:0]; } first @0x0;
    reg { field { sw = rw; hw = r; } value[31:0]; } second @0x4;
};
addrmap wide {
    reg { regwidth = 64; field { sw = rw; hw = r; } value[63:0]; } only @0x0;
};
"""

REGBLOCKS = ("small", "wide")
WRAPPERS = ("wrap", "element")


class WindowSizerTest(unittest.TestCase):
    def _size(self, body: str, pages: bool = True) -> tuple[dict[str, int], list[str]]:
        with TemporaryDirectory() as tmp:
            rdl = Path(tmp) / "top.rdl"
            rdl.write_text(BLOCKS + body, encoding="utf-8")
            root = compile_root(rdl, REGBLOCK_UDP)
        sizer = WindowSizer(REGBLOCKS, WRAPPERS)
        sizer.add_top(root.top, pages)
        return sizer.widths(), sizer.errors

    def test_block_alone_in_a_page_decodes_the_page(self) -> None:
        widths, errors = self._size("addrmap top { small alone @0x1000; };")
        self.assertEqual(errors, [])
        self.assertEqual(widths, {"small": 12})

    def test_page_child_off_a_page_boundary_fails(self) -> None:
        _, errors = self._size("addrmap top { small alone @0x1800; };")
        self.assertEqual(errors, ["top.alone: starts at 0x1800, not on a 4 KiB boundary"])

    def test_wrapper_children_own_the_space_to_the_next_child(self) -> None:
        widths, errors = self._size(
            "addrmap wrap { small low @0x0; wide high @0x100; }; addrmap top { wrap shared @0x0; };"
        )
        self.assertEqual(errors, [])
        self.assertEqual(widths, {"small": 8})

    def test_last_child_of_an_array_element_owns_the_rest_of_the_element(self) -> None:
        widths, errors = self._size(
            "addrmap element { small low @0x0; small high @0x80; };"
            "addrmap wrap { element copies[2] @0x0 += 0x100; };"
            "addrmap top { wrap shared @0x0; };"
        )
        self.assertEqual(errors, [])
        self.assertEqual(widths, {"small": 7})

    def test_space_that_is_not_a_power_of_two_fails(self) -> None:
        _, errors = self._size(
            "addrmap wrap { small low @0x0; small high @0x300; }; addrmap top { wrap shared @0x0; };"
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("top.shared.low: owns 0x300 bytes at 0x0", errors[0])

    def test_instances_share_the_smallest_owned_window(self) -> None:
        widths, errors = self._size(
            "addrmap wrap { small low @0x0; small mid @0x400; wide high @0x800; };"
            """
            addrmap top {
                wrap left @0x0;
                wrap right @0x1000;
            `ifdef OCAH_DOC_MEMORY_MAP
                left.low->ocah_aperture_size = 0x200;
            `endif
            };
            """
        )
        self.assertEqual(widths, {"small": 10})
        self.assertEqual(
            errors, ["top.left.low: ocah_aperture_size is 0x200, but small decodes 0x400"]
        )

    def test_stride_narrower_than_the_default_decode_keeps_it(self) -> None:
        widths, errors = self._size(
            "addrmap wrap { wide copies[4] @0x0 += 0x8; }; addrmap top { wrap shared @0x0; };"
        )
        self.assertEqual(errors, [])
        self.assertEqual(widths, {})


if __name__ == "__main__":
    unittest.main()
