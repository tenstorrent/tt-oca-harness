# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Exclusion lookup order and the accounting of an inventory."""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import fixture_reg  # noqa: E402
from ocah_regwalk import ExclusionSet, load_model, reset_reason  # noqa: E402

MODEL = load_model(fixture_reg)


class Reason(unittest.TestCase):
    def test_lookup_order(self):
        excl = ExclusionSet(
            named={
                ("CTRL", "DMA"): "array",
                ("CTRL", "DMA_1_"): "element",
                ("WIDE", None): "block",
            },
            name_suffix={"ATTRS": "suffix"},
            name_prefix={"SE": "prefix"},
            name_substring={"RI": "substring"},
            block_prefix={"FIX": "top"},
        )
        by = {s: excl.reason(MODEL.by_symbol(s)) for s in (r.symbol for r in MODEL.registers)}
        self.assertEqual(by["CTRL_DMA_0_"], "array")
        self.assertEqual(by["CTRL_DMA_1_"], "element")
        self.assertEqual(by["WIDE_KEY"], "block")
        self.assertEqual(by["BANK_0__REGION_ATTRS"], "suffix")
        self.assertEqual(by["CTRL_SEED"], "prefix")
        self.assertEqual(by["CTRL_TRIG"], "substring")
        self.assertEqual(by["VERSION"], "top")
        self.assertIsNone(by["CTRL_MODE"])

    def test_suffix_needs_a_token_boundary(self):
        excl = ExclusionSet(name_suffix={"D": "x"})
        self.assertIsNone(excl.reason(MODEL.by_symbol("CTRL_SEED")))
        self.assertIsNone(excl.reason(MODEL.by_symbol("CTRL_ID")))
        excl = ExclusionSet(name_suffix={"ID": "x"})
        self.assertEqual(excl.reason(MODEL.by_symbol("CTRL_ID")), "x")

    def test_entries_need_a_reason(self):
        with self.assertRaisesRegex(ValueError, "needs a reason"):
            ExclusionSet(named={("CTRL", "MODE"): ""})


class Account(unittest.TestCase):
    def test_partition_and_tally(self):
        excl = ExclusionSet(named={("CTRL", "LOCK"): "lock", ("BANK_0_", None): "bank"})
        part = excl.account(MODEL.registers, reset_reason)
        admitted = {r.symbol for r in part.admitted}
        self.assertNotIn("CTRL_TRIG", admitted)
        self.assertIn("CTRL_MODE", admitted)
        self.assertEqual(
            part.tally(),
            {
                "bank": 1,
                "lock": 1,
                "no field with an RDL reset; the default is a placeholder": 1,
                "sw=r with no declared reset; hardware drives the value": 1,
                "sw=w; a read does not return storage": 1,
            },
        )
        self.assertEqual(excl.tally(), part.tally())
        self.assertTrue(part.summary().startswith(f"admitted={len(part.admitted)} excluded=5 ["))
        self.assertEqual(len(part.admitted) + len(part.excluded), len(MODEL.registers))

    def test_admitted_must_cover_the_rest(self):
        excl = ExclusionSet(named={("CTRL", "LOCK"): "lock"})
        swept = [r for r in MODEL.registers if r.symbol not in ("CTRL_LOCK", "CTRL_SEED")]
        with self.assertRaisesRegex(LookupError, "neither admitted nor excluded.*CTRL_SEED"):
            excl.account(MODEL.registers, admitted=swept)
        part = excl.account(MODEL.registers, admitted=swept + ["CTRL_SEED"])
        self.assertEqual(len(part.admitted), len(MODEL.registers) - 1)

    def test_admitted_register_with_a_reason_is_a_conflict(self):
        excl = ExclusionSet(named={("CTRL", "LOCK"): "lock"})
        with self.assertRaisesRegex(LookupError, "carry an exclusion: CTRL_LOCK"):
            excl.account(MODEL.registers, admitted=[r.symbol for r in MODEL.registers])

    def test_admitted_symbol_absent_from_the_inventory(self):
        excl = ExclusionSet()
        with self.assertRaisesRegex(LookupError, "absent from the inventory: CTRL_GONE"):
            excl.account(
                MODEL.registers, admitted=[r.symbol for r in MODEL.registers] + ["CTRL_GONE"]
            )

    def test_stale_named_entries(self):
        excl = ExclusionSet(named={("CTRL", "GONE"): "x", ("NOPE", None): "y"})
        with self.assertRaisesRegex(LookupError, "match no register: CTRL.GONE, NOPE.None"):
            excl.account(MODEL.registers)
        excl.account(MODEL.registers, strict=False)
        excl = ExclusionSet(named={("CTRL", "TRIG"): "named too"})
        excl.account(MODEL.registers, reset_reason)
        self.assertEqual(excl.tally()["sw=w; a read does not return storage"], 1)

    def test_tally_before_account(self):
        with self.assertRaises(RuntimeError):
            ExclusionSet().tally()


if __name__ == "__main__":
    unittest.main()
