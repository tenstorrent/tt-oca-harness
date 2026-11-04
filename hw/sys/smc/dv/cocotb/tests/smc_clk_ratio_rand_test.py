# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_IN register traffic under a seed-drawn ref / smc / periph clock period triple.

Spec sources: hw/sys/smc/doc/clk_rst.adoc (Clock Architecture, Peripheral Timing
Requirements).
"""

from __future__ import annotations

import random

import pyuvm
from seq_lib.smc_clk_ratio_rand_test_seq import (
    draw_periods_ps,
    drawn_text,
    smc_clk_ratio_rand_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_clk_ratio_rand_test(smc_base_test):
    """Drawn clock periods pinned before bring-up; register traffic completes under them."""

    required_evidence = (
        "CHK-CKR-COPATTERN",
        "CHK-CKR-DRAW-LEGAL",
        "CHK-CKR-PERIODS",
        "CHK-CKR-RESET-WORDS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    def build_phase(self) -> None:
        super().build_phase()
        seed = self.random_seed()
        self.drawn_ps = draw_periods_ps(random.Random(seed))
        self.logger.info("RAND-SEED: %d; RAND-DRAW: %s", seed, drawn_text(self.drawn_ps))
        self.cfg.ref_clk_period_ns = self.drawn_ps["ref"] / 1000
        self.cfg.smc_clk_period_ns = self.drawn_ps["smc"] / 1000
        self.cfg.periph_clk_period_ns = self.drawn_ps["periph"] / 1000
        self.logger.info(
            "SMC timing pinned by the leaf: ref=%sns smc=%sns periph=%sns",
            self.cfg.ref_clk_period_ns,
            self.cfg.smc_clk_period_ns,
            self.cfg.periph_clk_period_ns,
        )

    async def run_scenario(self) -> None:
        seq = smc_clk_ratio_rand_test_seq("clk_ratio_rand_seq", periods_ps=self.drawn_ps)
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.log_timeout_paths()
        seq.nonvac_fence()
