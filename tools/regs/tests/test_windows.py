# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.regs.common.memorymap import compile_root
from tools.regs.common.windows import (
    WindowSizer,
    render_window_pkg,
    render_windows,
    state_windows,
)

REGBLOCK_UDP = Path(__file__).resolve().parents[3] / "hw/common/regs/regblock_udps.rdl"

BLOCKS = """
addrmap small {
    reg { field { sw = rw; hw = r; } value[31:0]; } first @0x0;
    reg { field { sw = rw; hw = r; } value[31:0]; } second @0x4;
};
addrmap wide {
    reg { regwidth = 64; field { sw = rw; hw = r; } value[63:0]; } only @0x0;
};
addrmap vendored {
    reg { field { sw = rw; hw = r; } value[31:0]; } only @0x0;
};
"""

REGBLOCKS = ("small", "wide")
WRAPPERS = ("wrap", "element")

OKAY = {"rresp": "OKAY", "rdata": "0x0", "bresp": "OKAY"}
SLVERR = {"rresp": "SLVERR", "rdata": "0x0", "bresp": "SLVERR"}
DECERR = {"rresp": "DECERR", "rdata": "0xBADCAB1E", "bresp": "DECERR"}
DECERR_RDL = "ocah_resp'{rresp: ocah_resp_e::DECERR, rdata: 0xBADCAB1E, bresp: ocah_resp_e::DECERR}"
ADOPTER_RDL = "ocah_resp'{rresp: ocah_resp_e::ADOPTER, rdata: 0x0, bresp: ocah_resp_e::ADOPTER}"


def _compile(body: str):
    with TemporaryDirectory() as tmp:
        rdl = Path(tmp) / "top.rdl"
        rdl.write_text(BLOCKS + body, encoding="utf-8")
        return compile_root(rdl, REGBLOCK_UDP).top


def _size(body: str, pages: bool = True, **answers):
    top = _compile(body)
    sizer = WindowSizer(REGBLOCKS, WRAPPERS, **answers)
    sizer.add_top(top, pages)
    return top, sizer.sized(), sizer.errors


def _stated(body: str) -> str:
    return f"\n`ifdef OCAH_DOC_MEMORY_MAP\n{body}\n`endif\n"


