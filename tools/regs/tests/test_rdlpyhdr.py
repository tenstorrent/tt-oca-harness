# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from tools.regs.tests.pyhdr_support import load

ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "tools/regs/rdlpyhdr.py"
UDP = ROOT / "hw/common/regs/regblock_udps.rdl"

# Every sw/hw pairing SystemRDL accepts: sw=na has no software view and sw=w with
# hw=w leaves the field unreadable. Volatile follows hw writability alone.
ACCESS_FIELDS = (
    ("rw_rw", 0, 0, "rw", "rw", "", "", False, True, 0),
    ("rw_r", 1, 1, "rw", "r", "", "", False, False, 0),
    ("rw_w", 2, 2, "rw", "w", "", "", False, True, 0),
    ("rw_na", 3, 3, "rw", "na", "", "", False, False, 0),
    ("r_rw", 4, 4, "r", "rw", "", "", False, True, 0),
    ("r_r", 5, 5, "r", "r", "", "", False, False, 0),
    ("r_w", 6, 6, "r", "w", "", "", False, True, 0),
    ("r_na", 7, 7, "r", "na", "", "", False, False, 0),
    ("w_rw", 8, 8, "w", "rw", "", "", False, True, 0),
    ("w_r", 9, 9, "w", "r", "", "", False, False, 0),
    ("w_na", 10, 10, "w", "na", "", "", False, False, 0),
    ("rw1_rw", 11, 11, "rw1", "rw", "", "", False, True, 0),
    ("rw1_r", 12, 12, "rw1", "r", "", "", False, False, 0),
    ("rw1_w", 13, 13, "rw1", "w", "", "", False, True, 0),
    ("rw1_na", 14, 14, "rw1", "na", "", "", False, False, 0),
    ("w1_rw", 15, 15, "w1", "rw", "", "", False, True, 0),
    ("w1_r", 16, 16, "w1", "r", "", "", False, False, 0),
    ("w1_w", 17, 17, "w1", "w", "", "", False, True, 0),
    ("w1_na", 18, 18, "w1", "na", "", "", False, False, 0),
)

RDL = """
enum mode_e { OFF = 0; ON = 1; FAST = 3; };
addrmap top {
    signal { signalwidth = 8; } seed_rst;
    reg ctrl_t {
        regwidth = 32;
        field { sw=rw; hw=r; reset = 0x1; } enable[0:0];
        field { sw=rw; hw=w; reset = 0x0; } busy_rw[1:1];
        field { sw=r;  hw=w; } status[3:2];
        field { sw=rw; hw=r; woclr; reset = 0x0; } clr[4:4];
        field { sw=r;  hw=w; rclr; reset = 0x0; } rc[5:5];
        field { sw=w;  hw=r; singlepulse; reset = 0x0; } go[6:6];
        field { sw=rw; hw=r; reset = seed_rst; } seeded[15:8];
        field { sw=rw; hw=r; encode = mode_e; reset = mode_e::FAST; } mode[17:16];
        field { sw=rw; hw=r; } mirror[31:24];
    };
    reg access_t {
        regwidth = 32;
%s
    };
    reg wide_t {
        regwidth = 128;
        field { sw=rw; hw=r; reset = 0x5; } lo[7:0];
        field { sw=r;  hw=w; } hi[127:64];
    };
    ctrl_t ctrl @0x0;
    ctrl_t ctrl_copy @0x4;
    access_t access @0x8;
    wide_t key[2] @0x10 += 0x10;
    ctrl.mirror->reset = ctrl.seeded;
    ctrl_copy.mirror->reset = ctrl_copy.seeded->reset;
};
""" % "\n".join(
    f"        field {{ sw={sw}; hw={hw}; reset = 0x0; }} {name}[{bit}:{bit}];"
    for name, bit, _msb, sw, hw, *_rest in ACCESS_FIELDS
)

RDL_DISAGREE = """
addrmap top {
    reg ctrl_t {
        regwidth = 32;
        field { sw=rw; hw=r; reset = 0x1; } enable[0:0];
    };
    ctrl_t ctrl @0x0;
    ctrl_t ctrl_copy @0x4;
    ctrl_copy.enable->%s;
};
"""

CTRL_FIELDS = (
    ("enable", 0, 0, "rw", "r", "", "", False, False, 1),
    ("busy_rw", 1, 1, "rw", "w", "", "", False, True, 0),
    ("status", 2, 3, "r", "w", "", "", False, True, None),
    ("clr", 4, 4, "rw", "r", "woclr", "", False, False, 0),
    ("rc", 5, 5, "r", "w", "", "rclr", False, True, 0),
    ("go", 6, 6, "w", "r", "", "", True, True, 0),
    ("seeded", 8, 15, "rw", "r", "", "", False, False, None),
    ("mode", 16, 17, "rw", "r", "", "", False, False, 3),
    ("mirror", 24, 31, "rw", "r", "", "", False, False, None),
)


