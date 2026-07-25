# SPDX-License-Identifier: Apache-2.0
"""SEP UVM environment configuration / cross-component handshakes."""

from __future__ import annotations

import random

from cocotb.triggers import Event
from pyuvm import uvm_object


class SepEnvCfg(uvm_object):
    """Shared config + handshakes for the SEP OSS PyUVM testbench."""

    def __init__(self, name: str = "SepEnvCfg") -> None:
        super().__init__(name)
        # Bring-up clock periods (ns) for the clocks tb_top exposes.
        self.sys_clk_period_ns = 5
        self.wdt_clk_period_ns = 5000
        self.entropy_clk_period_ns = 3
        # Per-access AXI timeout (ns) before the driver fails a wedged LSU path.
        self.axi_timeout_ns = 50_000
        # Set by the test once clocks run and reset releases, so the AXI driver
        # starts its cocotbext-axi master at the right time.
        self.reset_done = Event("sep_reset_done")

    def randomize_timing(self, seed: int | None = None) -> None:
        """Randomize the system-clock period for timing variety (run_dv --seed)."""
        rng = random.Random(seed)
        self.sys_clk_period_ns = rng.randint(4, 20)