class WindowSizerTest(unittest.TestCase):
    def sizes(self, sized) -> dict[str, int]:
        return {path: int(unit["size"], 16) for path, unit in sized["windows"].items()}

    def test_page_children_own_whole_pages(self) -> None:
        _, sized, errors = _size(
            "addrmap top { small alone @0x1000; small copies[2] @0x4000 += 0x1000;"
            " vendored bought @0x8000; };"
        )
        self.assertEqual(errors, [])
        self.assertEqual(
            self.sizes(sized), {"top.alone": 0x1000, "top.copies": 0x2000, "top.bought": 0x1000}
        )
        self.assertEqual(sized["addr_widths"], {"small": 12})
        package = render_window_pkg("top", sized)
        self.assertIn("package top_window_pkg;", package)
        self.assertIn("localparam longint unsigned TOP_ALONE_WINDOW_SIZE = 64'h1000;", package)
        self.assertIn("localparam longint unsigned TOP_COPIES_WINDOW_SIZE = 64'h2000;", package)
        self.assertIn("localparam longint unsigned TOP_BOUGHT_WINDOW_SIZE = 64'h1000;", package)

    def test_page_child_off_a_page_boundary_fails(self) -> None:
        _, _, errors = _size("addrmap top { small alone @0x1800; };")
        self.assertEqual(errors, ["top.alone: starts at 0x1800, not on a 4 KiB boundary"])

    def test_a_line_states_only_a_wider_window_for_a_page_child(self) -> None:
        body = "addrmap top {{ vendored bought @0x1000; vendored other @0x4000; {} }};"
        _, sized, errors = _size(body.format(_stated("bought->ocah_aperture_size = 0x2000;")))
        self.assertEqual(errors, [])
        self.assertEqual(self.sizes(sized), {"top.other": 0x1000})
        self.assertNotIn("TOP_BOUGHT", render_window_pkg("top", sized))
        _, _, errors = _size(body.format(_stated("bought->ocah_aperture_size = 0x1000;")))
        self.assertEqual(
            errors,
            [
                "top.bought: ocah_aperture_size 0x1000 does not widen the 0x1000 window the "
                "map gives the unit; remove the assignment"
            ],
        )

    def test_an_adopter_window_is_not_sized(self) -> None:
        _, sized, errors = _size(
            "addrmap top { small alone @0x0; vendored theirs @0x1000;"
            + _stated(f"theirs->ocah_hole_resp = {ADOPTER_RDL};")
            + "};"
        )
        self.assertEqual(errors, [])
        self.assertEqual(self.sizes(sized), {"top.alone": 0x1000})

    def test_wrapper_children_own_the_space_to_the_next_child(self) -> None:
        _, sized, errors = _size(
            "addrmap wrap { small low @0x0; vendored mid @0x100; wide high @0x400;"
            " vendored last @0x800; }; addrmap top { wrap shared @0x0; };"
        )
        self.assertEqual(errors, [])
        self.assertEqual(sized["addr_widths"], {"small": 8, "wide": 10})
        self.assertEqual(
            self.sizes(sized),
            {
                "top.shared": 0x1000,
                "top.shared.low": 0x100,
                "top.shared.mid": 0x300,
                "top.shared.high": 0x400,
                "top.shared.last": 0x800,
            },
        )

    def test_a_line_states_only_a_narrower_window_for_a_wrapper_child(self) -> None:
        body = (
            "addrmap wrap {{ vendored low @0x0; small high @0x800; {} }};"
            "addrmap top {{ wrap shared @0x0; }};"
        )
        _, sized, errors = _size(body.format(_stated("low->ocah_aperture_size = 0x80;")))
        self.assertEqual(errors, [])
        self.assertNotIn("top.shared.low", sized["windows"])
        _, _, errors = _size(body.format(_stated("low->ocah_aperture_size = 0x800;")))
        self.assertEqual(
            errors,
            [
                "top.shared.low: ocah_aperture_size 0x800 does not narrow the 0x800 window the "
                "map gives the unit; remove the assignment"
            ],
        )

    def test_last_child_of_an_array_element_owns_the_rest_of_the_element(self) -> None:
        _, sized, errors = _size(
            "addrmap element { small low @0x0; small high @0x80; };"
            "addrmap wrap { element copies[2] @0x0 += 0x100; };"
            "addrmap top { wrap shared @0x0; };"
        )
        self.assertEqual(errors, [])
        self.assertEqual(sized["addr_widths"], {"small": 7})

    def test_space_that_is_not_a_power_of_two_fails(self) -> None:
        _, _, errors = _size(
            "addrmap wrap { small low @0x0; small high @0x300; }; addrmap top { wrap shared @0x0; };"
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("top.shared.low: owns 0x300 bytes at 0x0", errors[0])

    def test_instances_share_the_smallest_owned_window(self) -> None:
        _, sized, errors = _size(
            "addrmap wrap { small low @0x0; small mid @0x400; wide high @0x800; };"
            "addrmap top { wrap left @0x0; wrap right @0x1000; };"
        )
        self.assertEqual(errors, [])
        self.assertEqual(sized["addr_widths"], {"small": 10})
        self.assertEqual(sized["windows"]["top.right.low"]["size"], "0x400")

    def test_an_array_owns_its_strides(self) -> None:
        _, sized, errors = _size(
            "addrmap wrap { wide copies[4] @0x0 += 0x8; small spread[2] @0x100 += 0x40; };"
            "addrmap top { wrap shared @0x0; };"
        )
        self.assertEqual(errors, [])
        self.assertEqual(sized["addr_widths"], {"small": 6})
        self.assertEqual(sized["windows"]["top.shared.copies"]["size"], "0x20")
        self.assertEqual(sized["windows"]["top.shared.spread"]["size"], "0x80")

    def test_a_register_block_in_another_map_keeps_the_window_it_needs(self) -> None:
        _, sized, errors = _size(
            "addrmap top { small low @0x0; vendored bought @0x400; wide high @0x1000; };",
            pages=False,
        )
        self.assertEqual(errors, [])
        self.assertEqual(sized["addr_widths"], {})
        self.assertEqual(self.sizes(sized), {"top.low": 0x8, "top.high": 0x10})

    def test_decoders_answer_as_their_options_make_them(self) -> None:
        _, sized, errors = _size(
            "addrmap wrap { small low @0x0; wide high @0x100; };"
            "addrmap top { small alone @0x0; wide quiet[2] @0x1000 += 0x10; wrap shared @0x2000;"
            + _stated(f"ocah_gap_resp = {DECERR_RDL};")
            + "};",
            err_check=("small",),
            no_err=("wide",),
        )
        self.assertEqual(errors, [])
        windows = sized["windows"]
        self.assertEqual(windows["top.alone"], {"size": "0x1000", "hole": SLVERR, "past": SLVERR})
        self.assertEqual(windows["top.quiet"], {"size": "0x1000", "hole": OKAY, "past": OKAY})
        self.assertEqual(windows["top.shared"], {"size": "0x1000", "past": DECERR})
        self.assertEqual(
            windows["top.shared.low"], {"size": "0x100", "hole": SLVERR, "past": SLVERR}
        )
        self.assertEqual(windows["top.shared.high"], {"size": "0x10", "hole": OKAY, "past": OKAY})

    def test_a_line_may_not_state_what_the_generator_derives(self) -> None:
        _, _, errors = _size(
            "addrmap wrap { small low @0x0; wide high @0x100; };"
            "addrmap top { small alone @0x0; wrap shared @0x1000;"
            + _stated(
                f"ocah_gap_resp = {DECERR_RDL};"
                "alone->ocah_aperture_size = 0x1000;"
                f"alone->ocah_hole_resp = {DECERR_RDL};"
                f"shared->ocah_past_extent_resp = {DECERR_RDL};"
                f"shared.low->ocah_past_extent_resp = {DECERR_RDL};"
            )
            + "};"
        )
        self.assertEqual(
            errors,
            [
                "top.alone: states ocah_aperture_size, which the generator derives for a "
                "register block; remove the assignment",
                "top.alone: states ocah_hole_resp, which the generator derives for a "
                "register block; remove the assignment",
                "top.shared: states ocah_past_extent_resp, which the generator derives for a "
                "wrapper placed in a page top; remove the assignment",
                "top.shared.low: states ocah_past_extent_resp, which the generator derives for "
                "a register block; remove the assignment",
            ],
        )

    def test_the_record_renders_as_json(self) -> None:
        _, sized, _ = _size("addrmap top { small alone @0x1000; };")
        self.assertEqual(json.loads(render_windows(sized)), sized)


class StateWindowsTest(unittest.TestCase):
    @staticmethod
    def _window(node) -> tuple[int | None, str | None, str | None]:
        def text(name: str) -> str | None:
            value = node.get_property(name, default=None)
            return None if value is None else f"{value.rresp.name} 0x{int(value.rdata):X}"

        return (
            node.get_property("ocah_aperture_size", default=None),
            text("ocah_hole_resp"),
            text("ocah_past_extent_resp"),
        )

    def test_the_map_takes_the_sized_windows_and_responses(self) -> None:
        top, sized, errors = _size(
            "addrmap wrap { small low @0x0; vendored bought @0x100; };"
            "addrmap top { small alone @0x0; vendored silent @0x1000; vendored spoken @0x2000;"
            " wrap shared @0x3000;"
            + _stated(
                f"ocah_gap_resp = {DECERR_RDL};"
                f"spoken->ocah_past_extent_resp = {DECERR_RDL};"
                f"shared.bought->ocah_past_extent_resp = {DECERR_RDL};"
            )
            + "};"
        )
        self.assertEqual(errors, [])
        state_windows(top, sized["windows"])
        shared = top.get_child_by_name("shared")
        self.assertEqual(
            self._window(top.get_child_by_name("alone")), (0x1000, "OKAY 0x0", "SLVERR 0x0")
        )
        self.assertEqual(self._window(top.get_child_by_name("silent")), (0x1000, None, None))
        self.assertEqual(
            self._window(top.get_child_by_name("spoken")), (0x1000, None, "DECERR 0xBADCAB1E")
        )
        self.assertEqual(self._window(shared), (0x1000, None, "DECERR 0xBADCAB1E"))
        self.assertEqual(
            self._window(shared.get_child_by_name("low")), (0x100, "OKAY 0x0", "SLVERR 0x0")
        )
        self.assertEqual(
            self._window(shared.get_child_by_name("bought")), (0xF00, None, "DECERR 0xBADCAB1E")
        )

    def test_a_window_the_map_does_not_place_fails(self) -> None:
        top = _compile("addrmap top { small alone @0x0; };")
        with self.assertRaisesRegex(ValueError, "does not place: top.gone"):
            state_windows(top, {"top.gone": {"size": "0x1000"}, "other.unit": {"size": "0x8"}})


if __name__ == "__main__":
    unittest.main()
