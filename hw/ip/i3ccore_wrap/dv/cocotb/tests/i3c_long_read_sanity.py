# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Long Read Sanity Test

Performs SETDASA + 500-byte private read (125 full dwords = 125 entries).
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

# Test parameters
READ_LENGTH = 500  # 125 full dwords (125 entries total)


class TB:
    """Minimal testbench for I3C long read test."""

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


@cocotb.test(timeout_time=5000, timeout_unit="us")
async def test_long_read_sanity(dut):
    """I3C long read test: SETDASA + 500-byte read."""
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info(f"I3C Long Read Sanity Test ({READ_LENGTH} bytes)")
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

    # Generate 500 bytes of test data (incrementing pattern) for target to transmit
    tx_data = [(i & 0xFF) for i in range(READ_LENGTH)]
    tb.log.info(
        f"Private read: {READ_LENGTH} bytes (pattern: 0x00-0x{(READ_LENGTH - 1) & 0xFF:02X})"
    )
    tb.log.info(f"  First 8 bytes: {[f'0x{b:02X}' for b in tx_data[:8]]}")
    tb.log.info(f"  Last 8 bytes:  {[f'0x{b:02X}' for b in tx_data[-8:]]}")

    # Private read (500 bytes) - interleaved, target provides tx_data, controller receives rx_data
    ok, resp, rx_data = await ctrl.private_read(tgt, tx_data)
    tb.log.info(f"  Response: 0x{resp:08X}, success={ok}")
    tb.log.info(f"  Controller received {len(rx_data)} bytes")
    assert ok, f"Private read failed with response 0x{resp:08X}"

    # Verify data
    if rx_data == tx_data:
        tb.log.info("  Data verification: PASSED")
    else:
        tb.log.error("  Data verification: FAILED")
        tb.log.error(f"  Expected {len(tx_data)} bytes, received {len(rx_data)} bytes")
        # Find first mismatch
        for i, (exp, got) in enumerate(zip(tx_data, rx_data)):
            if exp != got:
                tb.log.error(f"  First mismatch at byte {i}: expected 0x{exp:02X}, got 0x{got:02X}")
                break
        if len(rx_data) != len(tx_data):
            tb.log.error(f"  Length mismatch: expected {len(tx_data)}, got {len(rx_data)}")
        assert False, "Data mismatch"

    tb.log.info("=" * 60)
    tb.log.info(f"SUCCESS: {len(tx_data)}-byte read test passed!")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)
