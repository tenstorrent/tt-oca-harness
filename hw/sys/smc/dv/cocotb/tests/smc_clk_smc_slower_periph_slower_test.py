# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN register traffic with the SMC clock slower than the reference and the peripheral clock slower than it.

`clk_rst.adoc` constrains `clk_periph_i` to 100 MHz or faster and states no
other relation between the three input clocks, so this is a legal
configuration that the bench's default periods (ref / smc / periph 10 / 1.25 /
5 ns) never produce. The leaf pins ref / smc / periph to 8 / 12 / 10 ns,
confirms the relation by measuring each period and counting edges across one
ratio-collector window, and drives register traffic into both sides of the
peripheral clock-domain crossing.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_clk_smc_slower_periph_slower_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_clk_ratio_test_seq import (
    EXPECTED_ACCESSES,
    EXPECTED_VALUE_CHECKS,
    smc_clk_ratio_test_seq,
)
from smc_base_test import smc_base_test

REF_CLK_PERIOD_NS = 8
SMC_CLK_PERIOD_NS = 12
PERIPH_CLK_PERIOD_NS = 10


@pyuvm.test()
class smc_clk_smc_slower_periph_slower_test(smc_base_test):
    """Register traffic across the clock domains at ref / smc / periph 8 / 12 / 10 ns."""

    required_evidence = ("CHK-CLK-RATIO-CSR", "CHK-CLK-RATIO-PERIODS")
    min_evidence = 2

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
        seq = smc_clk_ratio_test_seq("clk_ratio_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        value_compares = self.env.scoreboard.sys_axi_value_checks_seen
        assert value_compares >= EXPECTED_VALUE_CHECKS, (
            f"scoreboard booked only {value_compares} SEP_IN AXI value compares, expected at "
            f"least {EXPECTED_VALUE_CHECKS}"
        )
        assert seq.accesses == EXPECTED_ACCESSES, (
            f"{seq.accesses} SEP_IN accesses issued, expected {EXPECTED_ACCESSES}"
        )
