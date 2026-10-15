# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register round trips on the SMC crossbar and the AVSBus window per clock cell.

Spec: clk_rst.adoc, smc_base_config.rdl, avsbus_controller.rdl.

The ``+smc_cell`` run argument selects the ref / smc / periph period triple in ns: default
(10 / 1.25 / 5), smc_slower (10 / 12 / 8), smc_equal (10 / 10 / 10), periph_slower
(8 / 1.25 / 10), periph3 (10 / 1.25 / 3), ref8 (8 / 1.25 / 5) or slowest_periph
(8 / 12 / 10).
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_clk_relation_regxbar_test_seq import smc_clk_relation_regxbar_test_seq
from smc_base_test import smc_base_test

CELLS = {
    "default": ((10, 1.25, 5), "CHK-REGXBAR-RESET-RT"),
    "smc_slower": ((10, 12, 8), None),
    "smc_equal": ((10, 10, 10), None),
    "periph_slower": ((8, 1.25, 10), None),
    "periph3": ((10, 1.25, 3), "CHK-REGXBAR-PERIODS"),
    "ref8": ((8, 1.25, 5), "CHK-REGXBAR-PERIODS"),
    "slowest_periph": ((8, 12, 10), "CHK-CLK-RELATION-BACKPRESSURE"),
}


@pyuvm.test()
class smc_clk_relation_regxbar_test(smc_base_test):
    """HANG_DET threshold and AVS_CFG_0 round trips at one clock cell."""

    # Every cell's checkers; build_phase narrows the tuple to the selected cell's.
    required_evidence = (
        "CHK-CLK-RELATION-BACKPRESSURE",
        "CHK-CLK-RELATION-ROUNDTRIP",
        "CHK-NONVAC",
        "CHK-REGXBAR-PERIODS",
        "CHK-REGXBAR-RESET-RT",
        "CHK-TIMEOUT-PATHS",
    )
    CELL = "default"
    min_evidence = 3

    auto_protocol_vip = False

    def build_phase(self) -> None:
        super().build_phase()
        cell = cocotb.plusargs.get("smc_cell", self.CELL)
        assert cell in CELLS, f"+smc_cell={cell} is not one of {sorted(CELLS)}"
        self.cell = cell
        periods, extra = CELLS[cell]
        self.required_evidence = (
            "CHK-CLK-RELATION-ROUNDTRIP",
            "CHK-NONVAC",
            "CHK-TIMEOUT-PATHS",
        ) + ((extra,) if extra else ())
        self.min_evidence = len(self.required_evidence)
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
        seq = smc_clk_relation_regxbar_test_seq(
            "clk_relation_regxbar_seq", cell=self.cell, periods_ns=self.periods_ns
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
