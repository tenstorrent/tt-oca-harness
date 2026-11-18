# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVS_CFG_0 round trip through the AVSBus CDC bridge at three peripheral clock periods.

Spec: clk_rst.adoc (Peripheral Timing Requirements), avsbus_controller memmap.adoc (AVS_CFG_0).

The cell is the peripheral period (periph10, periph5 or periph3); the reference clock is 10 ns
and the SMC clock 1.25 ns in every cell. The ``+smc_cell`` run argument or a subclass ``CELL``
pins it; otherwise build_phase draws it uniformly from the seed.
"""

from __future__ import annotations

import random

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
    # None draws the cell from the seed; a variant subclass pins one.
    CELL: str | None = None
    min_evidence = 3

    auto_protocol_vip = False

    def build_phase(self) -> None:
        super().build_phase()
        seed = self.random_seed()
        pinned = cocotb.plusargs.get("smc_cell", self.CELL)
        cell = (
            pinned if pinned is not None else random.Random(seed).choice(sorted(PERIPH_PERIODS_NS))
        )
        assert cell in PERIPH_PERIODS_NS, f"cell {cell} is not one of {sorted(PERIPH_PERIODS_NS)}"
        self.cell = cell
        self.cfg.ref_clk_period_ns = REF_CLK_PERIOD_NS
        self.cfg.smc_clk_period_ns = SMC_CLK_PERIOD_NS
        self.cfg.periph_clk_period_ns = PERIPH_PERIODS_NS[cell]
        if pinned is None:
            source = "drawn"
        elif "smc_cell" in cocotb.plusargs:
            source = "pinned by +smc_cell"
        else:
            source = "pinned by the class"
        self.logger.info("RAND-SEED: %d; RAND-DRAW: cell=%s (%s)", seed, cell, source)
        self.logger.info(
            "SMC timing set by the leaf: cell=%s (%s) ref=%sns smc=%sns periph=%sns",
            cell,
            source,
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
