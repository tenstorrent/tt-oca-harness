# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C IBI (In-Band Interrupt) Sanity Test

Tests IBI transmission from target to controller with payload data:
  1. Initialize controller and target
  2. Configure bus timing (T_AVAL, T_IDLE)
  3. SETDASA to assign dynamic address
  4. GETBCR to verify IBI capability
  5. SETMRL to set IBI payload size
  6. Target sends IBI with payload via write_ibi()
  7. Controller receives IBI via wait_ibi_received() + read_ibi()
  8. Verify IBI data matches

Uses i3c_api.py for all I3C operations.
"""

import logging
import os
import sys

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from i3c_api import I3CController, I3CHelper, I3CTarget, PioIntrStatus

# Import register addresses for immediate write handling
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../data/registers/py_headers"))
from I3CCSR_reg import (
    I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR,
    I3C_EC_TTI_RX_DATA_PORT_REG_ADDR,
    I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR,
    PIOCONTROL_COMMAND_PORT_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
    PIOCONTROL_RESPONSE_PORT_REG_ADDR,
)

# Address mapping
CTRL_BASE = 0x0000
TGT_BASE = 0x1000
TARGET_STATIC_ADDR = 0x10
TARGET_DYNAMIC_ADDR = 0x10


class TB:
    """Minimal testbench for I3C IBI sanity test."""

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


def build_immediate_write_cmd(data_bytes, dat_idx=0, tid=0):
    """
    Build immediate write command descriptor (64-bit).

    Immediate descriptor format (from i3c_pkg.sv):
    DWORD 0 (cmd_lo):
      [31]    toc       - Terminate on completion
      [30]    wroc      - Response on completion
      [29]    rnw       - Direction (0 for write)
      [28:26] mode      - Transfer mode (0 = SDR0)
      [25:23] dtt       - Data Transfer Type / number of valid data bytes
      [22:21] reserved
      [20:16] dev_idx   - Device index in DAT
      [15]    cp        - Command present (0 for private)
      [14:7]  cmd       - CCC code (0 for private)
      [6:3]   tid       - Transaction ID
      [2:0]   attr      - 0x1 for ImmediateDataTransfer

    DWORD 1 (cmd_hi):
      [31:24] data_byte4 - byte 3
      [23:16] data_byte3 - byte 2
      [15:8]  data_byte2 - byte 1
      [7:0]   def_or_data_byte1 - byte 0

    Returns: (cmd_lo, cmd_hi)
    """
    dtt = len(data_bytes)
    attr = 0x1  # ImmediateDataTransfer

    # Build cmd_lo
    cmd_lo = (
        (attr << 0)  # [2:0] attr = 1 (ImmediateDataTransfer)
        | (tid << 3)  # [6:3] tid
        | (0 << 7)  # [14:7] cmd (unused for private)
        | (0 << 15)  # [15] cp = 0 (no command)
        | (dat_idx << 16)  # [20:16] dev_idx
        | (0 << 21)  # [22:21] reserved
        | (dtt << 23)  # [25:23] dtt (number of valid bytes)
        | (0 << 26)  # [28:26] mode = SDR0
        | (0 << 29)  # [29] rnw = 0 (write)
        | (1 << 30)  # [30] wroc = 1 (response on completion)
        | (1 << 31)  # [31] toc = 1 (terminate on completion)
    )

    # Build cmd_hi - pack data bytes (little-endian)
    cmd_hi = 0
    for i, byte in enumerate(data_bytes[:4]):
        cmd_hi |= (byte & 0xFF) << (i * 8)

    return cmd_lo, cmd_hi


@cocotb.test(timeout_time=5000, timeout_unit="us")
async def i3c_ibi_sanity(dut):
    """I3C IBI sanity test: SETDASA + GETBCR + SETMRL + IBI transmission."""
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C IBI (In-Band Interrupt) Sanity Test")
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
    await ctrl.configure_timing_od_i3c()  # Now includes T_AVAL, T_IDLE
    await ctrl.configure_timing_pp()

    tb.log.info("Configuring controller thresholds...")
    await ctrl.configure_thresholds(tx_buf=2, tx_start=0, rx_buf=1, rx_start=0)

    tb.log.info("Initializing target...")
    await tgt.initialize(TARGET_STATIC_ADDR)
    # await tgt.configure_timing_od_i3c()
    # await tgt.configure_timing_pp()
    tb.log.info("Configuring target thresholds...")
    await tgt.configure_thresholds(tx_buf=2, tx_start=0, rx_buf=1, rx_start=0)

    # Enable IBI on both sides
    tb.log.info("Enabling IBI mode on target...")
    await tgt.enable_ibi_mode()
    tb.log.info("Enabling IBI interrupts on controller...")
    await ctrl.enable_ibi_interrupts(ibi_threshold=1)

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

    # GETBCR - Verify IBI capability
    tb.log.info("Sending GETBCR to verify IBI capability...")
    ok, bcr = await ctrl.getbcr(dat_idx=0)
    assert ok, "GETBCR failed"
    tb.log.info(f"  BCR: 0x{bcr:02X}")
    ibi_capable = (bcr >> 1) & 0x1  # BCR[1]
    ibi_payload = (bcr >> 2) & 0x1  # BCR[2]
    tb.log.info(f"    IBI Request Capable (BCR[1]): {ibi_capable}")
    tb.log.info(f"    IBI Payload (BCR[2]): {ibi_payload}")
    assert ibi_capable, "Target does not support IBI (BCR[1]=0)"

    # SETMRL - Set IBI payload size
    ibi_payload_size = 8  # 8 bytes of IBI payload
    tb.log.info(f"Sending SETMRL (mrl=0x100, ibi_payload_size={ibi_payload_size})...")
    ok, resp = await ctrl.setmrl(0x100, ibi_payload_size)
    assert ok, f"SETMRL failed with response 0x{resp:08X}"
    tb.log.info(f"  SETMRL response: 0x{resp:08X}, success={ok}")

    # Test IBI transmission
    tb.log.info("-" * 60)
    tb.log.info("Testing IBI transmission")
    tb.log.info("-" * 60)

    # Target sends IBI
    mdb = 0xAA  # Example MDB value
    ibi_payload_data = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66, 0x77, 0x88]
    tb.log.info(
        f"Target writing IBI: mdb=0x{mdb:02X}, payload={[f'0x{b:02X}' for b in ibi_payload_data]}"
    )
    ok = await tgt.write_ibi(mdb, ibi_payload_data)
    assert ok, "Target write_ibi failed"

    # Wait for IBI to be received by controller
    tb.log.info("Waiting for controller to receive IBI...")
    ok, reg = await ctrl.wait_ibi_received(max_polls=50000, interval=10)
    assert ok, "Timeout waiting for IBI to reach controller (check T_AVAL timing)"

    tb.log.info("IBI received by controller, reading IBI data...")
    ok, rx_ibi_id, rx_mdb, rx_payload = await ctrl.read_ibi()
    assert ok, "Controller read_ibi failed"

    tb.log.info(f"  Received IBI ID: 0x{rx_ibi_id:02X}")
    tb.log.info(f"  Received MDB: 0x{rx_mdb:02X}")
    tb.log.info(f"  Received Payload: {[f'0x{b:02X}' for b in rx_payload]}")

    # Verify IBI data
    assert rx_mdb == mdb, f"MDB mismatch: 0x{rx_mdb:02X} != 0x{mdb:02X}"
    assert rx_payload == ibi_payload_data, f"Payload mismatch: {rx_payload} != {ibi_payload_data}"

    tb.log.info("IBI data verification: PASSED")

    # Wait for target IBI transmission complete
    tb.log.info("Waiting for target IBI transmission complete...")
    ok, last_ibi_status = await tgt.wait_ibi_done()
    assert ok, "Timeout waiting for IBI_DONE"
    tb.log.info(f"  Target IBI transmission complete (status={last_ibi_status})")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: IBI sanity test passed!")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)


@cocotb.test(timeout_time=5000, timeout_unit="us")
async def i3c_ibi_during_broadcast(dut):
    """
    I3C IBI during broadcast test: Target sends IBI when controller starts
    a transfer with broadcast 0x7e address.

    Tests that IBI is processed first, then the immediate write completes.
    """
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C IBI During Broadcast Test")
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
    await ctrl.configure_thresholds(tx_buf=2, tx_start=0, rx_buf=1, rx_start=0)

    tb.log.info("Initializing target...")
    await tgt.initialize(TARGET_STATIC_ADDR)
    # await tgt.configure_timing_od_i3c()
    tb.log.info("Configuring target thresholds...")
    await tgt.configure_thresholds(tx_buf=2, tx_start=0, rx_buf=1, rx_start=0)

    # Enable IBI on both sides
    tb.log.info("Enabling IBI mode on target...")
    await tgt.enable_ibi_mode()
    tb.log.info("Enabling IBI interrupts on controller...")
    await ctrl.enable_ibi_interrupts(ibi_threshold=1)

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

    # GETBCR - Verify IBI capability
    tb.log.info("Sending GETBCR to verify IBI capability...")
    ok, bcr = await ctrl.getbcr(dat_idx=0)
    assert ok, "GETBCR failed"
    tb.log.info(f"  BCR: 0x{bcr:02X}")
    ibi_capable = (bcr >> 1) & 0x1
    assert ibi_capable, "Target does not support IBI (BCR[1]=0)"

    # SETMRL - Set IBI payload size
    ibi_payload_size = 8
    tb.log.info(f"Sending SETMRL (mrl=0x100, ibi_payload_size={ibi_payload_size})...")
    ok, resp = await ctrl.setmrl(0x100, ibi_payload_size)
    assert ok, f"SETMRL failed with response 0x{resp:08X}"

    # Test IBI during broadcast
    tb.log.info("-" * 60)
    tb.log.info("Testing IBI during broadcast (immediate write)")
    tb.log.info("-" * 60)

    # IBI data
    mdb = 0xBB
    ibi_payload_data = [0xAA, 0xBB, 0xCC, 0xDD]

    # Immediate write data (4 bytes)
    write_data = [0xDE, 0xAD, 0xBE, 0xEF]

    # Step 1: Queue IBI on target
    tb.log.info(
        f"Target queueing IBI: mdb=0x{mdb:02X}, payload={[f'0x{b:02X}' for b in ibi_payload_data]}"
    )
    ok = await tgt.write_ibi(mdb, ibi_payload_data)
    assert ok, "Target write_ibi failed"

    # Step 2: Queue immediate write command on controller
    # This will start the transfer with broadcast 0x7e
    tb.log.info(f"Controller queueing immediate write: data={[f'0x{b:02X}' for b in write_data]}")
    cmd_lo, cmd_hi = build_immediate_write_cmd(write_data, dat_idx=0, tid=1)
    tb.log.debug(f"  cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X}")

    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

    # Step 3: Wait for IBI to be received by controller (should be processed first)
    tb.log.info("Waiting for controller to receive IBI (should happen first)...")
    ok, reg = await ctrl.wait_ibi_received(max_polls=50000, interval=10)
    assert ok, "Timeout waiting for IBI to reach controller"

    # Read and verify IBI data
    tb.log.info("IBI received by controller, reading IBI data...")
    ok, rx_ibi_id, rx_mdb, rx_payload = await ctrl.read_ibi()
    assert ok, "Controller read_ibi failed"

    tb.log.info(f"  Received IBI ID: 0x{rx_ibi_id:02X}")
    tb.log.info(f"  Received MDB: 0x{rx_mdb:02X}")
    tb.log.info(f"  Received Payload: {[f'0x{b:02X}' for b in rx_payload]}")

    assert rx_mdb == mdb, f"MDB mismatch: 0x{rx_mdb:02X} != 0x{mdb:02X}"
    assert rx_payload == ibi_payload_data, f"Payload mismatch: {rx_payload} != {ibi_payload_data}"
    tb.log.info("IBI data verification: PASSED")

    # Step 4: Wait for target IBI transmission complete
    tb.log.info("Waiting for target IBI transmission complete...")
    ok, last_ibi_status = await tgt.wait_ibi_done()
    assert ok, "Timeout waiting for IBI_DONE"
    tb.log.info(f"  Target IBI transmission complete (status={last_ibi_status})")

    # Step 5: Wait for immediate write response (should complete after IBI)
    tb.log.info("Waiting for immediate write response (should complete after IBI)...")
    ok, reg = await helper.poll_field(
        ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus, "resp_ready_stat"
    )
    assert ok, "Timeout waiting for immediate write response"

    # Read response descriptor
    resp = await helper.read(ctrl.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    tb.log.info(f"  Immediate write response: 0x{resp:08X}, err_status={err_status}")
    assert err_status == 0, f"Immediate write error, err_status={err_status}"

    # Step 6: Verify target received the write data
    tb.log.info("Verifying target received write data...")
    TTI_RX_DESC_THLD_STAT = 1 << 11
    for _ in range(1000):
        tgt_status = await helper.read(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
        if tgt_status & TTI_RX_DESC_THLD_STAT:
            break
        await ClockCycles(dut.clk, 10)
    else:
        assert False, "Timeout waiting for target RX descriptor"

    # Read target RX descriptor
    tgt_rx_desc = await helper.read(tgt.base + I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR)
    tgt_rx_data_length = tgt_rx_desc & 0xFFFF
    tb.log.info(f"  Target RX descriptor: 0x{tgt_rx_desc:08X}, data_length={tgt_rx_data_length}")

    # Read target RX data
    rx_data = []
    bytes_remaining = tgt_rx_data_length
    while bytes_remaining > 0:
        word = await helper.read(tgt.base + I3C_EC_TTI_RX_DATA_PORT_REG_ADDR)
        bytes_to_take = min(4, bytes_remaining)
        unpacked = helper.unpack_bytes(word, bytes_to_take)
        rx_data.extend(unpacked)
        bytes_remaining -= bytes_to_take

    rx_data = rx_data[: len(write_data)]
    tb.log.info(f"  Target received: {[f'0x{b:02X}' for b in rx_data]}")
    assert rx_data == write_data, f"Write data mismatch: {rx_data} != {write_data}"
    tb.log.info("Write data verification: PASSED")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: IBI during broadcast test passed!")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)
