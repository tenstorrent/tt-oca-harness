# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The register model read from the hand-written fixture header."""

import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fixture_reg  # noqa: E402
from ocah_regwalk import load_model  # noqa: E402

FIXTURE = Path(__file__).with_name("fixture_reg.py")


class Windows(unittest.TestCase):
    def setUp(self):
        self.model = load_model(fixture_reg)

    def test_windows_by_kind(self):
        self.assertEqual(
            [w.name for w in self.model.blocks], ["FIX_TOP", "CTRL", "WIDE", "BANK_0_", "BANK_1_"]
        )
        self.assertEqual(
            [w.name for w in self.model.regfiles], ["BANK_0__REGION", "BANK_1__REGION"]
        )
        self.assertEqual(
            [(w.name, w.base, w.size) for w in self.model.mems], [("BUF", 0x3800, 0x800)]
        )
        self.assertEqual(self.model.top.name, "FIX_TOP")
        self.assertEqual(self.model.block("CTRL").end, 0x1030)

    def test_window_lookup_rejects_other_kinds(self):
        self.assertEqual(self.model.window("BUF").kind, "mem")
        with self.assertRaises(KeyError):
            self.model.block("BUF")
        with self.assertRaises(KeyError):
            self.model.window("NOPE")


class Instances(unittest.TestCase):
    def setUp(self):
        self.model = load_model(FIXTURE)

    def test_every_reg_addr_symbol_is_an_instance(self):
        symbols = sorted(
            n[: -len("_REG_ADDR")] for n in vars(fixture_reg) if n.endswith("_REG_ADDR")
        )
        self.assertEqual(sorted(r.symbol for r in self.model.registers), symbols)
        self.assertEqual(
            [r.addr for r in self.model.registers], sorted(r.addr for r in self.model.registers)
        )

    def test_block_name_and_index(self):
        reg = self.model.by_symbol("CTRL_DMA_1_")
        self.assertEqual(
            (reg.block, reg.name, reg.base_name, reg.index), ("CTRL", "DMA_1_", "DMA", 1)
        )
        self.assertEqual((reg.type_name, reg.offset, reg.width), ("CTRL_DMA", 0x24, 32))
        attrs = self.model.by_symbol("BANK_1__REGION_ATTRS")
        self.assertEqual((attrs.block, attrs.name, attrs.index), ("BANK_1_", "REGION_ATTRS", None))
        self.assertEqual(attrs.base_name, "REGION_ATTRS")

    def test_register_under_the_top_falls_back_to_address_containment(self):
        reg = self.model.by_symbol("VERSION")
        self.assertEqual((reg.block, reg.name, reg.addr), ("FIX_TOP", "VERSION", 0x3FF0))

    def test_lookups(self):
        self.assertIs(self.model.by_addr(0x1008), self.model.by_symbol("CTRL_TRIG"))
        self.assertEqual(self.model.at(0x1009), ())
        with self.assertRaises(KeyError):
            self.model.by_addr(0x1009)
        with self.assertRaises(KeyError):
            self.model.by_symbol("CTRL_NOPE")
        self.assertEqual(len(self.model.under("CTRL")), 10)
        self.assertEqual(
            [r.symbol for r in self.model.under("CTRL_DMA")], ["CTRL_DMA_0_", "CTRL_DMA_1_"]
        )
        self.assertEqual(self.model.under("CTRL_DM"), ())

    def test_array_count(self):
        self.assertEqual(self.model.array_count("BANK"), 2)
        self.assertEqual(self.model.array_count("CTRL_DMA"), 2)
        with self.assertRaises(KeyError):
            self.model.array_count("CTRL")

    def test_reset_and_fields(self):
        mode = self.model.by_symbol("CTRL_MODE")
        self.assertEqual(mode.reset, fixture_reg.CTRL_MODE_REG_DEFAULT)
        self.assertEqual(mode.field("busy").mask, 1 << 16)
        self.assertEqual(
            [f.name for f in mode.fields], ["en", "sel", "rsvd0", "reserved_1", "busy"]
        )
        with self.assertRaises(KeyError):
            mode.field("nope")
        attrs = self.model.by_symbol("BANK_0__REGION_ATTRS")
        self.assertEqual(attrs.reset, fixture_reg.BANK_REGION_ATTRS_REG_DEFAULT)
        self.assertEqual(attrs.words, 2)
        self.assertEqual(self.model.by_symbol("WIDE_KEY").words, 8)
        self.assertEqual(self.model.by_symbol("CTRL_SEED").reset, 0)

    def test_types(self):
        self.assertEqual(self.model.types["WIDE_KEY"][0], 256)
        self.assertEqual(len(self.model.types), 13)


def _module(**symbols) -> types.ModuleType:
    module = types.ModuleType("bad_reg")
    vars(module).update(symbols)
    return module


class Rejections(unittest.TestCase):
    BASE = dict(
        TOP_REG_MAP_BASE_ADDR=0x0,
        TOP_REG_MAP_SIZE=0x10,
        A_REG_OFFSET=0x0,
        A_REG_ADDR=0x0,
        A_REG_TYPE="T",
        T_REG_WIDTH=32,
        T_REG_FIELDS=(("f", 0, 0, "rw", "r", "", "", False, False, 0),),
    )

    def test_missing_type_binding(self):
        symbols = dict(self.BASE)
        del symbols["A_REG_TYPE"]
        with self.assertRaisesRegex(ValueError, "A_REG_TYPE"):
            load_model(_module(**symbols))

    def test_missing_fields_or_width(self):
        symbols = dict(self.BASE, A_REG_TYPE="U")
        with self.assertRaisesRegex(ValueError, "_REG_FIELDS"):
            load_model(_module(**symbols))
        symbols = dict(self.BASE)
        del symbols["T_REG_WIDTH"]
        with self.assertRaisesRegex(ValueError, "T_REG_WIDTH"):
            load_model(_module(**symbols))

    def test_missing_window_size_or_offset(self):
        symbols = dict(self.BASE)
        del symbols["TOP_REG_MAP_SIZE"]
        with self.assertRaisesRegex(ValueError, "TOP_REG_MAP_SIZE"):
            load_model(_module(**symbols))
        symbols = dict(self.BASE)
        del symbols["A_REG_OFFSET"]
        with self.assertRaisesRegex(ValueError, "A_REG_OFFSET"):
            load_model(_module(**symbols))

    def test_register_outside_every_window(self):
        symbols = dict(self.BASE, A_REG_ADDR=0x40)
        with self.assertRaisesRegex(ValueError, "no addrmap window"):
            load_model(_module(**symbols))

    def test_shared_address(self):
        symbols = dict(self.BASE, B_REG_OFFSET=0x0, B_REG_ADDR=0x0, B_REG_TYPE="T")
        model = load_model(_module(**symbols))
        self.assertEqual([r.symbol for r in model.at(0x0)], ["A", "B"])
        with self.assertRaises(LookupError):
            model.by_addr(0x0)

    def test_array_gap(self):
        symbols = dict(self.BASE, X_0__REG_OFFSET=0x4, X_0__REG_ADDR=0x4, X_0__REG_TYPE="T")
        symbols.update(X_2__REG_OFFSET=0x8, X_2__REG_ADDR=0x8, X_2__REG_TYPE="T")
        with self.assertRaisesRegex(KeyError, "not contiguous"):
            load_model(_module(**symbols)).array_count("X")


if __name__ == "__main__":
    unittest.main()
