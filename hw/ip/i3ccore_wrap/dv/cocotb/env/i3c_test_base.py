# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Block-level Test Base / Shared Helpers

Provides a reusable testbench wrapper (TB), AXI-Lite master setup, and
controller/target environment construction so individual cocotb test modules
stay small and consistent. All I3C operations go through i3c_api.py.

Instance map (tb_i3ccore.sv):
  - Instance 0 (CTRL_BASE = 0x0000): Controller
  - Instance 1 (TGT_BASE  = 0x1000): Target
"""

import logging

from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster

from .i3c_api import I3CController, I3CHelper, I3CTarget

# Address mapping (matches tb_i3ccore.sv INSTANCE_SPACING decode)
CTRL_BASE = 0x0000
TGT_BASE = 0x1000

DEFAULT_STATIC_ADDR = 0x10
DEFAULT_DYNAMIC_ADDR = 0x10


class TB:
    """Minimal testbench wrapper for the I3C block-level cocotb tests."""

    def __init__(self, dut):
        self.dut = dut
        self.log = logging.getLogger("cocotb.tb")
        self.log.setLevel(logging.DEBUG)
        self.axi_master = None

    async def setup_axi_master(self):
        await Timer(100, units="ns")
        bus = AxiLiteBus.from_prefix(self.dut, "axi")
        self.axi_master = AxiLiteMaster(bus, self.dut.clk, self.dut.rst_n, reset_active_level=False)
        self.axi_master.write_if.log.setLevel(logging.ERROR)
        self.axi_master.read_if.log.setLevel(logging.ERROR)
        self.log.info("AXI-Lite master connected")

    async def wait_for_reset(self):
        while self.dut.rst_n.value == 0:
            await RisingEdge(self.dut.clk)
        await ClockCycles(self.dut.clk, 5)
        self.log.info("Reset released")


async def make_env(dut):
    """Bring the DUT out of reset and return (tb, helper, ctrl, tgt)."""
    tb = TB(dut)
    await Timer(500, units="ns")
    await tb.setup_axi_master()
    await tb.wait_for_reset()

    helper = I3CHelper(tb.axi_master, dut, tb.log)
    ctrl = I3CController(CTRL_BASE, helper)
    tgt = I3CTarget(TGT_BASE, helper)
    return tb, helper, ctrl, tgt


async def init_controller(ctrl, tx_buf=1, rx_buf=1):
    """Standard controller bring-up: init + OD/PP timing + thresholds."""
    await ctrl.initialize()
    await ctrl.configure_timing_od_i3c()
    await ctrl.configure_timing_pp()
    await ctrl.configure_thresholds(tx_buf=tx_buf, tx_start=0, rx_buf=rx_buf, rx_start=0)


async def init_target(tgt, static_addr=DEFAULT_STATIC_ADDR, tx_buf=1, rx_buf=1):
    """Standard target bring-up: init(static) + OD timing + thresholds."""
    await tgt.initialize(static_addr)
    await tgt.configure_timing_od_i3c()
    await tgt.configure_thresholds(tx_buf=tx_buf, tx_start=0, rx_buf=rx_buf, rx_start=0)


async def bring_up_and_assign(
    ctrl, tgt, static_addr=DEFAULT_STATIC_ADDR, dynamic_addr=DEFAULT_DYNAMIC_ADDR
):
    """
    Full bring-up: init controller + target, then SETDASA and confirm the
    target received the dynamic address. Returns the SETDASA response word.
    """
    await init_controller(ctrl)
    await init_target(tgt, static_addr)

    ok, resp = await ctrl.send_setdasa(static_addr, dynamic_addr)
    assert ok, f"SETDASA failed with response 0x{resp:08X}"

    ok, dyn = await tgt.wait_dynamic_addr()
    assert ok, "Target did not receive dynamic address"
    assert dyn == dynamic_addr, f"Target addr mismatch: 0x{dyn:02X} != 0x{dynamic_addr:02X}"
    return resp