def run_generator(rdl: Path, out: Path, *options: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "-u", str(UDP), *options, str(rdl), str(out)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
    )


def generate(rdl: Path, out: Path, *options: str) -> str:
    result = run_generator(rdl, out, *options)
    if result.returncode != 0:
        raise AssertionError(result.stdout + result.stderr)
    return out.read_text()


class RdlPyHdrTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = TemporaryDirectory()
        cls.rdl = Path(cls.temp.name) / "map.rdl"
        cls.rdl.write_text(RDL)
        cls.out = Path(cls.temp.name) / "top_reg.py"
        cls.text = generate(cls.rdl, cls.out)
        cls.module = load(cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def test_instance_binds_type(self):
        m = self.module
        for inst in ("CTRL", "CTRL_COPY"):
            self.assertEqual(getattr(m, f"{inst}_REG_TYPE"), "TOP_CTRL_T")
            self.assertFalse(hasattr(m, f"{inst}_REG_WIDTH"), "width is a property of the type")
        for inst in ("KEY_0_", "KEY_1_"):
            self.assertEqual(getattr(m, f"{inst}_REG_TYPE"), "TOP_WIDE_T")
        self.assertEqual(m.KEY_1__REG_ADDR, 0x20)

    def test_type_width(self):
        m = self.module
        self.assertEqual(m.TOP_CTRL_T_REG_WIDTH, 32)
        self.assertEqual(m.TOP_ACCESS_T_REG_WIDTH, 32)
        self.assertEqual(m.TOP_WIDE_T_REG_WIDTH, 128)

    def test_field_records(self):
        self.assertEqual(self.module.TOP_CTRL_T_REG_FIELDS, CTRL_FIELDS)

    def test_every_sw_hw_combination(self):
        self.assertEqual(self.module.TOP_ACCESS_T_REG_FIELDS, ACCESS_FIELDS)

    def test_reset_is_the_constant_value_or_none(self):
        by_name = {f[0]: f for f in self.module.TOP_CTRL_T_REG_FIELDS}
        self.assertEqual(by_name["enable"][-1], 1)
        self.assertEqual(by_name["mode"][-1], 3, "encoded enum member")
        self.assertIsNone(by_name["status"][-1], "no reset property")
        self.assertIsNone(by_name["seeded"][-1], "signal-driven reset")
        self.assertIsNone(by_name["mirror"][-1], "field or property reference")
        self.assertEqual(self.module.TOP_CTRL_T_REG_DEFAULT, 0x30001)

    def test_wide_register_gets_fields_without_default_or_ctypes(self):
        m = self.module
        self.assertEqual(
            m.TOP_WIDE_T_REG_FIELDS,
            (
                ("lo", 0, 7, "rw", "r", "", "", False, False, 5),
                ("hi", 64, 127, "r", "w", "", "", False, True, None),
            ),
        )
        self.assertEqual(
            m.TOP_WIDE_T_REG_FIELD_ACCESS,
            (("lo", "rw", "", "", False), ("hi", "r", "", "", False)),
        )
        for symbol in ("TOP_WIDE_T_REG_DEFAULT", "TOP_WIDE_T_reg_u"):
            self.assertFalse(hasattr(m, symbol), symbol)
        self.assertTrue(hasattr(m, "TOP_CTRL_T_reg_u"))

    def test_field_access_is_a_projection_of_fields(self):
        projected = tuple((f[0], f[3], f[5], f[6], f[7]) for f in CTRL_FIELDS)
        self.assertEqual(self.module.TOP_CTRL_T_REG_FIELD_ACCESS, projected)

    def test_field_access_flag_changes_nothing(self):
        out = Path(self.temp.name) / "top_reg_flag.py"
        self.assertEqual(generate(self.rdl, out, "--field-access"), self.text)

    def test_bitfields_none_keeps_field_records(self):
        out = Path(self.temp.name) / "top_reg_nobf.py"
        text = generate(self.rdl, out, "--bitfields", "none")
        m = load(out)
        self.assertEqual(m.TOP_CTRL_T_REG_FIELDS, CTRL_FIELDS)
        self.assertEqual(m.TOP_CTRL_T_REG_DEFAULT, 0x30001)
        self.assertNotIn("class ", text)

    def assert_instances_disagree(self, assignment: str, message: str) -> None:
        rdl = Path(self.temp.name) / "disagree.rdl"
        rdl.write_text(RDL_DISAGREE % assignment)
        result = run_generator(rdl, Path(self.temp.name) / "disagree_reg.py")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(
            f"register type 'TOP_CTRL_T' (top.ctrl vs top.ctrl_copy): field 'enable' {message}",
            result.stderr,
        )

    def test_instances_of_one_type_must_agree_on_access(self):
        self.assert_instances_disagree("sw = r", "sw 'rw' vs 'r'")

    def test_instances_of_one_type_must_agree_on_reset(self):
        self.assert_instances_disagree("reset = 0x0", "reset 1 vs 0")


if __name__ == "__main__":
    unittest.main()
