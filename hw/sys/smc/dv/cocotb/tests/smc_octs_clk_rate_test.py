# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS primary counter rate against the three input clock periods.

Contract SMC_CLOCK_SRC_001, anchor smc_octs_clk_rate_test.
Scenarios: CSRC-OCTS-CLK.S1, CSRC-OCTS-CLK.S2, CSRC-OCTS-CLK.S3, CSRC-OCTS-CLK.S4.
Spec: clk_rst.adoc (Timer and Debug Timebases), system_timer_octs architecture.adoc.

The ``+smc_cell`` run argument selects the ref / smc / periph period triple in ns: default
(10 / 1.25 / 5), smc_slower (10 / 12 / 5), smc_equal (10 / 10 / 5), smc_fast (10 / 1 / 5),
ref8 (8 / 1.25 / 5) or periph3 (10 / 1.25 / 3).
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_octs_clk_rate_test_seq import smc_octs_clk_rate_test_seq
from smc_base_test import smc_base_test

CELLS = {
    "default": ((10, 1.25, 5), "CHK-OCTS-RATE-DEFAULT"),
    "smc_slower": ((10, 12, 5), "CHK-OCTS-RATE-SMC-PERIOD"),
    "smc_equal": ((10, 10, 5), "CHK-OCTS-RATE-SMC-PERIOD"),
    "smc_fast": ((10, 1, 5), "CHK-OCTS-RATE-SMC-PERIOD"),
    "ref8": ((8, 1.25, 5), "CHK-OCTS-RATE-OTHER-CLOCKS"),
    "periph3": ((10, 1.25, 3), "CHK-OCTS-RATE-OTHER-CLOCKS"),
}


@pyuvm.test()
class smc_octs_clk_rate_test(smc_base_test):
    """OCTS TIMER_COUNT delta against bench edge counters on the three input clocks."""

    min_evidence = 4

    auto_protocol_vip = False

    def build_phase(self) -> None:
        super().build_phase()
        cell = cocotb.plusargs.get("smc_cell", "default")
        assert cell in CELLS, f"+smc_cell={cell} is not one of {sorted(CELLS)}"
        self.cell = cell
        periods, rate_id = CELLS[cell]
        self.rate_id = rate_id
        self.required_evidence = (
            rate_id,
            "CHK-OCTS-START-RELOAD",
            "CHK-NONVAC",
            "CHK-TIMEOUT-PATHS",
        )
        (
            self.cfg.ref_clk_period_ns,
            self.cfg.smc_clk_period_ns,
            self.cfg.periph_clk_period_ns,
        ) = periods
        self.periods_ns = periods
        self.logger.info(
            "SMC timing pinned by the leaf: cell=%s ref=%sns smc=%sns periph=%sns",
            cell,
            *periods,
        )

    async def run_scenario(self) -> None:
        seq = smc_octs_clk_rate_test_seq(
            "octs_clk_rate_seq",
            cell=self.cell,
            rate_id=self.rate_id,
            periods_ns=self.periods_ns,
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
