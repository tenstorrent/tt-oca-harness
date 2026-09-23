# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.regs.common.memorymap import (
    build_views,
    compile_root,
    load_config,
    render_adoc,
)
from tools.regs.common.rdlview import collect
from tools.regs.stamp_spdx import stamp_file

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

    def test_doc_override_is_validated(self):
        data = collect(self.root, {"first.control": "Documented locally"})
        control = next(reg for reg in data.regs if reg.name == "control")
        self.assertEqual(control.desc, "Documented locally")
        with self.assertRaisesRegex(ValueError, "matched no register"):
            collect(self.root, {"first.missing": "Stale"})

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


if __name__ == "__main__":
    unittest.main()
