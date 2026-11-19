# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.regs.common.memorymap import compile_root
from tools.regs.common.windows import Decoders, WindowSizer, render_window_pkg, state_windows

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


def _compile(body: str):
    with TemporaryDirectory() as tmp:
        rdl = Path(tmp) / "top.rdl"
        rdl.write_text(BLOCKS + body, encoding="utf-8")
        return compile_root(rdl, REGBLOCK_UDP).top


class WindowSizerTest(unittest.TestCase):
    def _size(self, body: str, pages: bool = True) -> tuple[dict[str, int], list[str]]:
        sizer = WindowSizer(REGBLOCKS, WRAPPERS)
        sizer.add_top(_compile(body), pages)
        return sizer.widths(), sizer.errors

    def test_page_windows_round_each_child_up_to_whole_pages(self) -> None:
        top = _compile("addrmap top { small alone @0x1000; small copies[2] @0x4000 += 0x1000; };")
        sizer = WindowSizer(REGBLOCKS, WRAPPERS)
        package = render_window_pkg(top, sizer.add_top(top, True))
        self.assertEqual(sizer.errors, [])
        self.assertIn("package top_window_pkg;", package)
        self.assertIn("localparam longint unsigned TOP_ALONE_WINDOW_SIZE = 64'h1000;", package)
        self.assertIn("localparam longint unsigned TOP_COPIES_WINDOW_SIZE = 64'h2000;", package)

    def test_block_alone_in_a_page_decodes_the_page(self) -> None:
        widths, errors = self._size("addrmap top { small alone @0x1000; };")
        self.assertEqual(errors, [])
        self.assertEqual(widths, {"small": 12})

    def test_page_child_off_a_page_boundary_fails(self) -> None:
        _, errors = self._size("addrmap top { small alone @0x1800; };")
        self.assertEqual(errors, ["top.alone: starts at 0x1800, not on a 4 KiB boundary"])

    def test_a_stated_aperture_widens_a_page_child(self) -> None:
        top = _compile(
            """
            addrmap top {
                small alone @0x2000;
            `ifdef OCAH_DOC_MEMORY_MAP
                alone->ocah_aperture_size = 0x2000;
            `endif
            };
            """
        )
        sizer = WindowSizer(REGBLOCKS, WRAPPERS)
        package = render_window_pkg(top, sizer.add_top(top, True))
        self.assertEqual(sizer.widths(), {"small": 13})
        self.assertEqual(sizer.errors, [])
        self.assertIn("localparam longint unsigned TOP_ALONE_WINDOW_SIZE = 64'h2000;", package)

    def test_a_stated_aperture_off_its_own_alignment_fails(self) -> None:
        _, errors = self._size(
            """
            addrmap top {
                small alone @0x1000;
            `ifdef OCAH_DOC_MEMORY_MAP
                alone->ocah_aperture_size = 0x2000;
            `endif
            };
            """
        )
        self.assertEqual(
            errors,
            [
                "top.alone: owns 0x2000 bytes at 0x1000, but a register block decodes a "
                "power-of-two window whose base is a multiple of its size"
            ],
        )

    def test_pages_that_reach_the_next_child_fail(self) -> None:
        _, errors = self._size(
            """
            addrmap top {
                small low @0x0;
                wide high @0x1000;
            `ifdef OCAH_DOC_MEMORY_MAP
                low->ocah_aperture_size = 0x2000;
            `endif
            };
            """
        )
        self.assertEqual(errors, ["top.low: its pages end at 0x1FFF, past high at 0x1000"])

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


DECERR = "ocah_resp'{rresp: ocah_resp_e::DECERR, rdata: 0xBADCAB1E, bresp: ocah_resp_e::DECERR}"


class StateWindowsTest(unittest.TestCase):
    def _state(self, body: str, no_err: tuple[str, ...] = ()) -> tuple[object, list[str]]:
        top = _compile(
            "addrmap vendored { reg { field { sw = rw; hw = r; } value[31:0]; } only @0x0; };"
            + body
        )
        decoders = Decoders(
            frozenset(REGBLOCKS), frozenset(WRAPPERS), frozenset(no_err), {"small": 8}
        )
        return top, state_windows(top, True, decoders)

    @staticmethod
    def _window(node) -> tuple[int | None, str | None]:
        past = node.get_property("ocah_past_extent_resp", default=None)
        return (
            node.get_property("ocah_aperture_size", default=None),
            None if past is None else f"{past.rresp.name} 0x{int(past.rdata):X}",
        )

    def test_generated_decoders_get_their_windows_and_responses(self) -> None:
        top, errors = self._state(
            "addrmap wrap { small low @0x0; wide high @0x100; };"
            f"addrmap top {{ ocah_gap_resp = {DECERR}; small alone @0x0; wide quiet @0x1000;"
            "wrap shared @0x2000; };",
            no_err=("wide",),
        )
        self.assertEqual(errors, [])
        shared = top.get_child_by_name("shared")
        self.assertEqual(self._window(top.get_child_by_name("alone")), (0x1000, "SLVERR 0x0"))
        self.assertEqual(self._window(top.get_child_by_name("quiet")), (0x1000, "OKAY 0x0"))
        self.assertEqual(self._window(shared), (0x1000, "DECERR 0xBADCAB1E"))
        self.assertEqual(self._window(shared.get_child_by_name("low")), (0x100, "SLVERR 0x0"))
        self.assertEqual(self._window(shared.get_child_by_name("high")), (0x10, "OKAY 0x0"))

    def test_other_blocks_keep_what_the_map_states(self) -> None:
        top, errors = self._state(
            "addrmap element { small low @0x0; };"
            "addrmap wrap { element inner @0x0; small copies[2] @0x100 += 0x100; };"
            "addrmap top { vendored bought @0x0; wrap shared @0x1000; };"
        )
        self.assertEqual(errors, [])
        shared = top.get_child_by_name("shared")
        for node in (
            top.get_child_by_name("bought"),
            shared.get_child_by_name("inner"),
            shared.get_child_by_name("copies"),
        ):
            self.assertEqual(self._window(node), (None, None))

    def test_a_stated_value_the_generator_gives_fails(self) -> None:
        top, errors = self._state(
            f"""
            addrmap top {{
                small alone @0x0;
            `ifdef OCAH_DOC_MEMORY_MAP
                alone->ocah_aperture_size = 0x1000;
                alone->ocah_past_extent_resp = {DECERR};
            `endif
            }};
            """
        )
        self.assertEqual(
            errors,
            [
                "top.alone: ocah_aperture_size 0x1000 is the value the generator gives it; "
                "remove the assignment"
            ],
        )
        self.assertEqual(
            self._window(top.get_child_by_name("alone")), (0x1000, "DECERR 0xBADCAB1E")
        )


if __name__ == "__main__":
    unittest.main()
