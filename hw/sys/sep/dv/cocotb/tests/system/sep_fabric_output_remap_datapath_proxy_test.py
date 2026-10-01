# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Live AP/STEE output-remap plus outbound-filter drop.

RANDCFG. Programs one output-remap region so an AP or STEE window beat is
rewritten to 0x8000_0000 (the outbound mailbox responder) and allow-lists
only that remapped address in the outbound filter. A CPU-LSU access of the
programmed window returns OKAY (translated beat). A second region, left
invalid so its beat passes through untranslated, returns DECERR (forbidden
beat). The CSR-bank R/W test is not
re-run as the proof.

no_cpu, +skip_fuse_sense: remap and the outbound filter do not depend on
sense. Outbound filter skip is tied off in RTL.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_outbound_remap_seq import (
    N_REGIONS,
    OUTFILT_N_ENTRIES,
    RESP_DECERR,
    RESP_OKAY,
    SepOutboundRemap,
    SepOutboundRemapCfg,
    remap_probe_seq,
)


@pyuvm.test()
class sep_fabric_output_remap_datapath_proxy_test(sep_base_test):
    """Programmed region translates; a beat outside the allow set is DECERR."""

    async def run_scenario(self) -> None:
        cfg = SepOutboundRemapCfg(self.random_seed())
        self.logger.info("outbound remap datapath: %s", cfg.summary())
        await self.bring_up_no_cpu()

        remap = SepOutboundRemap(self)
        await remap.program(cfg)

        ok = remap_probe_seq(cfg.access_addr, expect_error=False)
        await self.start_seq(ok)
        assert ok.resp_code == RESP_OKAY, (
            f"remapped access 0x{cfg.access_addr:08x} resp={ok.resp_code}, "
            f"expected OKAY (target 0x{cfg.expect_addr:08x})"
        )
        self.logger.info(
            "CHK-REMAP-TRANSLATE PASS: %s r%d access 0x%08x -> OKAY "
            "(remapped 0x%08x, not identity)",
            cfg.bank,
            cfg.region,
            cfg.access_addr,
            cfg.expect_addr,
        )

        await remap.set_filter_enable(cfg, False)
        self.env.axi_monitor.arm_expected_decerr(1)
        closed = remap_probe_seq(cfg.access_addr, expect_error=True)
        await self.start_seq(closed)
        assert closed.resp_code == RESP_DECERR, (
            f"allow-listed remapped 0x{cfg.access_addr:08x} resp={closed.resp_code} "
            f"with the outbound entry disabled, expected DECERR "
            f"(target 0x{cfg.expect_addr:08x} just completed OKAY)"
        )
        self.logger.info(
            "CHK-FILTER-DISABLE PASS: %s r%d access 0x%08x -> DECERR "
            "with the allow entry disabled (same remapped target)",
            cfg.bank,
            cfg.region,
            cfg.access_addr,
        )
        await remap.set_filter_enable(cfg, True)

        self.env.axi_monitor.arm_expected_decerr(1)
        bad = remap_probe_seq(cfg.forbidden_addr, expect_error=True)
        await self.start_seq(bad)
        assert bad.resp_code == RESP_DECERR, (
            f"forbidden 0x{cfg.forbidden_addr:08x} resp={bad.resp_code}, "
            f"expected DECERR (passes through as 0x{cfg.forbidden_expect:08x})"
        )
        self.logger.info(
            "CHK-FILTER-DROP PASS: %s r%d access 0x%08x -> DECERR "
            "(outside the remapped allow window)",
            cfg.bank,
            cfg.forbidden_region,
            cfg.forbidden_addr,
        )
        self.env.axi_monitor.arm_expected_decerr(1)
        neighbor = remap_probe_seq(cfg.neighbor_addr, expect_error=True)
        await self.start_seq(neighbor)
        assert neighbor.resp_code == RESP_DECERR, (
            f"same-region neighbor 0x{cfg.neighbor_addr:08x} resp={neighbor.resp_code}, "
            f"expected DECERR (translates to 0x{cfg.neighbor_expect:08x}, "
            f"outside the one-beat allow at 0x{cfg.expect_addr:08x})"
        )
        self.logger.info(
            "CHK-FILTER-DROP PASS: %s r%d access 0x%08x -> DECERR "
            "(translates to 0x%08x, outside the one-beat allow at 0x%08x)",
            cfg.bank,
            cfg.region,
            cfg.neighbor_addr,
            cfg.neighbor_expect,
            cfg.expect_addr,
        )
        # Config report, not a checker. The seed picks one region and one entry,
        # and a bound on an index the same seed generated cannot fail. The
        # coverage this entry does claim is asserted above, against the DUT.
        self.logger.info(
            "output-remap config: bank=%s region=%d of %d entry=%d of %d, seed %d",
            cfg.bank,
            cfg.region,
            N_REGIONS,
            cfg.entry,
            OUTFILT_N_ENTRIES,
            cfg.seed,
        )
