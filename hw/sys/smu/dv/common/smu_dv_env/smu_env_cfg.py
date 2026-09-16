# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMU OSS environment configuration."""

from __future__ import annotations

import random

from cocotb.triggers import Event
from ocah_axi_vip import OcahAxiConfig, OcahAxiProtocol, OcahAxiSlaveSequence


class SmuEnvCfg:
    def __init__(self, name: str = "cfg") -> None:
        self.name = name
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
        """Choose reproducible clock / JTAG timing from RANDOM_SEED."""
        rng = random.Random(seed)
        self.smu_clk_period_ns = rng.choice((8, 10, 12))
        self.ref_clk_period_ns = rng.choice((8, 10, 12, 16))
        self.periph_clk_period_ns = rng.choice((8, 10, 12, 16))
        self.jtag_period_ns = rng.choice((32, 40, 48))
        self.idle_tck = rng.randint(2, 4)
        # Keep settle above cold-reset extender (255) + deglitch margin.
        self.post_reset_settle_cycles = rng.randint(500, 700)
