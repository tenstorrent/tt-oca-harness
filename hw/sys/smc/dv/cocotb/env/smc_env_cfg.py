# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM environment configuration object."""

from __future__ import annotations

import random

from cocotb.triggers import Event
from ocah_axi_vip import OcahAxiConfig, OcahAxiProtocol, OcahAxiSlaveSequence
from pyuvm import uvm_object

from .smc_memory_model import SmcMemoryModel

# SYS_OUT AXI4 egress geometry (smc_pkg smc_sys_out_56_64_8_12_axi_*) and the
# responder's sparse memory span; the dual bench binds one responder per
# instance from the same values.
SYS_OUT_AXI_GEOMETRY = OcahAxiConfig(
    protocol=OcahAxiProtocol.AXI4,
    addr_width=56,
    data_width=64,
    id_width=8,
    user_width=12,
)
SYS_OUT_MEM_SIZE = 1 << 56


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
        # Slave sequence of the SYS_OUT responder smc_base_test.bring_up binds to
        # u_output_axi_if: backdoor memory access and one-shot faults.
        self.sys_out_mem: OcahAxiSlaveSequence | None = None
        # Set by the base test once clocks are running and cold reset is
        # released, so the env agents start their observations at the right
        # time.
        self.reset_done = Event("smc_reset_done")

    def randomize_timing(self, seed: int | None = None) -> None:
        """Randomize the three clock periods for timing variety.

        The peripheral clock is drawn only from periods of 10 ns or less:
        ``clk_rst.adoc`` (The Peripheral Clock Domain) sets a 100 MHz minimum
        for ``clk_periph_i``. The other two clocks have no specified bound.

        Uses a dedicated RNG seeded from the runner's ``RANDOM_SEED`` so
        ``run_dv.py --seed`` reproduces the chosen periods without disturbing
        global ``random`` state used elsewhere.
        """
        rng = random.Random(seed)
        self.ref_clk_period_ns = rng.choice([8, 10, 12])
        self.smc_clk_period_ns = rng.choice([4, 5, 6])
        self.periph_clk_period_ns = rng.choice([8, 10])
