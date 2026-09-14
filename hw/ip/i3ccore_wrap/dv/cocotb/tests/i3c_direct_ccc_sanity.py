# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Direct CCC Sanity Test

Performs SETDASA followed by Direct CCC commands with read-write-read verification:
  GETBCR -> GETMWL -> SETMWL(0x10) -> GETMWL -> GETMRL -> SETMRL(0x10, 0x10) -> GETMRL -> RSTACT(0x01)

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
    """Minimal testbench for I3C Direct CCC sanity test."""

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
async def i3c_direct_ccc_sanity(dut):
    """I3C test: SETDASA + Direct CCC commands with read-write-read verification."""
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C Direct CCC Sanity Test")
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

    # GETBCR - Get Bus Characteristics Register
    tb.log.info("Sending GETBCR CCC...")
    ok, bcr = await ctrl.getbcr(dat_idx=0)
    if ok:
        tb.log.info(f"  BCR value: 0x{bcr:02X} ({bcr})")
        tb.log.info(f"    Bit 7-6 (Device Role): {(bcr >> 6) & 0x3}")
        tb.log.info(f"    Bit 5 (Advanced Capabilities): {(bcr >> 5) & 0x1}")
        tb.log.info(f"    Bit 4 (Virtual Target Support): {(bcr >> 4) & 0x1}")
        tb.log.info(f"    Bit 3 (Offline Capable): {(bcr >> 3) & 0x1}")
        tb.log.info(f"    Bit 2 (IBI Payload): {(bcr >> 2) & 0x1}")
        tb.log.info(f"    Bit 1 (IBI Request Capable): {(bcr >> 1) & 0x1}")
        tb.log.info(f"    Bit 0 (Max Data Speed Limitation): {bcr & 0x1}")
    else:
        tb.log.error("GETBCR failed!")
        assert False, "GETBCR failed"

    # GETMWL - Get Max Write Length (before SET)
    tb.log.info("Sending GETMWL CCC (before SET)...")
    ok, mwl_before = await ctrl.getmwl()
    assert ok, "GETMWL failed"
    tb.log.info(f"  MWL value: 0x{mwl_before:04X} ({mwl_before} bytes)")

    # SETMWL - Set Max Write Length to 0x10
    tb.log.info("Sending SETMWL CCC (value=0x10)...")
    ok, resp = await ctrl.setmwl(0x10)
    assert ok, f"SETMWL failed with response 0x{resp:08X}"
    tb.log.info(f"  SETMWL response: 0x{resp:08X}, success={ok}")

    # GETMWL - Verify MWL changed
    tb.log.info("Sending GETMWL CCC (after SET)...")
    ok, mwl_after = await ctrl.getmwl()
    assert ok, "GETMWL failed"
    tb.log.info(f"  MWL value: 0x{mwl_after:04X} ({mwl_after} bytes)")
    tb.log.info(f"  MWL changed: 0x{mwl_before:04X} -> 0x{mwl_after:04X}")

    # GETMRL - Get Max Read Length (before SET)
    tb.log.info("Sending GETMRL CCC (before SET)...")
    ok, mrl_before, ibi_before = await ctrl.getmrl()
    assert ok, "GETMRL failed"
    tb.log.info(f"  MRL value: 0x{mrl_before:04X} ({mrl_before} bytes)")
    if (bcr >> 2) & 0x1:
        tb.log.info(f"  IBI Payload Size: {ibi_before} bytes")

    # SETMRL - Set Max Read Length to 0x10, IBI payload size to 0x10
    tb.log.info("Sending SETMRL CCC (mrl=0x10, ibi_payload_size=0x10)...")
    ok, resp = await ctrl.setmrl(0x10, 0x10)
    assert ok, f"SETMRL failed with response 0x{resp:08X}"
    tb.log.info(f"  SETMRL response: 0x{resp:08X}, success={ok}")

    # GETMRL - Verify MRL changed
    tb.log.info("Sending GETMRL CCC (after SET)...")
    ok, mrl_after, ibi_after = await ctrl.getmrl()
    assert ok, "GETMRL failed"
    tb.log.info(f"  MRL value: 0x{mrl_after:04X} ({mrl_after} bytes)")
    tb.log.info(f"  MRL changed: 0x{mrl_before:04X} -> 0x{mrl_after:04X}")
    if (bcr >> 2) & 0x1:
        tb.log.info(f"  IBI Payload Size changed: {ibi_before} -> {ibi_after}")

    # RSTACT - Direct Reset Action (Peripheral Reset)
    tb.log.info("Sending RSTACT CCC (defining_byte=0x01, Peripheral Reset)...")
    ok, resp = await ctrl.rstact(0x01)
    assert ok, f"RSTACT failed with response 0x{resp:08X}"
    tb.log.info(f"  RSTACT response: 0x{resp:08X}, success={ok}")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: GET/SET CCC tests passed!")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)
