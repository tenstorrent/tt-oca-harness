# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.regs.common.memorymap import (
    build_views,
    check_regblock_responses,
    compile_root,
    load_config,
    render_adoc,
    render_py,
)
from tools.regs.stamp_spdx import stamp_file

REGBLOCK_UDP = Path(__file__).resolve().parents[3] / "hw/common/regs/regblock_udps.rdl"

UDP = """
property ocah_aperture_size {
    component = addrmap | regfile | reg | mem;
    type = longint unsigned;
};
"""

RDL = """
addrmap child {
    name = "Child";
    desc = "Contains | escaped";
    reg {
        field { sw = rw; hw = r; } value[31:0];
    } control @0x0;
};
addrmap top {
    child first @0x1000;
`ifdef OCAH_DOC_MEMORY_MAP
    first->ocah_aperture_size = 0x100;
`endif
    child repeated[2] @0x2000 += 0x100;
`ifdef OCAH_DOC_MEMORY_MAP
    repeated->ocah_aperture_size = 0x200;
`endif
};
"""

RESPONSE_RDL = """
mem words {
    mementries = 0x40;
    memwidth = 32;
};
mem remap {
    mementries = 0x40;
    memwidth = 32;
`ifdef OCAH_DOC_MEMORY_MAP
    ocah_hole_resp = ocah_resp'{rresp: ocah_resp_e::FORWARD, rdata: 0x0, bresp: ocah_resp_e::FORWARD};
`endif
};
addrmap leaf {
    reg { field { sw = rw; hw = r; } value[31:0]; } first @0x0;
    reg { field { sw = rw; hw = r; } value[31:0]; } second @0x8;
};
addrmap strict {
`ifdef OCAH_DOC_MEMORY_MAP
    ocah_hole_resp = ocah_resp'{rresp: ocah_resp_e::SLVERR, rdata: 0x0, bresp: ocah_resp_e::SLVERR};
`endif
    reg { field { sw = rw; hw = r; } value[31:0]; } first @0x0;
    reg { field { sw = rw; hw = r; } value[31:0]; } second @0x8;
};
addrmap tiled {
    reg { field { sw = rw; hw = r; } value[31:0]; } only @0x0;
};
addrmap wrap {
`ifdef OCAH_DOC_MEMORY_MAP
    ocah_gap_resp = ocah_resp'{rresp: ocah_resp_e::DECERR, rdata: 0x0, bresp: ocah_resp_e::SLVERR};
`endif
    leaf low @0x0;
    leaf high @0x100;
};
addrmap top {
`ifdef OCAH_DOC_MEMORY_MAP
    ocah_hole_resp = ocah_resp'{rresp: ocah_resp_e::OKAY, rdata: 0x0, bresp: ocah_resp_e::OKAY};
    ocah_gap_resp = ocah_resp'{rresp: ocah_resp_e::DECERR, rdata: 0xBADCAB1E, bresp: ocah_resp_e::DECERR};
`endif
    leaf plain @0x0;
    strict checked @0x1000;
    tiled full @0x2000;
    wrap composite @0x3000;
    leaf repeated[4] @0x4000 += 0x10;
    external words memory @0x5000;
    external remap window @0x6000;
`ifdef OCAH_DOC_MEMORY_MAP
    plain->ocah_aperture_size = 0x100;
    plain->ocah_past_extent_resp = ocah_resp'{rresp: ocah_resp_e::DECERR, rdata: 0xBADCAB1E, bresp: ocah_resp_e::SLVERR};
    checked->ocah_aperture_size = 0x100;
    checked->ocah_past_extent_resp = ocah_resp'{rresp: ocah_resp_e::SLVERR, rdata: 0x0, bresp: ocah_resp_e::SLVERR};
    composite->ocah_aperture_size = 0x1000;
    composite->ocah_past_extent_resp = ocah_resp'{rresp: ocah_resp_e::DECERR, rdata: 0x0, bresp: ocah_resp_e::SLVERR};
    repeated->ocah_aperture_size = 0x100;
    repeated->ocah_gap_resp = ocah_resp'{rresp: ocah_resp_e::SLVERR, rdata: 0x0, bresp: ocah_resp_e::SLVERR};
    repeated->ocah_past_extent_resp = ocah_resp'{rresp: ocah_resp_e::ALIAS, rdata: 0x0, bresp: ocah_resp_e::ALIAS};
`endif
};
"""

