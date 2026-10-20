# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Field classes, masks, word views and reason arms over the fixture header."""

import sys
import unittest
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fixture_reg  # noqa: E402
from ocah_regwalk import (  # noqa: E402
    FieldClass as C,
)
from ocah_regwalk import (  # noqa: E402
    FieldSpec,
    classify_field,
    is_reserved,
    load_model,
    reg_masks,
    reset_reason,
    word_view,
    write_reason,
)

MODEL = load_model(fixture_reg)


def classes(symbol: str) -> dict[str, frozenset]:
    return {f.name: classify_field(f) for f in MODEL.by_symbol(symbol).fields}


class Classes(unittest.TestCase):
    def test_sw_and_hw(self):
        mode = classes("CTRL_MODE")
        self.assertEqual(mode["en"], {C.RW})
        self.assertEqual(mode["rsvd0"], {C.RO})
        self.assertEqual(mode["busy"], {C.RO, C.HW_DRIVEN})
        self.assertEqual(classes("CTRL_ID")["id"], {C.RO, C.UNRESET})
        self.assertEqual(classes("CTRL_TRIG")["go"], {C.WO, C.PULSE})

    def test_write_and_read_modifiers(self):
        self.assertEqual(classes("CTRL_IRQ")["pending"], {C.RW, C.W1C, C.HW_DRIVEN})
        self.assertEqual(classes("CTRL_LOCK")["lock"], {C.RW, C.W1S})
        flags = classes("CTRL_FLAGS")
        self.assertEqual(flags["err"], {C.RW, C.W0C, C.HW_DRIVEN})
        self.assertEqual(flags["evt"], {C.RW, C.RC, C.HW_DRIVEN})
        self.assertEqual(flags["tok"], {C.RO, C.RS, C.HW_DRIVEN})
        self.assertEqual(flags["once"], {C.RW, C.WRITE_ONCE})
        self.assertEqual(flags["arm"], {C.WO, C.WRITE_ONCE})
        self.assertEqual(flags["all"], {C.RW, C.WSET})
        self.assertEqual(flags["none"], {C.RW, C.WCLR})
        self.assertEqual(flags["tgl"], {C.RW, C.WOT})
        self.assertEqual(flags["ztg"], {C.RW, C.WZT})
        self.assertEqual(flags["zst"], {C.RW, C.W0S})
        self.assertEqual(flags["usr"], {C.RW, C.WUSER, C.RUSER})
        self.assertEqual(flags["hid"], {C.HW_DRIVEN})

    def test_every_class_is_reachable(self):
        seen = set()
        for reg in MODEL.registers:
            for field in reg.fields:
                seen |= classify_field(field)
        self.assertEqual(seen, set(C))

    def test_unknown_property_raises(self):
        bad = FieldSpec("x", 0, 0, "rw", "r", "wnew", "", False, False, 0)
        with self.assertRaisesRegex(ValueError, "wnew"):
            classify_field(bad)
        bad = FieldSpec("x", 0, 0, "rx", "r", "", "", False, False, 0)
        with self.assertRaisesRegex(ValueError, "rx"):
            classify_field(bad)

    def test_reserved_names(self):
        for name in ("rsvd", "rsvd0", "rsvd_0", "Rsvd3116", "reserved", "RESERVED_7_3", "RSVD0"):
            self.assertTrue(
                is_reserved(FieldSpec(name, 0, 0, "r", "r", "", "", False, False, 0)), name
            )
        for name in ("test_reserved", "rsvdx", "reserved_bits"):
            self.assertFalse(
                is_reserved(FieldSpec(name, 0, 0, "r", "r", "", "", False, False, 0)), name
            )


class Masks(unittest.TestCase):
    def test_mode(self):
        m = reg_masks(MODEL.by_symbol("CTRL_MODE"))
        self.assertEqual(m.storage, 0x0001_0FFF)
        self.assertEqual(m.sw_usable, 0x0001_000F)
        self.assertEqual(m.reserved, 0x0000_0FF0)
        self.assertEqual(m.plain_rw, 0x0000_0F0F)
        self.assertEqual(m.static_reset, 0x0000_0FFF)
        self.assertEqual(m.unreset, 0)
        self.assertEqual(m.unimplemented, 0xFFFE_F000)
        self.assertEqual((m.write_destructive, m.read_destructive), (0, 0))

    def test_flags(self):
        m = reg_masks(MODEL.by_symbol("CTRL_FLAGS"))
        self.assertEqual(m.storage, 0x7FFF)
        self.assertEqual(m.sw_usable, 0x3FFF)
        self.assertEqual(m.plain_rw, 0)
        self.assertEqual(m.static_reset, 0x3F40)
        self.assertEqual(m.write_destructive, 0x3F03)
        self.assertEqual(m.read_destructive, 0x203C)

    def test_unreset_and_wide(self):
        self.assertEqual(reg_masks(MODEL.by_symbol("CTRL_SEED")).unreset, 0xFFFF)
        self.assertEqual(reg_masks(MODEL.by_symbol("CTRL_STATUS")).unreset, 0xFF00)
        key = reg_masks(MODEL.by_symbol("WIDE_KEY"))
        self.assertEqual(key.storage, (1 << 256) - 1)
        self.assertEqual(key.plain_rw, 0)
        self.assertEqual(key.static_reset, 0)


