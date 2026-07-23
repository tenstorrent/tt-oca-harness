# SPDX-License-Identifier: Apache-2.0
"""SMC OSS PyUVM environment configuration object."""

from __future__ import annotations

import random

from cocotb.triggers import Event
from pyuvm import uvm_object

from .smc_memory_model import SmcMemoryModel


class SmcEnvCfg(uvm_object):
    """Shared environment configuration / handshakes for the SMC OSS TB."""

    def __init__(self, name: str = "SmcEnvCfg") -> None:
        super().__init__(name)
        # Default clock periods for the three SMC clock domains exposed by
        # tb_top (clk_ref_i / clk_smc_i / clk_periph_i). ``randomize_timing``
        # may override these per run.
        self.ref_clk_period_ns = 10
        self.smc_clk_period_ns = 5
        self.periph_clk_period_ns = 10
        # Cycles to wait after cold reset deassertion before sampling.
        self.post_reset_settle_cycles = 500
        self.axi_timeout_ns = 50_000
        # Testcase-local golden memory. This is not a DUT backdoor; sequences
        # use it to track data driven through public AXI/protocol VIP paths.
        self.memory_model = SmcMemoryModel()
        # Set by the base test once clocks are running and cold reset is
        # released, so the env agents start their observations at the right
        # time.
        self.reset_done = Event("smc_reset_done")

    def randomize_timing(self, seed: int | None = None) -> None:
        """Randomize the three clock periods for timing variety.

        Uses a dedicated RNG seeded from the runner's ``RANDOM_SEED`` so
        ``run_dv.py --seed`` reproduces the chosen periods without disturbing
        global ``random`` state used elsewhere.
        """
        rng = random.Random(seed)
        self.ref_clk_period_ns = rng.choice([8, 10, 12])
        self.smc_clk_period_ns = rng.choice([4, 5, 6])
        self.periph_clk_period_ns = rng.choice([8, 10, 12])
