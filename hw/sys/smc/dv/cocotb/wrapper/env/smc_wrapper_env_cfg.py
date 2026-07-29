# SPDX-License-Identifier: Apache-2.0
"""Configuration and deterministic timing for the smc_wrapper pad-level env.

Lives under cocotb/wrapper/ (not a top-level cocotb_wrapper tree). Distinct from
bare-SMC ``env.smc_env_cfg.SmcEnvCfg`` — different fields and bring-up timing.
"""

from __future__ import annotations

import random

from cocotb.triggers import Event
from pyuvm import uvm_object


class SmcWrapperEnvCfg(uvm_object):
    """Shared clock/reset configuration for SMC wrapper tests."""

    def __init__(self, name: str = "SmcWrapperEnvCfg") -> None:
        super().__init__(name)
        self.ref_clk_period_ns = 10
        self.smc_clk_period_ns = 10
        self.periph_clk_period_ns = 20
        self.powergood_delay_cycles = 8
        self.reset_hold_cycles = 12
        self.post_reset_cycles = 24
        self.reset_done = Event("smc_wrapper_reset_done")

    def randomize_timing(self, seed: int) -> None:
        """Choose reproducible clock ratios and reset timing."""
        rng = random.Random(seed)
        self.smc_clk_period_ns = rng.choice((8, 10, 12))
        self.ref_clk_period_ns = rng.choice((10, 12, 16))
        self.periph_clk_period_ns = rng.choice((16, 20, 24))
        self.powergood_delay_cycles = rng.randint(6, 10)
        self.reset_hold_cycles = rng.randint(10, 16)
        self.post_reset_cycles = rng.randint(20, 32)
