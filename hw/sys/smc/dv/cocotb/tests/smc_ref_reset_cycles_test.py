# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Cold-reset conditioning counted in clk_ref_i cycles.

Spec: clk_rst.adoc (Power-Good and Cold Reset), port_table.adoc (SMC Port Declaration).

The ``+smc_cell`` run argument selects the reference period (ref10 or ref4); the SMC clock is
1.25 ns and the peripheral clock 5 ns in both cells.
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smc_ref_reset_cycles_test_seq import (
    RELEASE_MIN_CYCLES,
    smc_ref_reset_cycles_test_seq,
)
from smc_base_test import smc_base_test

REF_PERIODS_NS = {"ref10": 10, "ref4": 4}
SMC_CLK_PERIOD_NS = 1.25
PERIPH_CLK_PERIOD_NS = 5


@pyuvm.test()
class smc_ref_reset_cycles_test(smc_base_test):
    """Release hold and de-glitch of rst_cold_ni measured in clk_ref_i cycles."""

    required_evidence = (
        "CHK-REF-RESET-RELEASE-CYCLES",
        "CHK-REF-RESET-DEGLITCH",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 4

    auto_protocol_vip = False

    def build_phase(self) -> None:
        super().build_phase()
        cell = cocotb.plusargs.get("smc_cell", "ref10")
        assert cell in REF_PERIODS_NS, f"+smc_cell={cell} is not one of {sorted(REF_PERIODS_NS)}"
        self.cfg.ref_clk_period_ns = REF_PERIODS_NS[cell]
        self.cfg.smc_clk_period_ns = SMC_CLK_PERIOD_NS
        self.cfg.periph_clk_period_ns = PERIPH_CLK_PERIOD_NS
        self.logger.info(
            "SMC timing pinned by the leaf: cell=%s ref=%sns smc=%sns periph=%sns",
            cell,
            self.cfg.ref_clk_period_ns,
            SMC_CLK_PERIOD_NS,
            PERIPH_CLK_PERIOD_NS,
        )

    async def run_scenario(self) -> None:
        seq = smc_ref_reset_cycles_test_seq("ref_reset_cycles_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
        assert seq.n_rel is not None and seq.n_rel >= RELEASE_MIN_CYCLES, seq.n_rel
        assert seq.n_assert is not None and seq.n_assert >= 1, seq.n_assert
