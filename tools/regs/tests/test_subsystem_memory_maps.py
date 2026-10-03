# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

from __future__ import annotations

import re
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
        "vendor/chipsalliance/adams-bridge/upstream/src/abr_top/rtl",
        "vendor/chipsalliance/i3c-core/upstream/src/rdl",
        "vendor/chipsalliance/i3c-core/upstream/src/rdl/tt_rdl",
    )
    return sorted({path for pattern in patterns for path in ROOT.glob(pattern)})


def configured_views(config_path: str, rdl: str | None = None, top: str | None = None):
    config = load_config(ROOT / config_path)
    if config.get("sources"):
        roots = {
            source["name"]: compile_root(
                ROOT / source["rdl"],
                UDP,
                catalog(),
                source["top"],
            )
            for source in config["sources"]
        }
    else:
        if rdl is None or top is None:
            raise ValueError(f"{config_path}: rdl and top are required")
        roots = {"main": compile_root(ROOT / rdl, UDP, catalog(), top)}
    return build_views(config, roots)


def one_view(rdl: str, config: str, top: str):
    return configured_views(config, rdl, top)[0]


def rows_by_key(view):
    return {row.key: row for row in view.rows}


def sv_hex(source: str, name: str) -> int:
    match = re.search(rf"\b{name}\s*=\s*\d+'h([0-9a-fA-F_]+)", source)
    if not match:
        raise AssertionError(f"SystemVerilog constant {name} not found")
    return int(match.group(1).replace("_", ""), 16)


