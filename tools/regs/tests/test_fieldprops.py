# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.regs.common.fieldprops import extract_field_props
from tools.regs.common.rdlview import compile_root, field_access

RDL = """
addrmap top {
    reg {
        field { sw=rw; hw=w; woclr; }             shorthand_clr[0:0];
        field { sw=rw; hw=w; onwrite=woclr; }      explicit_clr[1:1];
        field { sw=rw; hw=w; onwrite=woset; }      set_on_write[2:2];
        field { sw=rw; hw=w; onwrite=wzc; }        clr_on_zero[3:3];
        field { sw=r;  hw=w; rclr; }               read_clr[4:4];
        field { sw=w;  hw=r; singlepulse; reset=0; } pulse[5:5];
        field { sw=rw; hw=r; }                     plain[6:6];
    } r0 @0;
};
"""


class Stub:
    """Minimal FieldNode stand-in for exercising the contradiction guard, which
    a real compile cannot reach -- the RDL compiler rejects the pairing first."""

    def __init__(self, **props):
        self.props = props
        self.inst_name = "stub"
        self.lsb = 0
        self.msb = 0

    def get_property(self, name, default=None):
        return self.props.get(name, default)


class FieldPropsTest(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        rdl = Path(self.temp.name) / "map.rdl"
        rdl.write_text(RDL)
        root = compile_root(rdl, None, [], top="top")
        self.fields = {f.inst_name: f for reg in root.top.children() for f in reg.fields()}

    def tearDown(self):
        self.temp.cleanup()

    def props(self, name):
        return extract_field_props(self.fields[name])

    def test_shorthand_and_explicit_agree(self):
        # woclr shorthand and onwrite=woclr resolve to the same onwrite token,
        # and both keep the standalone woclr flag set for the JSON model.
        for name in ("shorthand_clr", "explicit_clr"):
            props = self.props(name)
            self.assertEqual(props.onwrite, "woclr")
            self.assertTrue(props.woclr)

    def test_write_side_effects(self):
        self.assertEqual(self.props("set_on_write").onwrite, "woset")
        self.assertEqual(self.props("clr_on_zero").onwrite, "wzc")

    def test_read_clear(self):
        props = self.props("read_clr")
        self.assertEqual(props.onread, "rclr")
        self.assertEqual(props.onwrite, "")

    def test_singlepulse(self):
        self.assertTrue(self.props("pulse").singlepulse)
        self.assertFalse(self.props("plain").singlepulse)

    def test_plain_field_has_no_effects(self):
        props = self.props("plain")
        self.assertEqual((props.onwrite, props.onread), ("", ""))
        self.assertFalse(props.singlepulse)
        self.assertFalse(props.woclr)

    def test_access_shorthand_rendering(self):
        cases = {
            "shorthand_clr": "RW1C",
            "explicit_clr": "RW1C",
            "set_on_write": "RW1S",
            "clr_on_zero": "RW0C",
            "read_clr": "R RC",
            "pulse": "W 1P",
            "plain": "RW",
        }
        for name, expected in cases.items():
            self.assertEqual(field_access(self.fields[name]), expected, name)

    def test_conflicting_write_shorthand_raises(self):
        with self.assertRaisesRegex(RuntimeError, "woset and woclr"):
            extract_field_props(Stub(woset=True, woclr=True))

    def test_conflicting_read_shorthand_raises(self):
        with self.assertRaisesRegex(RuntimeError, "rset and rclr"):
            extract_field_props(Stub(rset=True, rclr=True))


if __name__ == "__main__":
    unittest.main()
