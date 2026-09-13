# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Configuration and deterministic timing choices for the SMU OSS environment."""

from __future__ import annotations

import random

from cocotb.triggers import Event
from ocah_axi_vip import OcahAxiConfig, OcahAxiProtocol, OcahAxiSlaveSequence
from pyuvm import uvm_object


class SmuEnvCfg(uvm_object):
    """Shared clock/reset configuration for SMU wrapper tests."""

    def __init__(self, name: str = "SmuEnvCfg") -> None:
        super().__init__(name)
        self.ref_clk_period_ns = 10
        self.smu_clk_period_ns = 10
        self.periph_clk_period_ns = 20
        self.entropy_clk_period_ns = 3
        self.sep_wdt_clk_period_ns = 100
        self.jtag_period_ns = 40
        self.idle_tck = 2
        self.post_reset_settle_cycles = 500
        self.powergood_delay_cycles = 8
        self.reset_hold_cycles = 12
        self.post_reset_cycles = 24
        self.reset_done = Event("smu_reset_done")
        # Outbound SMN AXI4 egress: the crossbar's ext_out geometry
        # (smu_axi_xbar_pkg axi_out_*), the responder's sparse memory span, and
        # the slave sequence smu_base_test.bring_up binds to u_axi_out_if
        # (backdoor memory access, one-shot faults).
        self.axi_out_geometry = OcahAxiConfig(
            protocol=OcahAxiProtocol.AXI4,
            addr_width=56,
            data_width=64,
            id_width=10,
            user_width=12,
        )
        self.axi_out_mem_size = 1 << 56
        self.axi_out_mem: OcahAxiSlaveSequence | None = None

    def randomize_timing(self, seed: int) -> None:
        """Choose reproducible clock ratios and reset timing."""
        rng = random.Random(seed)
        self.smu_clk_period_ns = rng.choice((8, 10, 12))
        # clk_ref_i carries telemetry; a period equal to clk_smu_i leaves the two
        # domains indistinguishable at the boundary.
        self.ref_clk_period_ns = rng.choice(
            tuple(p for p in (10, 12, 16) if p != self.smu_clk_period_ns)
        )
        self.periph_clk_period_ns = rng.choice((16, 20, 24))
        self.sep_wdt_clk_period_ns = rng.choice((80, 100, 120))
        self.powergood_delay_cycles = rng.randint(6, 10)
        self.reset_hold_cycles = rng.randint(10, 16)
        self.post_reset_cycles = rng.randint(20, 32)
        # Same draws as the bare-smu SmuEnvCfg: sequences shared with that
        # catalog read these off cfg and raise AttributeError without them.
        self.jtag_period_ns = rng.choice((32, 40, 48))
        self.idle_tck = rng.randint(2, 4)
        self.post_reset_settle_cycles = rng.randint(500, 700)
