# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Write/Read Sanity Test

Performs SETDASA + 4-byte private write + 4-byte private read.
Uses i3c_api.py for all I3C operations.
"""

import logging

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from env.i3c_api import I3CController, I3CHelper, I3CTarget

# Address mapping
CTRL_BASE = 0x0000
TGT_BASE = 0x1000
TARGET_STATIC_ADDR = 0x10
TARGET_DYNAMIC_ADDR = 0x10


class TB:
    """Minimal testbench for I3C sanity test."""

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


@cocotb.test(timeout_time=1000, timeout_unit="us")
async def test_write_read_sanity(dut):
    """I3C sanity test: SETDASA + 4-byte write + 4-byte read."""
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C Write/Read Sanity Test")
    tb.log.info("=" * 60)

    await Timer(500, units="ns")
    await tb.setup_axi_master()
    await tb.wait_for_reset()

    # Create API objects
    helper = I3CHelper(tb.axi_master, dut, tb.log)
    ctrl = I3CController(CTRL_BASE, helper)
    tgt = I3CTarget(TGT_BASE, helper)

    # Initialize controller and target
    tb.log.info("Initializing controller...")
    await ctrl.initialize()
    await ctrl.configure_timing_od_i3c()
    await ctrl.configure_timing_pp()

    tb.log.info("Configuring controller thresholds...")
    await ctrl.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    tb.log.info("Initializing target...")
    await tgt.initialize(TARGET_STATIC_ADDR)
    tb.log.info("Configuring target thresholds...")
    await tgt.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    # SETDASA
    tb.log.info(
        f"Sending SETDASA (static=0x{TARGET_STATIC_ADDR:02X}, "
        f"dynamic=0x{TARGET_DYNAMIC_ADDR:02X})..."
    )
    ok, resp = await ctrl.send_setdasa(TARGET_STATIC_ADDR, TARGET_DYNAMIC_ADDR)
    tb.log.info(f"  Response: 0x{resp:08X}, success={ok}")
    assert ok, f"SETDASA failed with response 0x{resp:08X}"

    # Verify target got dynamic address
    ok, dyn_addr = await tgt.wait_dynamic_addr()
    tb.log.info(f"  Target dynamic address: 0x{dyn_addr:02X}, valid={ok}")
    assert ok, "Target did not receive dynamic address"
    assert dyn_addr == TARGET_DYNAMIC_ADDR

    # Private write (4 bytes) - interleaved, returns rx_data
    write_data = [0xDE, 0xAD, 0xBE, 0xEF]
    tb.log.info(f"Private write: {[f'0x{b:02X}' for b in write_data]}")
    ok, resp, rx_data = await ctrl.private_write(write_data, tgt)
    tb.log.info(f"  Response: 0x{resp:08X}, success={ok}")
    tb.log.info(f"  Target received: {[f'0x{b:02X}' for b in rx_data]}")
    assert ok, f"Private write failed with response 0x{resp:08X}"
    assert rx_data == write_data, f"Data mismatch: {rx_data} != {write_data}"

    # Private read (4 bytes) - includes target TX prep
    read_data = [0x11, 0x22, 0x33, 0x44]
    tb.log.info(f"Private read: {[f'0x{b:02X}' for b in read_data]}")
    ok, resp, ctrl_rx_data = await ctrl.private_read(tgt, read_data)
    tb.log.info(f"  Response: 0x{resp:08X}, success={ok}")
    tb.log.info(f"  Controller received: {[f'0x{b:02X}' for b in ctrl_rx_data]}")
    assert ok, f"Private read failed with response 0x{resp:08X}"
    assert ctrl_rx_data == read_data, f"Data mismatch: {ctrl_rx_data} != {read_data}"

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: All tests passed!")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)