RESPONSE_COLUMNS = ["base", "size", "occupied_size", "label", "hole_resp", "past_resp"]


class MemoryMapTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        root = Path(self.temp.name)
        self.udp = root / "udp.rdl"
        self.rdl = root / "map.rdl"
        self.udp.write_text(UDP)
        self.rdl.write_text(RDL)
        self.root = compile_root(self.rdl, self.udp, top="top")

    def tearDown(self):
        self.temp.cleanup()

    def test_build_and_render(self):
        config = {
            "version": 1,
            "views": [
                {
                    "name": "map",
                    "title": "Map",
                    "derive_gaps": True,
                    "rows": [
                        {"selector": "first"},
                        {"selector": "repeated"},
                    ],
                }
            ],
        }
        view = build_views(config, {"main": self.root})[0]
        self.assertEqual(view.rows[0].aperture_size, 0x100)
        self.assertEqual(view.rows[1].label, "Reserved")
        self.assertEqual(view.rows[2].occupied_size, 0x104)
        self.assertEqual(view.rows[2].aperture_size, 0x200)
        adoc = render_adoc([view])
        self.assertIn(r"Contains \| escaped", adoc)
        self.assertIn("Reserved", adoc)
        self.assertIn("512 B", adoc)
        self.assertIn("// tag::map[]", adoc)
        self.assertIn("// end::map[]", adoc)

    def test_gap_bounds_preserve_outside_rows(self):
        bounds_rdl = Path(self.temp.name) / "bounds.rdl"
        bounds_rdl.write_text(
            """
mem region {
    mementries = 0x800;
    memwidth = 8;
};
addrmap bounds_top {
    external region bounds @0x1000;
};
"""
        )
        bounds_root = compile_root(bounds_rdl, None, top="bounds_top")
        config = {
            "version": 1,
            "views": [
                {
                    "name": "map",
                    "derive_gaps": True,
                    "bounds_source": "bounds",
                    "bounds_selector": "bounds",
                    "rows": [
                        {"selector": "first"},
                        {"selector": "repeated"},
                    ],
                }
            ],
        }
        view = build_views(config, {"main": self.root, "bounds": bounds_root})[0]
        self.assertEqual([row.label for row in view.rows], ["Child", "Reserved", "Child"])
        self.assertEqual(view.rows[1].base, 0x1100)
        self.assertEqual(view.rows[1].end, 0x17FF)

    def test_rejects_stale_selector(self):
        config = {
            "version": 1,
            "views": [{"name": "map", "rows": [{"selector": "missing"}]}],
        }
        with self.assertRaisesRegex(ValueError, "matched no elaborated node"):
            build_views(config, {"main": self.root})

    def test_rejects_undersized_rdl_aperture(self):
        undersized = Path(self.temp.name) / "undersized.rdl"
        undersized.write_text(
            RDL.replace("first->ocah_aperture_size = 0x100;", "first->ocah_aperture_size = 0x2;")
        )
        root = compile_root(undersized, self.udp, top="top")
        config = {
            "version": 1,
            "views": [{"name": "map", "rows": [{"selector": "first"}]}],
        }
        with self.assertRaisesRegex(ValueError, "smaller than occupied"):
            build_views(config, {"main": root})

    def test_rejects_overlap(self):
        config = {
            "version": 1,
            "views": [
                {
                    "name": "map",
                    "rows": [
                        {"selector": "first"},
                        {"source": "other", "selector": "first"},
                    ],
                }
            ],
        }
        with self.assertRaisesRegex(ValueError, "overlaps"):
            build_views(config, {"main": self.root, "other": self.root})

    def test_relative_base_is_derived_from_rdl(self):
        config = {
            "version": 1,
            "views": [
                {
                    "name": "map",
                    "include_all": True,
                    "base_mode": "relative",
                }
            ],
        }
        view = build_views(config, {"main": self.root})[0]
        self.assertEqual(view.base, view.rows[0].base)

    def test_xml_stamping_removes_exporter_trailing_space(self):
        xml = Path(self.temp.name) / "map.xml"
        xml.write_text('<?xml version="1.0"?>\n<description>text </description>  \n')
        self.assertTrue(stamp_file(xml))
        text = xml.read_text()
        self.assertTrue(text.startswith('<?xml version="1.0"?>\n<!-- SPDX'))
        self.assertIn("<description>text </description>\n", text)

    def test_rdl_stamping(self):
        rdl = Path(self.temp.name) / "map.rdl"
        rdl.write_text("addrmap map {};\n")
        self.assertTrue(stamp_file(rdl))
        self.assertTrue(rdl.read_text().startswith("// SPDX-License-Identifier"))

    def test_config_rejects_unknown_keys(self):
        config = Path(self.temp.name) / "bad.toml"
        config.write_text('version = 1\n[[views]]\nname = "bad"\ncolums = ["base"]\n')
        with self.assertRaisesRegex(ValueError, "unknown key"):
            load_config(config)

    def test_config_rejects_hardware_facts(self):
        config = Path(self.temp.name) / "bad.toml"
        for field in ("expected_address", "aperture_size", "base", "bounds_start"):
            with self.subTest(field=field):
                config.write_text(
                    f'version = 1\n[[views]]\nname = "bad"\n'
                    f'[[views.rows]]\nselector = "first"\n{field} = 1\n'
                )
                with self.assertRaisesRegex(ValueError, "numeric hardware data"):
                    load_config(config)
        config.write_text('version = 1\n[[nodes]]\nselector = "first"\n')
        with self.assertRaisesRegex(ValueError, "unknown key"):
            load_config(config)
        config.write_text(
            'version = 1\n[[views]]\nname = "bad"\n'
            '[[views.rows]]\nkind = "region"\nlabel = "Hidden map"\nbase = 1\nsize = 1\n'
        )
        with self.assertRaisesRegex(ValueError, "numeric hardware data"):
            load_config(config)


class ResponseColumnTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def compile(self, text: str, name: str = "map.rdl", top: str = "top"):
        rdl = Path(self.temp.name) / name
        rdl.write_text(text)
        return compile_root(rdl, REGBLOCK_UDP, top=top)

    def view(self, spec: dict, text: str = RESPONSE_RDL, **roots):
        config = {"version": 1, "views": [{"name": "map", **spec}]}
        return build_views(config, {"main": self.compile(text), **roots})[0]

    def cells(self, view):
        rendered = {}
        for line in render_adoc([view]).splitlines():
            cells = line[1:].split(" |") if line.startswith("|") and line != "|===" else []
            if len(cells) == len(view.columns) and "label" in view.columns:
                rendered[cells[view.columns.index("label")]] = cells
        return rendered

    def test_cells_render_last(self):
        adoc = render_adoc([self.view({"include_all": True, "columns": RESPONSE_COLUMNS})])
        self.assertIn(
            "|Base Address |Size |Decoded Extent |Unit |Hole in Extent (R / W) "
            "|Past Extent (R / W)\n",
            adoc,
        )
        self.assertIn(
            "|0x00000000 |256 B |12 B |plain |OKAY, 0x0 / OKAY |DECERR, 0xBADCAB1E / SLVERR\n",
            adoc,
        )

    def test_python_data_matches_the_rendered_cells(self):
        view = self.view({"include_all": True, "columns": RESPONSE_COLUMNS})
        data: dict = {}
        exec(render_py([view]), data)
        rows = {row["label"]: row for row in data["VIEWS"]["map"]["rows"]}
        self.assertEqual(list(rows), [row.label for row in view.rows])
        plain = rows["plain"]
        self.assertEqual(plain["end"], plain["base"] + plain["aperture_size"] - 1)
        self.assertEqual(plain["occupied_size"], 12)
        self.assertEqual(
            plain["hole_responses"],
            (("", {"rresp": "OKAY", "rdata": 0, "bresp": "OKAY", "text": "OKAY, 0x0 / OKAY"}),),
        )
        self.assertEqual(
            plain["past_response"],
            {
                "rresp": "DECERR",
                "rdata": 0xBADCAB1E,
                "bresp": "SLVERR",
                "text": "DECERR, 0xBADCAB1E / SLVERR",
            },
        )
        self.assertEqual(
            [label for label, _ in rows["composite"]["hole_responses"]], ["", "between sub-blocks"]
        )
        self.assertEqual(rows["memory"]["hole_responses"], ())
        self.assertIsNone(rows["memory"]["past_response"])

    def test_override_beside_inheriting_sibling(self):
        cells = self.cells(self.view({"include_all": True, "columns": RESPONSE_COLUMNS}))
        self.assertEqual(cells["plain"][-2], "OKAY, 0x0 / OKAY")
        self.assertEqual(cells["checked"][-2:], ["SLVERR, 0x0 / SLVERR", "SLVERR, 0x0 / SLVERR"])

    def test_absent_regions_render_dash(self):
        cells = self.cells(self.view({"include_all": True, "columns": RESPONSE_COLUMNS}))
        self.assertEqual(cells["memory"][-2:], ["-", "-"])
        self.assertEqual(cells["full"][-2:], ["-", "-"])

    def test_composite_cell_names_the_space_between_sub_blocks(self):
        cells = self.cells(self.view({"include_all": True, "columns": RESPONSE_COLUMNS}))
        self.assertEqual(
            cells["composite"][-2:],
            [
                "OKAY, 0x0 / OKAY; between sub-blocks: DECERR, 0x0 / SLVERR",
                "DECERR, 0x0 / SLVERR",
            ],
        )

    def test_array_tails_and_range_after_last_element(self):
        cells = self.cells(self.view({"include_all": True, "columns": RESPONSE_COLUMNS}))
        self.assertEqual(
            cells["repeated"][-2:],
            [
                "OKAY, 0x0 / OKAY; between instances: SLVERR, 0x0 / SLVERR",
                "Aliases registers",
            ],
        )

    def test_full_stride_extent_decodes_the_last_tail(self):
        text = RESPONSE_RDL.replace(
            "addrmap top {\n`ifdef OCAH_DOC_MEMORY_MAP\n",
            "addrmap top {\n`ifdef OCAH_DOC_MEMORY_MAP\n    ocah_full_stride_extent = true;\n",
        )
        view = self.view({"include_all": True, "columns": RESPONSE_COLUMNS}, text)
        rows = {row.label: row for row in view.rows}
        self.assertEqual(rows["repeated"].occupied_size, 0x40)
        self.assertEqual(rows["plain"].occupied_size, 0xC)

    def test_memory_with_its_own_response_answers_throughout(self):
        text = RESPONSE_RDL.replace(
            "    plain->ocah_aperture_size = 0x100;\n",
            "    plain->ocah_aperture_size = 0x100;\n"
            "    memory->ocah_hole_resp = ocah_resp'{rresp: ocah_resp_e::DECERR, rdata: 0x0,"
            " bresp: ocah_resp_e::DECERR};\n",
        )
        cells = self.cells(self.view({"include_all": True, "columns": RESPONSE_COLUMNS}, text))
        self.assertEqual(cells["memory"][-2:], ["DECERR, 0x0 / DECERR", "-"])

    def test_forwarded_memory(self):
        cells = self.cells(self.view({"include_all": True, "columns": RESPONSE_COLUMNS}))
        self.assertEqual(cells["window"][-2:], ["Forwarded", "-"])

    def test_reserved_rows_take_the_row_source_top_gap(self):
        bounds = self.compile(
            """
mem region {
    mementries = 0x800;
    memwidth = 32;
};
addrmap bounds_top {
`ifdef OCAH_DOC_MEMORY_MAP
    ocah_gap_resp = ocah_resp'{rresp: ocah_resp_e::SLVERR, rdata: 0x0, bresp: ocah_resp_e::SLVERR};
`endif
    external region bounds @0x0;
};
""",
            "bounds.rdl",
            "bounds_top",
        )
        view = self.view(
            {
                "derive_gaps": True,
                "bounds_source": "bounds",
                "bounds_selector": "bounds",
                "columns": RESPONSE_COLUMNS,
                "rows": [{"selector": "plain"}, {"selector": "checked"}],
            },
            bounds=bounds,
        )
        reserved = [row for row in view.rows if row.label == "Reserved"]
        self.assertEqual(len(reserved), 2)
        for row in reserved:
            self.assertEqual(row.hole_responses[0][1].text, "DECERR, 0xBADCAB1E / DECERR")
            self.assertIsNone(row.past_response)

    def test_views_without_response_columns_are_unchanged(self):
        bare = "\n".join(line for line in RESPONSE_RDL.splitlines() if "_resp" not in line)
        spec = {"include_all": True, "derive_gaps": True}
        self.assertEqual(render_adoc([self.view(spec)]), render_adoc([self.view(spec, bare)]))
        with self.assertRaisesRegex(ValueError, "ocah_hole_resp is not set"):
            self.view({**spec, "columns": RESPONSE_COLUMNS}, bare)

    def test_rejects_group_rows(self):
        spec = {
            "columns": RESPONSE_COLUMNS,
            "rows": [{"kind": "group", "label": "Group", "members": ["plain"]}],
        }
        with self.assertRaisesRegex(ValueError, "group row"):
            self.view(spec)

    def test_rejects_ambiguous_holes(self):
        text = RESPONSE_RDL.replace("    leaf high @0x100;", "    strict high @0x100;")
        with self.assertRaisesRegex(ValueError, "composite: holes answer differently"):
            self.view({"include_all": True, "columns": RESPONSE_COLUMNS}, text)

    def test_wide_read_data_notes_the_upper_word(self):
        wide = RESPONSE_RDL.replace(
            "rdata: 0xBADCAB1E, bresp: ocah_resp_e::DECERR",
            "rdata: 0xCA11AB1EBADCAB1E, bresp: ocah_resp_e::DECERR",
        )
        view = self.view(
            {
                "derive_gaps": True,
                "columns": ["label", "hole_resp"],
                "rows": [{"selector": "plain"}, {"selector": "checked"}, {"selector": "full"}],
            },
            wide,
        )
        adoc = render_adoc([view])
        reserved = [line for line in adoc.splitlines() if "|Reserved" in line]
        self.assertEqual(
            reserved, ["|Reserved |DECERR, 0xBADCAB1E^<<map-note-1,[1]>>^ / DECERR"] * 3
        )
        self.assertIn(
            "|===\n\n.Notes\n[[map-note-1]]^[1]^ A 32-bit read with address bit 2 set returns"
            " 0xCA11AB1E.\n// end::map[]",
            adoc,
        )

    def test_notes_mark_their_cell(self):
        text = RESPONSE_RDL.replace(
            "    plain->ocah_aperture_size = 0x100;\n",
            "    plain->ocah_aperture_size = 0x100;\n"
            '    plain->ocah_past_extent_note = "Past [note] | unescaped";\n'
            '    memory->ocah_hole_note = "Writes are dropped.";\n'
            '    full->ocah_hole_note = "Writes are dropped.";\n',
        )
        view = self.view({"include_all": True, "columns": RESPONSE_COLUMNS}, text)
        cells = self.cells(view)
        self.assertEqual(cells["plain"][-1], "DECERR, 0xBADCAB1E / SLVERR^<<map-note-1,[1]>>^")
        self.assertEqual(cells["full"][-2], "-^<<map-note-2,[2]>>^")
        self.assertEqual(cells["memory"][-2], "-^<<map-note-2,[2]>>^")
        self.assertIn(
            ".Notes\n[[map-note-1]]^[1]^ Past [note] | unescaped +\n"
            "[[map-note-2]]^[2]^ Writes are dropped.\n",
            render_adoc([view]),
        )

    def test_following_gap_note_marks_the_next_reserved_row(self):
        text = RESPONSE_RDL.replace(
            "    plain->ocah_aperture_size = 0x100;\n",
            "    plain->ocah_aperture_size = 0x100;\n"
            '    plain->ocah_following_gap_note = "Forwarded elsewhere.";\n',
        )
        view = self.view(
            {
                "derive_gaps": True,
                "columns": ["base", "label", "hole_resp"],
                "rows": [{"selector": "plain"}, {"selector": "checked"}],
            },
            text,
        )
        adoc = render_adoc([view])
        reserved = [line for line in adoc.splitlines() if "|Reserved" in line]
        self.assertEqual(
            reserved,
            [
                "|0x00000100 |Reserved |DECERR, 0xBADCAB1E / DECERR^<<map-note-1,[1]>>^",
                "|0x00001100 |Reserved |DECERR, 0xBADCAB1E / DECERR",
            ],
        )
        self.assertIn(".Notes\n[[map-note-1]]^[1]^ Forwarded elsewhere.\n", adoc)

    def test_nested_array_tails_answer_like_their_composite(self):
        text = RESPONSE_RDL.replace("    leaf high @0x100;", "    leaf high[2] @0x100 += 0x10;")
        cells = self.cells(self.view({"include_all": True, "columns": RESPONSE_COLUMNS}, text))
        self.assertEqual(
            cells["composite"][-2], "OKAY, 0x0 / OKAY; between sub-blocks: DECERR, 0x0 / SLVERR"
        )

    def test_rejects_invalid_read_data(self):
        forwarded = RESPONSE_RDL.replace(
            "ocah_resp_e::FORWARD, rdata: 0x0", "ocah_resp_e::FORWARD, rdata: 0x1"
        )
        with self.assertRaisesRegex(ValueError, "FORWARD read carries read data"):
            self.view({"include_all": True, "columns": RESPONSE_COLUMNS}, forwarded)


class RegblockResponseCheckTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()

    def tearDown(self):
        self.temp.cleanup()

    def check(self, err_check=(), no_rtl=(), text=RESPONSE_RDL, columns=RESPONSE_COLUMNS):
        rdl = Path(self.temp.name) / "map.rdl"
        rdl.write_text(text)
        roots = {"main": compile_root(rdl, REGBLOCK_UDP, top="top")}
        view = {"name": "map", "include_all": True}
        if columns:
            view["columns"] = columns
        views = build_views({"version": 1, "views": [view]}, roots)
        check_regblock_responses(views, roots, err_check, no_rtl)

    def test_accepts_values_matching_generator_options(self):
        self.check(err_check={"strict"})

    def test_rejects_values_contradicting_generator_options(self):
        with self.assertRaisesRegex(ValueError, "top.checked: regblock answers OKAY"):
            self.check()

    def test_exempts_blocks_without_regblock_rtl(self):
        self.check(no_rtl={"strict"})

    def test_composite_sub_blocks_take_the_composite_flag(self):
        with self.assertRaisesRegex(ValueError, "top.composite.low: regblock answers SLVERR"):
            self.check(err_check={"strict", "wrap"})

    def test_rejects_unresolved_leaf(self):
        bare = "\n".join(line for line in RESPONSE_RDL.splitlines() if "ocah_hole_resp" not in line)
        with self.assertRaisesRegex(ValueError, "top.plain: ocah_hole_resp is not set"):
            self.check(err_check={"strict"}, text=bare, columns=["label", "past_resp"])

    def test_skips_views_without_response_columns(self):
        bare = "\n".join(line for line in RESPONSE_RDL.splitlines() if "_resp" not in line)
        self.check(text=bare, columns=None)


if __name__ == "__main__":
    unittest.main()