class SubsystemMemoryMapsTest(unittest.TestCase):
    def test_configured_maps_build_from_rdl(self):
        specs = (
            (
                "hw/sys/smc/regs/smc.rdl",
                "hw/sys/smc/doc/memmap.toml",
                "smc_top",
            ),
            (
                "hw/ip/key_manager/regs/key_manager.rdl",
                "hw/ip/key_manager/doc/memmap.toml",
                "key_manager",
            ),
            (
                "hw/ip/cross_trigger/cross_trigger_network/regs/cross_trigger_network.rdl",
                "hw/ip/cross_trigger/cross_trigger_network/doc/memmap.toml",
                "cross_trigger_network",
            ),
        )
        for rdl, config, top in specs:
            with self.subTest(rdl=rdl):
                view = one_view(rdl, config, top)
                self.assertTrue(view.rows)

    def test_multi_source_maps_build_from_rdl(self):
        for config_path in (
            "hw/sys/sep/doc/memmap.toml",
            "hw/ip/efuse/doc/memmap.toml",
            "hw/ip/axi_lite_mailbox_unit/doc/memmap.toml",
        ):
            with self.subTest(config=config_path):
                views = configured_views(config_path)
                self.assertTrue(views)
                self.assertTrue(all(view.rows for view in views))

    def test_rtl_decode_matches_canonical_maps(self):
        sep_crypto = (ROOT / "hw/sys/sep/rtl/sep_crypto_pkg.sv").read_text()
        sep_addrmap = (ROOT / "hw/sys/sep/regs/gen/sv/sep_addrmap_pkg.sv").read_text()
        smc_addrmap = (ROOT / "hw/sys/smc/regs/gen/sv/smc_addrmap_pkg.sv").read_text()
        smc_xbar = (ROOT / "hw/sys/smc/rtl/crossbars/smc_local_xbar.sv").read_text()
        smc_periph_xbar = (
            ROOT / "hw/sys/smc/rtl/crossbars/smc_periph_axi_lite_xbar.sv"
        ).read_text()
        smc_internal_xbar = (
            ROOT / "hw/sys/smc/rtl/crossbars/smc_internal_axi_lite_xbar.sv"
        ).read_text()
        km_intf = (ROOT / "hw/ip/key_manager/rtl/km_intf_pkg.sv").read_text()

        sep = rows_by_key(
            next(
                view
                for view in configured_views("hw/sys/sep/doc/memmap.toml")
                if view.name == "sep-components"
            )
        )
        self.assertEqual(sep["main:trng"].base, sv_hex(sep_crypto, "TrngBaseAddr"))
        self.assertEqual(sep["main:abr"].base, sv_hex(sep_addrmap, "SEP_TOP_ABR_BASE_ADDR"))
        self.assertEqual(sep["main:abr"].occupied_size, sv_hex(sep_addrmap, "SEP_TOP_ABR_SIZE"))
        self.assertIn("SEP_TOP_ABR_SIZE", sep_crypto)
        self.assertEqual(
            sep["main:entropy_pool"].base,
            sv_hex(sep_addrmap, "SEP_TOP_ENTROPY_POOL_BASE_ADDR"),
        )

        smc = rows_by_key(
            next(
                view
                for view in configured_views(
                    "hw/sys/smc/doc/memmap.toml",
                    "hw/sys/smc/regs/smc.rdl",
                    "smc_top",
                )
                if view.name == "smc-components"
            )
        )
        self.assertEqual(
            smc["main:smc_avsbus_controller"].base,
            sv_hex(smc_addrmap, "SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR"),
        )
        self.assertIn("SMC_TOP_SMC_AVSBUS_CONTROLLER_BASE_ADDR", smc_periph_xbar)
        self.assertEqual(
            smc["main:smc_cpu_ctrl"].base,
            sv_hex(smc_addrmap, "SMC_TOP_SMC_CPU_CTRL_BASE_ADDR"),
        )
        self.assertIn("SMC_TOP_SMC_CPU_CTRL_BASE_ADDR", smc_xbar)
        self.assertEqual(
            smc["main:oca_i3c_wrap"].base,
            sv_hex(smc_addrmap, "SMC_TOP_OCA_I3C_WRAP_BASE_ADDR"),
        )
        self.assertIn("SMC_TOP_OCA_I3C_WRAP_BASE_ADDR", smc_xbar)
        self.assertEqual(
            smc["main:smc_mailbox"].base,
            sv_hex(smc_addrmap, "SMC_TOP_SMC_MAILBOX_BASE_ADDR"),
        )
        self.assertIn("SMC_TOP_SMC_MAILBOX_BASE_ADDR", smc_internal_xbar)
        self.assertEqual(
            smc["main:smc_mailbox"].occupied_size,
            sv_hex(smc_addrmap, "SMC_TOP_SMC_MAILBOX_SIZE"),
        )
        self.assertEqual(
            smc["main:smc_cluster_plic"].base,
            sv_hex(smc_addrmap, "SMC_TOP_SMC_CLUSTER_PLIC_BASE_ADDR"),
        )
        self.assertIn("SMC_TOP_SMC_CLUSTER_PLIC_BASE_ADDR", smc_xbar)
        self.assertEqual(
            smc["main:smc_cluster_plic"].occupied_size,
            sv_hex(smc_addrmap, "SMC_TOP_SMC_CLUSTER_PLIC_SIZE"),
        )
        self.assertEqual(
            smc["main:smc_cluster_clint"].base,
            sv_hex(smc_addrmap, "SMC_TOP_SMC_CLUSTER_CLINT_BASE_ADDR"),
        )
        self.assertIn("SMC_TOP_SMC_CLUSTER_CLINT_BASE_ADDR", smc_xbar)

        km = rows_by_key(
            one_view(
                "hw/ip/key_manager/regs/key_manager.rdl",
                "hw/ip/key_manager/doc/memmap.toml",
                "key_manager",
            )
        )
        for node, prefix in (("rom", "Rom"), ("sram", "Sram")):
            base = sv_hex(km_intf, f"{prefix}BaseAddr")
            end = sv_hex(km_intf, f"{prefix}EndAddr")
            self.assertEqual(km[f"main:{node}"].base, base)
            self.assertEqual(km[f"main:{node}"].aperture_size, end - base + 1)

    def test_response_cells(self):
        def hole(row):
            ((_label, response),) = row.hole_responses
            return response.text

        km_view = one_view(
            "hw/ip/key_manager/regs/key_manager.rdl",
            "hw/ip/key_manager/doc/memmap.toml",
            "key_manager",
        )
        km = rows_by_key(km_view)
        self.assertEqual(hole(km["main:kmcsr"]), "SLVERR, 0x0 / SLVERR")
        self.assertEqual(km["main:mailbox_km"].past_response.text, "SLVERR, 0x0 / SLVERR")
        reserved = [row for row in km_view.rows if row.kind == "reserved"]
        self.assertTrue(reserved)
        for row in reserved:
            self.assertEqual(hole(row), "DECERR, 0xBADCAB1E / DECERR")

        sep = rows_by_key(
            next(
                view
                for view in configured_views("hw/sys/sep/doc/memmap.toml")
                if view.name == "sep-components"
            )
        )
        self.assertEqual(
            sep["main:km_mailbox_sep"].past_response.text, "DECERR, 0xBADCAB1E / DECERR"
        )

        smc = rows_by_key(
            next(
                view
                for view in configured_views(
                    "hw/sys/smc/doc/memmap.toml",
                    "hw/sys/smc/regs/smc.rdl",
                    "smc_top",
                )
                if view.name == "smc-components"
            )
        )
        self.assertEqual(hole(smc["main:smc_external"]), "Adopter-defined")
        self.assertEqual(hole(smc["main:mmode_region"]), "Forwarded")
        self.assertNotIn("main:ecam_region", smc)


if __name__ == "__main__":
    unittest.main()
