# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP UVM environment configuration / cross-component handshakes."""

from __future__ import annotations

from cocotb.triggers import Event
from ocah_axi_vip import OcahAxiSlaveSequence
from pyuvm import uvm_object


class SepEnvCfg(uvm_object):
    """Shared config + handshakes for the SEP OSS PyUVM testbench."""

    def __init__(self, name: str = "SepEnvCfg") -> None:
        super().__init__(name)
        # Bring-up clock periods (ns). clk_i is the 800 MHz silicon target
        # (1.25 ns). clk_ref_i is the 100 MHz platform reference, slower than
        # clk_i so the REFERENCE_COUNTER CDC sees real crossings.
        self.sys_clk_period_ns = 1.25
        self.wdt_clk_period_ns = 5000
        self.entropy_clk_period_ns = 3
        self.ref_clk_period_ns = 10
        # Per-access AXI timeout (ns) before the driver fails a wedged LSU path.
        self.axi_timeout_ns = 50_000
        # Set by the test once clocks run and reset releases, so the AXI driver
        # starts its cocotbext-axi master at the right time.
        self.reset_done = Event("sep_reset_done")
        # Slave sequence of the SMC responder sep_base_test.start_clocks binds
        # to u_smc_axi_if in rom_boot builds: backdoor memory access and
        # one-shot faults. None on targets without that interface.
        self.smc_mem: OcahAxiSlaveSequence | None = None
