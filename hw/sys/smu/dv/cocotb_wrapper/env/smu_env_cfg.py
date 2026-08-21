# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Configuration and deterministic timing choices for the SMU OSS environment."""

from __future__ import annotations

import random

from cocotb.triggers import Event
from pyuvm import uvm_object


class SmuEnvCfg(uvm_object):
    """Shared clock/reset configuration for SMU wrapper tests."""

    def __init__(self, name: str = "SmuEnvCfg") -> None:
        super().__init__(name)
        self.ref_clk_period_ns = 10
        self.smu_clk_period_ns = 10
        self.periph_clk_period_ns = 20
        self.sep_wdt_clk_period_ns = 100
        self.powergood_delay_cycles = 8
        self.reset_hold_cycles = 12
        self.post_reset_cycles = 24
        self.reset_done = Event("smu_reset_done")

    def randomize_timing(self, seed: int) -> None:
        """Choose reproducible clock ratios and reset timing."""
        rng = random.Random(seed)
        self.smu_clk_period_ns = rng.choice((8, 10, 12))
        self.ref_clk_period_ns = rng.choice((10, 12, 16))
        self.periph_clk_period_ns = rng.choice((16, 20, 24))
        self.sep_wdt_clk_period_ns = rng.choice((80, 100, 120))
        self.powergood_delay_cycles = rng.randint(6, 10)
        self.reset_hold_cycles = rng.randint(10, 16)
        self.post_reset_cycles = rng.randint(20, 32)
