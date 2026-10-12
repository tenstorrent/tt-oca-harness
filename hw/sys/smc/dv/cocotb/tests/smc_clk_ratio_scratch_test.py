# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SCRATCH[0..7] traffic at ref / smc / periph 10 / 12 / 6 ns.

Contract SMC_CLOCK_RATIO_005, anchor smc_clk_ratio_scratch_test.
Allocated scenarios: RATIO-SCRATCH-XFER.S1, RATIO-SCRATCH-XFER.S2, RATIO-SCRATCH-XFER.S3.
Spec sources: hw/sys/smc/regs/blocks/scratch/scratch.rdl, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_clk_ratio_scratch_test_seq import smc_clk_ratio_scratch_test_seq
from smc_base_test import smc_base_test

REF_CLK_PERIOD_NS = 10
SMC_CLK_PERIOD_NS = 12
PERIPH_CLK_PERIOD_NS = 6
REQUIRED = (
    "CHK-SCRATCH-RESET-READ",
    "CHK-SCRATCH-WRITE-READ",
    "CHK-SCRATCH-NO-ALIAS",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_clk_ratio_scratch_test(smc_base_test):
    """Scratch reset read, round trip, eight-way burst and restore at 10 / 12 / 6 ns."""

    required_evidence = REQUIRED
    min_evidence = 5

    auto_protocol_vip = False

    def build_phase(self) -> None:
        super().build_phase()
        self.cfg.ref_clk_period_ns = REF_CLK_PERIOD_NS
        self.cfg.smc_clk_period_ns = SMC_CLK_PERIOD_NS
        self.cfg.periph_clk_period_ns = PERIPH_CLK_PERIOD_NS
        self.logger.info(
            "SMC timing pinned by the leaf: ref=%sns smc=%sns periph=%sns",
            REF_CLK_PERIOD_NS,
            SMC_CLK_PERIOD_NS,
            PERIPH_CLK_PERIOD_NS,
        )

    async def run_scenario(self) -> None:
        seq = smc_clk_ratio_scratch_test_seq("clk_ratio_scratch_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n != "CHK-NONVAC" and n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
