# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The model over the committed SMC and SEP headers, against the headers and the SEP walk.

The SEP walk in ``hw/sys/sep/dv/cocotb/env/sep_reg_meta.py`` binds an instance to
its type by guessing the type name from the instance name, and takes access from
the IP-XACT by address. The model binds through ``_REG_TYPE``. The two are
compared here register by register, and the registers the walk drops are
accounted for by cause.
"""

import importlib.util
import sys
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(REPO / "hw" / "common" / "dv" / "vip"))
sys.path.insert(0, str(REPO / "hw" / "sys" / "sep" / "dv" / "cocotb" / "env"))

from ocah_regwalk import load_model, reg_masks, reset_reason, word_view  # noqa: E402

SMC = REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "py" / "smc_reg.py"
SEP = REPO / "hw" / "sys" / "sep" / "regs" / "gen" / "py" / "sep_reg.py"
WORD = 0xFFFF_FFFF


def header(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class HeaderAgreement(unittest.TestCase):
    """Facts the model must reproduce from the header it was read from."""

    def check(self, path: Path):
        module = header(path)
        model = load_model(module)
        ns = vars(module)
        addr_symbols = [n for n in ns if n.endswith("_REG_ADDR")]
        self.assertEqual(len(model.registers), len(addr_symbols))
        self.assertEqual(len(model.blocks), sum(n.endswith("_REG_MAP_BASE_ADDR") for n in ns))
        self.assertEqual(len(model.types), sum(n.endswith("_REG_FIELDS") for n in ns))
        for reg in model.registers:
            self.assertEqual(reg.addr, ns[reg.symbol + "_REG_ADDR"])
            self.assertEqual(reg.offset, ns[reg.symbol + "_REG_OFFSET"])
            self.assertTrue(model.block(reg.block).contains(reg.addr), reg.symbol)
            holders = [w for w in model.windows if w.contains(reg.addr)]
            self.assertIn(reg.addr - reg.offset, [w.base for w in holders], reg.symbol)
            default = ns.get(reg.type_name + "_REG_DEFAULT")
            if default is None:
                self.assertGreater(reg.width, 64, reg.symbol)
            else:
                self.assertEqual(reg.reset, default, reg.symbol)
            self.assertLessEqual(reg_masks(reg).storage.bit_length(), reg.width, reg.symbol)
        return model

    def test_smc(self):
        model = self.check(SMC)
        self.assertEqual(model.top.name, "SMC_TOP")
        ports = model.at(model.by_symbol("OCA_I3C_WRAP_I3C_CSR_0__PIOCONTROL_TX_DATA_PORT").addr)
        self.assertEqual(len(ports), 2)
        with self.assertRaises(LookupError):
            model.by_addr(ports[0].addr)
        self.assertEqual(model.array_count("OCA_I3C_WRAP_I3C_CSR"), 6)
        scratch = model.by_symbol("SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_0_")
        self.assertEqual(
            (scratch.block, scratch.name, scratch.index),
            ("SMC_MISC_WRAP_SCRATCH_COLD_WARM", "SCRATCH_0_", 0),
        )

    def test_sep(self):
        model = self.check(SEP)
        self.assertEqual(model.top.name, "SEP_TOP")
        self.assertEqual(model.array_count("INBOUND_FILTER_CTRL"), 16)
        self.assertEqual(model.array_count("OUTBOUND_FILTER_CTRL"), 32)
        attrs = model.by_symbol("LOCAL_MASTER_ALIAS_REMAP_CTRL_3__REGION_REGION_ATTRS")
        self.assertEqual(
            (attrs.block, attrs.name, attrs.index),
            ("LOCAL_MASTER_ALIAS_REMAP_CTRL_3_", "REGION_REGION_ATTRS", None),
        )
        self.assertEqual(attrs.field("valid").lsb, 63)
        self.assertEqual(model.block("KM_MAILBOX_SEP").size, 0x1C)


class SepWalkPartition(unittest.TestCase):
    """The model against the walk sep_reg_meta.py performs today."""

    @classmethod
    def setUpClass(cls):
        import sep_reg_meta

        cls.meta = sep_reg_meta
        cls.walk = sep_reg_meta.iter_register_walk()
        cls.model = load_model(SEP)
        cls.by_addr = {reg.addr: reg for reg in cls.model.registers}

    def test_counts(self):
        walk = self.walk
        self.assertEqual((walk.export, walk.inventory, walk.nometa), (2126, 1952, 174))
        self.assertEqual(len(self.model.registers), walk.export)
        self.assertEqual(len(self.by_addr), walk.export)

    def test_inventory_rows_agree(self):
        """Every register the walk keeps has the same block, name, reset and masks here.

        The walk's storage mask comes from the generated ctypes struct, whose
        ``rsvd_N`` fillers occupy every gap below the highest field, so it equals
        every bit up to that field; the model reports the gaps as
        ``unimplemented`` instead. ENTROPY_SOURCE.CTRL names its bit 0 ``RSVD0``,
        which the walk's case-sensitive reserved-name match keeps software-usable
        and ``RESERVED_NAME`` does not.
        """
        differ = []
        for info in self.walk.regs:
            reg = self.by_addr[info.addr]
            word = word_view(reg, 0)
            filled = ((1 << reg_masks(reg).storage.bit_length()) - 1) & WORD
            got = (
                reg.block,
                reg.name,
                word.reset,
                filled,
                word.masks.sw_usable,
                word.masks.unreset,
            )
            want = (info.block, info.name, info.reset, info.mask_all, info.mask, info.unreset)
            if got != want:
                differ.append((f"{info.block}.{info.name}", got, want))
        self.assertEqual([d[0] for d in differ], ["ENTROPY_SOURCE.CTRL"])
        got, want = differ[0][1:]
        self.assertEqual(got[4] | 1, want[4])
        self.assertEqual(got[:4] + got[5:], want[:4] + want[5:])

    def test_dropped_rows_by_cause(self):
        """The 174 registers the walk drops all have a type binding here.

        30 are 256 bits wide, for which the header emits no ``_REG_DEFAULT`` and
        the walk has no reset to compare. The other 144 have a ``_REG_DEFAULT``
        under their type name; the walk cannot find it from the instance name,
        the model reads ``_REG_TYPE``.
        """
        kept = {info.addr for info in self.walk.regs}
        dropped = [reg for reg in self.model.registers if reg.addr not in kept]
        self.assertEqual(len(dropped), self.walk.nometa)
        wide = [reg for reg in dropped if reg.width > 64]
        named = [reg for reg in dropped if reg.width <= 64]
        self.assertEqual((len(wide), len(named)), (30, 144))
        ns = vars(self.meta.sep_reg)
        for reg in wide:
            self.assertNotIn(reg.type_name + "_REG_DEFAULT", ns, reg.symbol)
        for reg in named:
            self.assertEqual(reg.reset, ns[reg.type_name + "_REG_DEFAULT"], reg.symbol)
            self.assertFalse(
                hasattr(self.meta.sep_reg, f"{reg.block}_{reg.name}_REG_DEFAULT"), reg.symbol
            )

    def test_access_shapes_match_the_ipxact_join(self):
        """The reset arms reproduce the IP-XACT access shapes the walk pins."""
        kept = [self.by_addr[info.addr] for info in self.walk.regs]
        hw_driven = sorted(
            f"{r.block}.{r.name}"
            for r in kept
            if reset_reason(r) == "sw=r with no declared reset; hardware drives the value"
        )
        expected = sorted(f"{i.block}.{i.name}" for i in self.walk.regs if i.access.hw_driven)
        self.assertEqual(hw_driven, expected)
        self.assertEqual(len(expected), 29)
        write_only = [r for r in kept if reset_reason(r) == "sw=w; a read does not return storage"]
        self.assertEqual(len(write_only), 555)
        self.assertEqual(len(write_only), sum(i.access.write_only for i in self.walk.regs))


if __name__ == "__main__":
    unittest.main()
