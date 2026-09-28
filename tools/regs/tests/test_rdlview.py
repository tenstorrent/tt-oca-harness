# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

import re
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.regs.common.rdlview import collect, compile_root, write_adoc, write_html


class RegisterViewTests(unittest.TestCase):
    def test_nested_banks_inside_array_keep_their_full_paths(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "nested.rdl"
            source.write_text("""
regfile bank {
    reg { field { sw = rw; hw = r; } value[31:0]; } control;
};
regfile channel {
    bank tx @0x0;
    bank rx @0x8;
};
addrmap top { channel channels[2] @0x0 += 0x20; };
""")
            data = collect(compile_root(str(source), None, []))
            self.assertEqual(
                [(reg.name, reg.addr) for reg in data.regs],
                [
                    ("channels[2].tx.control", "0x0 - 0x20"),
                    ("channels[2].rx.control", "0x8 - 0x28"),
                ],
            )
            self.assertEqual(len(data.arrays), 2)

    def test_distinct_banks_and_array_instances_survive_both_exports(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "banks.rdl"
            source.write_text("""
regfile bank {
    reg { field { sw = rw; hw = r; } value[31:0]; } control;
    reg { field { sw = rw; hw = r; } value[31:0]; } scratch[4];
};
addrmap top {
    bank cold @0x0;
    bank warm @0x80;
    bank channels[2] @0x100 += 0x40;
    reg { field { sw = r; hw = w; } value[31:0]; } status @0x200;
};
""")
            root = compile_root(str(source), None, [])
            data = collect(root)
            regs = {reg.name: reg.addr for reg in data.regs}
            self.assertEqual(regs["cold.control"], "0x0")
            self.assertEqual(regs["warm.control"], "0x80")
            self.assertEqual(regs["cold.scratch[4]"], "0x4 - 0x10")
            self.assertEqual(regs["warm.scratch[4]"], "0x84 - 0x90")
            self.assertEqual(regs["channels[2].control"], "0x100 - 0x140")
            self.assertEqual(regs["channels[0].scratch[4]"], "0x104 - 0x110")
            self.assertEqual(regs["channels[1].scratch[4]"], "0x144 - 0x150")
            self.assertEqual(regs["status"], "0x200")
            self.assertEqual(len(regs), 8)
            self.assertEqual(len(regs), len(data.regs))
            self.assertEqual(data.arrays["warm.scratch[4]"], (4, "0x84", "0x4"))

            adoc = Path(temp) / "banks.adoc"
            html = Path(temp) / "banks.html"
            write_adoc(root, str(adoc))
            write_html(root, str(html))
            for name in ("cold.control", "warm.control", "cold.scratch[4]", "warm.scratch[4]"):
                self.assertIn(f"=== {name}\n", adoc.read_text())
                self.assertIn(f">{name}</h3>", html.read_text())
            anchors = re.findall(r'<h3 id="([^"]+)"', html.read_text())
            links = re.findall(r'href="#([^"]+)"', html.read_text())
            self.assertEqual(len(anchors), len(set(anchors)))
            self.assertEqual(anchors, links)

    def test_addrmap_name_renders_as_heading_with_desc_below(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "named.rdl"
            source.write_text("""
addrmap plic {
    name = "PLIC Address Map";
    desc = "Platform-Level Interrupt Controller register interface.";
    reg { field { sw = rw; hw = r; } value[31:0]; } control @0x0;
};
""")
            root = compile_root(str(source), None, [])
            adoc = Path(temp) / "named.adoc"
            html = Path(temp) / "named.html"
            write_adoc(root, str(adoc))
            write_html(root, str(html))

            # The authored name is the visible heading; the identifier stays in
            # the anchor and the <h2> id that the catalog tooling keys off.
            self.assertIn("[#regmap-{regmap-instance}-plic]\n== PLIC Address Map\n", adoc.read_text())
            self.assertIn('<h2 id="regmap-plic">PLIC Address Map</h2>', html.read_text())
            self.assertNotIn("Address Map: plic", adoc.read_text())
            self.assertNotIn("Address Map: plic", html.read_text())
            # The description is added below the heading.
            self.assertIn(
                "Platform-Level Interrupt Controller register interface.",
                adoc.read_text(),
            )
            self.assertIn(
                "<p>Platform-Level Interrupt Controller register interface.</p>",
                html.read_text(),
            )

    def test_addrmap_without_name_falls_back_to_the_identifier_heading(self):
        with TemporaryDirectory() as temp:
            source = Path(temp) / "bare.rdl"
            source.write_text("""
addrmap bare { reg { field { sw = rw; hw = r; } value[31:0]; } control @0x0; };
""")
            root = compile_root(str(source), None, [])
            adoc = Path(temp) / "bare.adoc"
            html = Path(temp) / "bare.html"
            write_adoc(root, str(adoc))
            write_html(root, str(html))
            # No authored name: the heading falls back to "Address Map: <ident>",
            # and with no desc it runs straight into the register list.
            self.assertIn("== Address Map: bare\n", adoc.read_text())
            self.assertIn(
                '<h2 id="regmap-bare">Address Map: bare</h2>\n<p><strong>Register List:</strong></p>',
                html.read_text(),
            )


if __name__ == "__main__":
    unittest.main()
