# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVS_CFG_0 round trip through the AVSBus CDC bridge at three peripheral clock periods.

Spec: clk_rst.adoc (Peripheral Timing Requirements), avsbus_controller memmap.adoc (AVS_CFG_0).

The ``+smc_cell`` run argument selects the peripheral period (periph10, periph5 or periph3); the
reference clock is 10 ns and the SMC clock 1.25 ns in every cell.
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_periph_floor_roundtrip_test_seq import smc_periph_floor_roundtrip_test_seq
from smc_base_test import smc_base_test

PERIPH_PERIODS_NS = {"periph10": 10, "periph5": 5, "periph3": 3}
REF_CLK_PERIOD_NS = 10
SMC_CLK_PERIOD_NS = 1.25


@pyuvm.test()
class smc_periph_floor_roundtrip_test(smc_base_test):
    """AVS_CFG_0 write, read-back and restore at the run's peripheral clock period."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-PERIPH-FLOOR-ROUNDTRIP",
        "CHK-TIMEOUT-PATHS",
    )
    CELL = "periph5"
    min_evidence = 3

    auto_protocol_vip = False

    def build_phase(self) -> None:
        super().build_phase()
        cell = cocotb.plusargs.get("smc_cell", self.CELL)
        assert cell in PERIPH_PERIODS_NS, (
            f"+smc_cell={cell} is not one of {sorted(PERIPH_PERIODS_NS)}"
        )
        self.cell = cell
        self.cfg.ref_clk_period_ns = REF_CLK_PERIOD_NS
        self.cfg.smc_clk_period_ns = SMC_CLK_PERIOD_NS
        self.cfg.periph_clk_period_ns = PERIPH_PERIODS_NS[cell]
        self.logger.info(
            "SMC timing pinned by the leaf: cell=%s ref=%sns smc=%sns periph=%sns",
            cell,
            REF_CLK_PERIOD_NS,
            SMC_CLK_PERIOD_NS,
            self.cfg.periph_clk_period_ns,
        )

    async def run_scenario(self) -> None:
        seq = smc_periph_floor_roundtrip_test_seq(
            "periph_floor_roundtrip_seq",
            cell=self.cell,
            periods_ns=(REF_CLK_PERIOD_NS, SMC_CLK_PERIOD_NS, PERIPH_PERIODS_NS[self.cell]),
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses == 5, f"{seq.accesses} SEP_IN accesses issued, expected 5"
