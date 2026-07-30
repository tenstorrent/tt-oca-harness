# SPDX-License-Identifier: Apache-2.0
"""SMU OSS environment configuration."""

from __future__ import annotations

import cocotb
from cocotb.triggers import Event


class SmuEnvCfg:
    def __init__(self, name: str = "cfg") -> None:
        self.name = name
        self.smu_clk_period_ns = 10
        self.ref_clk_period_ns = 10
        self.periph_clk_period_ns = 10
        self.jtag_period_ns = 40
        self.idle_tck = 2
        # Real smc_reset_ctrl: 32-cycle cold deglitch + 255-cycle extender on clk_ref.
        # Match SMC OSS settle budget so rst_cold_stable_* / rst_primary_* release.
        self.post_reset_settle_cycles = 500
        self.reset_done = Event()

    def randomize_timing(self, seed: int) -> None:
        # Deterministic defaults for Phase-1; seed reserved for later jitter.
        _ = seed