class Words(unittest.TestCase):
    def test_word_views_of_a_wide_register(self):
        cfg = MODEL.by_symbol("WIDE_CFG")
        lo, hi = word_view(cfg, 0), word_view(cfg, 1)
        self.assertEqual((lo.addr, lo.index, lo.reset), (0x2020, 0, 5))
        self.assertEqual((hi.addr, hi.index, hi.reset), (0x2024, 1, 0))
        self.assertEqual((lo.masks.unreset, hi.masks.unreset), (0, 0xFFFF_FFFF))
        self.assertEqual((lo.masks.static_reset, hi.masks.static_reset), (0xFFFF_FFFF, 0))
        attrs = MODEL.by_symbol("BANK_0__REGION_ATTRS")
        self.assertEqual(word_view(attrs, 1).masks.storage, 0x8000_0000)
        self.assertEqual(word_view(attrs, 1).masks.unimplemented, 0x7FFF_FFFF)
        self.assertEqual(word_view(MODEL.by_symbol("WIDE_KEY"), 7).addr, 0x201C)
        with self.assertRaises(IndexError):
            word_view(cfg, 2)

    def test_a_32_bit_register_is_its_own_word(self):
        mode = MODEL.by_symbol("CTRL_MODE")
        view = word_view(mode)
        self.assertEqual(
            (view.addr, view.reset, view.masks), (mode.addr, mode.reset, reg_masks(mode))
        )


class Reasons(unittest.TestCase):
    def reason(self, fn, symbol, **kw):
        return fn(MODEL.by_symbol(symbol), **kw)

    def test_reset_arms(self):
        self.assertEqual(
            self.reason(reset_reason, "CTRL_TRIG"), "sw=w; a read does not return storage"
        )
        self.assertEqual(
            self.reason(reset_reason, "CTRL_ID"),
            "sw=r with no declared reset; hardware drives the value",
        )
        self.assertEqual(
            self.reason(reset_reason, "CTRL_SEED"),
            "no field with an RDL reset; the default is a placeholder",
        )
        for symbol in ("CTRL_MODE", "CTRL_IRQ", "CTRL_STATUS", "WIDE_KEY", "WIDE_CFG", "VERSION"):
            self.assertIsNone(self.reason(reset_reason, symbol), symbol)

    def test_write_arms(self):
        self.assertEqual(
            self.reason(write_reason, "CTRL_TRIG"), "sw=w; a read does not return storage"
        )
        self.assertEqual(
            self.reason(write_reason, "CTRL_ID"),
            "sw=r with no declared reset; hardware drives the value",
        )
        self.assertEqual(self.reason(write_reason, "CTRL_MODE", mask=0), "no software-usable field")
        self.assertEqual(
            self.reason(write_reason, "VERSION"), "sw=r; a write does not reach storage"
        )
        self.assertEqual(
            self.reason(write_reason, "CTRL_MODE"),
            "sw=r field inside the mask; the written value does not land",
        )
        self.assertEqual(
            self.reason(write_reason, "CTRL_IRQ"),
            "woclr field inside the mask; a write does not land as written",
        )
        self.assertEqual(
            self.reason(write_reason, "CTRL_LOCK"),
            "woset field inside the mask; a write does not land as written",
        )
        self.assertEqual(
            self.reason(write_reason, "CTRL_IRQ", mask=0x0F),
            "woclr field inside the mask; a write does not land as written",
        )
        self.assertEqual(
            self.reason(write_reason, "CTRL_FLAGS", mask=0x1000),
            "wzs field inside the mask; a write does not land as written",
        )
        self.assertEqual(
            self.reason(write_reason, "CTRL_FLAGS", mask=0x0C),
            "rclr field inside the mask; a read changes the value",
        )

    def test_singlepulse_and_volatile_inside_the_mask(self):
        trig = MODEL.by_symbol("CTRL_TRIG")
        rw_pulse = replace(trig, fields=(FieldSpec("go", 0, 0, "rw", "r", "", "", True, False, 0),))
        self.assertEqual(
            write_reason(rw_pulse),
            "singlepulse field inside the mask; the written value self-clears",
        )
        irq = MODEL.by_symbol("CTRL_IRQ")
        pending = FieldSpec("pending", 0, 3, "rw", "w", "", "", False, True, 0)
        with_volatile = replace(irq, fields=(pending, irq.fields[1]))
        self.assertEqual(
            write_reason(with_volatile),
            "volatile field inside the mask; hardware may change the value",
        )
        self.assertIsNone(write_reason(with_volatile, mask=0xF0))

    def test_require_reset_false_keeps_only_the_readback_arm(self):
        seed = MODEL.by_symbol("CTRL_SEED")
        self.assertEqual(
            write_reason(seed), "no field with an RDL reset; the default is a placeholder"
        )
        self.assertIsNone(write_reason(seed, require_reset=False))
        self.assertIsNone(write_reason(seed, mask=reg_masks(seed).plain_rw, require_reset=False))
        self.assertEqual(
            self.reason(write_reason, "CTRL_ID", require_reset=False),
            "sw=r; a write does not reach storage",
        )
        self.assertEqual(
            self.reason(write_reason, "CTRL_TRIG", require_reset=False),
            "sw=w; a read does not return storage",
        )

    def test_plain_rw_mask_admits_plain_storage(self):
        for symbol in ("CTRL_MODE", "CTRL_IRQ", "CTRL_DMA_1_", "WIDE_CFG", "BANK_1__REGION_ATTRS"):
            reg = MODEL.by_symbol(symbol)
            self.assertIsNone(write_reason(reg, mask=reg_masks(reg).plain_rw), symbol)
        self.assertIsNone(write_reason(MODEL.by_symbol("CTRL_DMA_0_")))


if __name__ == "__main__":
    unittest.main()
