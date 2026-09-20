# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP UVM environment configuration / cross-component handshakes."""

from __future__ import annotations

from cocotb.triggers import Event
from ocah_axi_vip import OcahAxiSlaveSequence
from pyuvm import uvm_object

from env.sep_seeded_rng import SepSeededRng


class SepEnvCfg(uvm_object):
    """Shared config + handshakes for the SEP OSS PyUVM testbench."""

    def __init__(self, name: str = "SepEnvCfg") -> None:
        super().__init__(name)
        # Bring-up clock periods (ns) for the clocks tb_top exposes.
        self.sys_clk_period_ns = 5
        self.wdt_clk_period_ns = 5000
        self.entropy_clk_period_ns = 3
        # Reference clock for the SEP_CPU_CTRL REFERENCE_COUNTER. Slower than
        # the system clock so the counter's CDC crossing is a real one in both
        # directions; kept off the seeded randomization because a read-count
        # delta is compared against an elapsed-time bound.
        self.ref_clk_period_ns = 40
        # Per-access AXI timeout (ns) before the driver fails a wedged LSU path.
        self.axi_timeout_ns = 50_000
        # Set by the test once clocks run and reset releases, so the AXI driver
        # starts its cocotbext-axi master at the right time.
        self.reset_done = Event("sep_reset_done")
        # Slave sequence of the SMC responder sep_base_test.start_clocks binds
        # to u_smc_axi_if in rom_boot builds: backdoor memory access and
        # one-shot faults. None on targets without that interface.
        self.smc_mem: OcahAxiSlaveSequence | None = None

    def randomize_timing(self, seed: int) -> None:
        """Randomize the system-clock period for timing variety (run_dv --seed)."""
        rng = SepSeededRng(seed)
        self.sys_clk_period_ns = rng.randrange(4, 21)
