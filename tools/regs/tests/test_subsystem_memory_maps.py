# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import unittest
from pathlib import Path

from tools.regs.common.memorymap import build_views, compile_root, load_config

ROOT = Path(__file__).resolve().parents[3]
UDP = ROOT / "hw/common/regs/regblock_udps.rdl"


def catalog() -> list[Path]:
    patterns = (
        "hw/ip/*/regs",
        "hw/ip/*/*/regs",
        "hw/ip/*/regs/include",
        "hw/ip/*/*/regs/include",
        "hw/ip/*/regs/blocks/*",
        "hw/ip/*/*/regs/blocks/*",
        "hw/sys/*/regs",
        "hw/sys/*/regs/include",
        "hw/sys/*/regs/blocks/*",
        "hw/sys/*/dv/models/regs",
        "hw/ip/*/dv/models/regs",
        "hw/ip/*/*/dv/models/regs",
        "vendor/*/*/overlay/regs/*/regs",
        "vendor/*/*/overlay/regs/*/regs/include",
        "vendor/*/*/overlay/rdl",
        "vendor/chipsalliance/i3c-core/upstream/src/rdl",
        "vendor/chipsalliance/i3c-core/upstream/src/rdl/tt_rdl",
    )
    return sorted({path for pattern in patterns for path in ROOT.glob(pattern)})


def one_view(rdl: str, config: str, top: str):
    root = compile_root(ROOT / rdl, UDP, catalog(), top)
    return build_views(load_config(ROOT / config), {"main": root})[0]


def rows_by_key(view):
    return {row.key: row for row in view.rows}


class SubsystemMemoryMapsTest(unittest.TestCase):
    def test_sep_reconciled_windows(self):
        views = build_views(
            load_config(ROOT / "hw/sys/sep/regs/memmap.toml"),
            {"main": compile_root(ROOT / "hw/sys/sep/regs/sep.rdl", UDP, catalog(), "och_sep_top")},
        )
        rows = rows_by_key(next(view for view in views if view.name == "sep-components"))
        self.assertEqual(rows["main:sep_sram"].aperture_size, 0x40000)
        self.assertEqual(rows["main:trng"].base, 0x10917000)
        self.assertEqual(rows["main:abr"].aperture_size, 0x10000)
        self.assertEqual(rows["main:entropy_pool"].base, 0x10950000)

    def test_smc_current_decode(self):
        views = build_views(
            load_config(ROOT / "hw/sys/smc/regs/memmap.toml"),
            {"main": compile_root(ROOT / "hw/sys/smc/regs/smc.rdl", UDP, catalog(), "smc_top")},
        )
        view = next(view for view in views if view.name == "smc-components")
        rows = rows_by_key(view)
        self.assertEqual(rows["main:smc_avsbus_controller"].base, 0xC0004000)
        self.assertEqual(rows["main:smc_cpu_ctrl"].base, 0xC0039000)
        self.assertEqual(rows["main:oca_i3c_wrap"].base, 0xC003A000)
        self.assertEqual(rows["main:smc_mailbox"].aperture_size, 0x20000)

    def test_key_manager_memories_and_windows(self):
        view = one_view(
            "hw/ip/key_manager/regs/key_manager.rdl",
            "hw/ip/key_manager/regs/memmap.toml",
            "key_manager",
        )
        rows = rows_by_key(view)
        self.assertEqual(rows["main:rom"].aperture_size, 0x4000)
        self.assertEqual(rows["main:sram"].base, 0x8000)
        self.assertEqual(rows["main:kpv"].aperture_size, 0x2000)

    def test_cross_trigger_count_and_stride(self):
        view = one_view(
            "hw/ip/cross_trigger/cross_trigger_network/regs/cross_trigger_network.rdl",
            "hw/ip/cross_trigger/cross_trigger_network/regs/memmap.toml",
            "cross_trigger_network",
        )
        rows = rows_by_key(view)
        self.assertEqual(rows["main:ctp"].count, 16)
        self.assertEqual(rows["main:ctp"].stride, 0x10)
        self.assertEqual(rows["main:ctm"].aperture_size, 0x200)

    def test_mailbox_pair_layouts(self):
        config = load_config(ROOT / "hw/ip/axi_lite_mailbox_unit/regs/memmap.toml")
        roots = {
            source["name"]: compile_root(ROOT / source["rdl"], UDP, catalog(), source["top"])
            for source in config["sources"]
        }
        views = {view.name: view for view in build_views(config, roots)}
        smc = views["smc-mailboxes"].rows
        sep = views["sep-mailboxes"].rows
        self.assertEqual((len(smc), smc[0].base, smc[-1].base), (64, 0, 0x1F800))
        self.assertEqual((len(sep), sep[0].base, sep[-1].base), (16, 0, 0x7800))
        self.assertTrue(all(row.aperture_size == 0x800 for row in (*smc, *sep)))

    def test_rtl_decode_matches_canonical_maps(self):
        sep_crypto = (ROOT / "hw/sys/sep/rtl/sep_crypto_pkg.sv").read_text()
        sep_xbar = (ROOT / "hw/sys/sep/rtl/sep_local_axi_xbar_pkg.sv").read_text()
        smc_xbar = (ROOT / "hw/sys/smc/rtl/crossbars/smc_local_xbar_pkg.sv").read_text()
        self.assertIn("TRNG_BASE_ADDR = 32'h1091_7000", sep_crypto)
        self.assertIn("ABR_REG_MAP_BASE_ADDR = 32'h1094_0000", sep_crypto)
        self.assertIn("ENTROPY_FIFO_MAIN_BASE = 32'h10950000", sep_xbar)
        self.assertIn("FRONT_PORT_PLIC_BASE = 32'hc4000000", smc_xbar)
        self.assertIn("FRONT_PORT_PLIC_SIZE = 32'h4000000", smc_xbar)
        self.assertIn("FRONT_PORT_CLINT_BEU_BASE = 32'hc8000000", smc_xbar)


if __name__ == "__main__":
    unittest.main()
