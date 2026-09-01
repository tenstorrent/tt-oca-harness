# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Error Sanity Test

Tests error handling when controller addresses a non-existent target:
  1. Initialize controller and target
  2. SETDASA to assign dynamic address to real target (DAT index 0)
  3. Set up DAT entry with wrong address (DAT index 1)
  4. Issue immediate write to wrong address
  5. Verify transaction aborts with non-zero error status in response

Uses i3c_api.py for all I3C operations.
"""

import logging
import os
import sys

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotb.utils import get_sim_time
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from i3c_api import I3CController, I3CHelper, I3CTarget, PioIntrStatus

# Import register addresses
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../data/registers/py_headers"))
# Constrained-random framework (shared, IP-agnostic core via i3c domain layer)
from i3c_rand import RandMgr, rand_bytes, rand_i3c_addr, rand_ibi_mdb
from I3CCSR_reg import (
    # TTI registers for fifo overflow test
    I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR,
    I3C_EC_TTI_TX_DATA_PORT_REG_ADDR,
    I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR,
    PIOCONTROL_COMMAND_PORT_REG_ADDR,
    PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
    PIOCONTROL_QUEUE_SIZE_REG_ADDR,
    PIOCONTROL_RESPONSE_PORT_REG_ADDR,
    PIOCONTROL_TX_DATA_PORT_REG_ADDR,
)

# Address mapping
CTRL_BASE = 0x0000
TGT_BASE = 0x1000
TARGET_STATIC_ADDR = 0x10
TARGET_DYNAMIC_ADDR = 0x10


class TB:
    """Minimal testbench for I3C error sanity test."""

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
        # Actively pulse reset so each cocotb test in this module starts from a
        # clean DUT state. cocotb runs every @cocotb.test in one simulation, and
        # the SV testbench only drives the power-on reset once, so without an
        # explicit per-test reset the bus/controller state from a previous test
        # leaks into the next one and breaks its SETDASA. The SV TB stops driving
        # rst_n after the initial pulse, so depositing here does not conflict.
        self.dut.rst_n.value = 0
        await ClockCycles(self.dut.clk, 10)
        self.dut.rst_n.value = 1
        await ClockCycles(self.dut.clk, 5)
        self.log.info("Reset released (per-test active reset)")


async def wait_for_9th_scl_and_check_nack(dut, log):
    """
    Monitor SCL and check that controller NACKs on the 9th SCL bit.

    Args:
        dut: Device under test
        log: Logger instance

    Returns:
        bool: True if NACK detected (sda_o[0] == 0 on 9th SCL rising edge)
    """
    log.info("NACK monitor: Monitoring SCL for 9th rising edge...")
    scl_edge_count = 0

    # Wait for Start condition
    log.info(f"Waiting for Start Condition - simulation time: {get_sim_time(units='ns')} ns")
    while dut.scl_o.value[1] == 1:
        await RisingEdge(dut.clk)
    log.info(f"Start Condition Received - simulation time: {get_sim_time(units='ns')} ns")

    # Wait for 9 SCL rising edges
    while 1:
        # Now wait for SCL rising edge
        while dut.scl_o.value[1] == 0:
            await RisingEdge(dut.clk)

        scl_edge_count += 1
        sda_value = int(dut.sda_o.value[1])
        log.debug(
            f"NACK monitor: SCL rising edge #{scl_edge_count}, Controller SDA output = {sda_value}"
        )

        # On the 9th edge, check SDA
        if scl_edge_count == 9:
            if sda_value == 1:
                log.info("NACK monitor: NACK detected (SDA=1 on 9th SCL)")
                return True
            else:
                log.error("NACK monitor: ACK detected (SDA=0 on 9th SCL) - Expected NACK!")
                return False

        # Wait for SCL falling edge first (to ensure we catch the rising edge)
        while dut.scl_o.value[1] == 1:
            await RisingEdge(dut.clk)

    return False


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
async def i3c_error_wrong_addr(dut):
    """I3C error test: SETDASA + immediate write to wrong address should fail."""
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C Error Sanity Test - Wrong Target Address")
    tb.log.info("=" * 60)

    await Timer(500, units="ns")
    await tb.setup_axi_master()
    await tb.wait_for_reset()

    r = RandMgr(name="error_wrong_addr")  # seed logged; +seed/SEED override

    # Create API objects
    helper = I3CHelper(tb.axi_master, dut, tb.log)
    ctrl = I3CController(CTRL_BASE, helper)
    tgt = I3CTarget(TGT_BASE, helper)

    # Initialize controller
    tb.log.info("Initializing controller...")
    await ctrl.initialize()
    await ctrl.configure_timing_od_i3c()
    await ctrl.configure_timing_pp()

    tb.log.info("Configuring controller thresholds...")
    await ctrl.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    # Initialize target
    tb.log.info("Initializing target...")
    await tgt.initialize(TARGET_STATIC_ADDR)
    tb.log.info("Configuring target thresholds...")
    await tgt.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    # SETDASA - assign dynamic address to real target at DAT index 0
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

    # Random wrong address: legal, non-reserved, and not the assigned target.
    # Any address other than the single assigned target has no device -> NACK,
    # so the error condition stays reachable for every seed.
    wrong_addr = rand_i3c_addr(r, exclude={TARGET_DYNAMIC_ADDR, TARGET_STATIC_ADDR})

    # Set up DAT entry with wrong address at index 1
    tb.log.info("-" * 60)
    tb.log.info("Setting up wrong address in DAT index 1")
    tb.log.info("-" * 60)
    tb.log.info(f"Writing DAT entry 1 with wrong address 0x{wrong_addr:02X}...")
    await ctrl.set_dat_entry(1, wrong_addr, wrong_addr)

    # Issue immediate write to wrong address (DAT index 1)
    tb.log.info("-" * 60)
    tb.log.info("Testing immediate write to wrong target address")
    tb.log.info("-" * 60)

    write_data = rand_bytes(r, 4)
    tb.log.info(
        f"Issuing immediate write to DAT index 1 (wrong addr 0x{wrong_addr:02X}): "
        f"data={[f'0x{b:02X}' for b in write_data]}"
    )

    cmd_lo, cmd_hi = build_immediate_write_cmd(write_data, dat_idx=1, tid=1)
    tb.log.debug(f"  cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X}")

    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

    # Wait for response
    tb.log.info("Waiting for response (expecting error)...")
    ok, reg = await helper.poll_field(
        ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=50000,
        interval=10,
    )
    assert ok, "Timeout waiting for response descriptor"

    # Read response descriptor
    resp = await helper.read(ctrl.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    data_length = resp & 0xFFFF
    tid = (resp >> 24) & 0xF

    tb.log.info(f"  Response: 0x{resp:08X}")
    tb.log.info(f"    err_status: {err_status} (0x{err_status:X})")
    tb.log.info(f"    data_length: {data_length}")
    tb.log.info(f"    tid: {tid}")

    # Verify error status is non-zero
    assert err_status != 0, f"Expected non-zero error status, got err_status={err_status}"
    tb.log.info(f"  ERROR DETECTED: err_status={err_status} (as expected)")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: Error handling test passed!")
    tb.log.info("  Transaction to wrong address was correctly aborted")
    tb.log.info(f"  Error status: {err_status}")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)


@cocotb.test(timeout_time=10000, timeout_unit="us")
async def i3c_fifo_overflow(dut):
    """I3C FIFO overflow test: 500-byte read without draining RX FIFO should cause overflow error.

    This test:
    1. Initialize controller and target, perform SETDASA
    2. Issue a 500-byte private read
    3. Fill target TX FIFO but DO NOT drain controller RX FIFO
    4. Verify response descriptor reports Ovl (0x6) error status
    """
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C FIFO Overflow Test - RX FIFO Overflow")
    tb.log.info("=" * 60)

    await Timer(500, units="ns")
    await tb.setup_axi_master()
    await tb.wait_for_reset()

    r = RandMgr(name="fifo_overflow")  # seed logged; +seed/SEED override

    # Create API objects
    helper = I3CHelper(tb.axi_master, dut, tb.log)
    ctrl = I3CController(CTRL_BASE, helper)
    tgt = I3CTarget(TGT_BASE, helper)

    # Initialize controller
    tb.log.info("Initializing controller...")
    await ctrl.initialize()
    await ctrl.configure_timing_od_i3c()
    await ctrl.configure_timing_pp()

    tb.log.info("Configuring controller thresholds...")
    await ctrl.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    # Initialize target
    tb.log.info("Initializing target...")
    await tgt.initialize(TARGET_STATIC_ADDR)
    tb.log.info("Configuring target thresholds...")
    await tgt.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    # SETDASA - assign dynamic address
    tb.log.info(
        f"Sending SETDASA (static=0x{TARGET_STATIC_ADDR:02X}, "
        f"dynamic=0x{TARGET_DYNAMIC_ADDR:02X})..."
    )
    ok, resp = await ctrl.send_setdasa(TARGET_STATIC_ADDR, TARGET_DYNAMIC_ADDR)
    tb.log.info(f"  Response: 0x{resp:08X}, success={ok}")
    assert ok, f"SETDASA failed with response 0x{resp:08X}"

    # Verify target got dynamic addressZ
    ok, dyn_addr = await tgt.wait_dynamic_addr()
    tb.log.info(f"  Target dynamic address: 0x{dyn_addr:02X}, valid={ok}")
    assert ok, "Target did not receive dynamic address"
    assert dyn_addr == TARGET_DYNAMIC_ADDR

    # Random read length, constrained to stay far above the controller RX FIFO
    # (8 entries * 4 = 32 bytes) so the overflow is guaranteed for every seed.
    # Kept a multiple of 4 for clean FIFO-entry accounting.
    data_len = r.randint(64, 150) * 4  # 256 .. 600 bytes
    bytes_per_entry = 4
    dat_idx = 0

    # Generate random test data for target to transmit
    tx_data = rand_bytes(r, data_len)

    tb.log.info("-" * 60)
    tb.log.info(f"Testing {data_len}-byte read WITHOUT draining controller RX FIFO")
    tb.log.info("-" * 60)

    # Target TX threshold (in bytes)
    tx_entries_per_interrupt = 1 << (tgt.tx_thld + 1)
    tx_bytes_per_interrupt = tx_entries_per_interrupt * bytes_per_entry

    # TTI interrupt bit definitions
    TTI_TX_DATA_THLD_STAT = 1 << 8
    TTI_TX_DESC_THLD_STAT = 1 << 10
    TTI_TX_DESC_COMPLETE = 1 << 26

    tb.log.info(f"  Data length: {data_len} bytes")
    tb.log.info(
        f"  Target TX threshold: {tx_bytes_per_interrupt} bytes ({tx_entries_per_interrupt} entries)"
    )

    # Issue read command (cmd_lo with rnw=1, cmd_hi with data_length)
    cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 29) | (1 << 30) | (1 << 31)  # rnw=1
    cmd_hi = data_len << 16
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
    tb.log.debug(f"  Read command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})")

    bytes_written = 0  # bytes written to target TX FIFO
    loop_count = 0

    # Wait for target TX descriptor queue to have space
    for _ in range(1000):
        tgt_status = await helper.read(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
        if tgt_status & TTI_TX_DESC_THLD_STAT:
            break
        await ClockCycles(dut.clk, 10)
    else:
        tb.log.warning("  Timeout waiting for TX descriptor queue ready")

    # Write TX descriptor to target - tells target how many bytes to send
    tx_desc = data_len << 16
    await helper.write(tgt.base + I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR, tx_desc)
    tb.log.debug(f"  Wrote TX descriptor 0x{tx_desc:08X} (byte_count={data_len})")

    # Main loop - wait for controller response (overflow error) or target TX_DESC_COMPLETE
    # NOTE: Intentionally NOT draining controller RX FIFO to cause overflow
    while True:
        loop_count += 1
        if loop_count % 100 == 0:
            tb.log.debug(f"  Loop {loop_count}, written={bytes_written}/{data_len}")

        # Check if controller response is ready (overflow error will trigger this)
        ctrl_status = await helper.read_into(
            ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
        )
        if ctrl_status.f.resp_ready_stat:
            tb.log.debug(f"  Controller response ready, bytes_written={bytes_written}")
            break

        # Check if target TX transaction is complete
        tgt_status = await helper.read(tgt.base + I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR)
        if tgt_status & TTI_TX_DESC_COMPLETE:
            tb.log.debug(f"  Target TX_DESC_COMPLETE, bytes_written={bytes_written}")
            break

        # Fill target TX FIFO when TX_DATA_THLD_STAT fires
        if bytes_written < data_len and (tgt_status & TTI_TX_DATA_THLD_STAT):
            remaining_tx = data_len - bytes_written
            chunk = min(tx_bytes_per_interrupt, remaining_tx)
            for i in range(0, chunk, bytes_per_entry):
                word = helper.pack_bytes(
                    tx_data[bytes_written + i : bytes_written + i + bytes_per_entry]
                )
                await helper.write(tgt.base + I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, word)
            bytes_written += chunk
            tb.log.debug(f"  Wrote {chunk} bytes to target TX, total={bytes_written}/{data_len}")

        # NOTE: Intentionally NOT draining controller RX FIFO to cause overflow!
        # The controller RX FIFO is small (8 entries * 4 bytes = 32 bytes)
        # With 500 bytes and no draining, it will overflow

        await ClockCycles(dut.clk, 10)

    # Wait for controller response descriptor (may already be ready from loop above)
    tb.log.info("Waiting for controller response (expecting overflow error)...")
    ok, reg = await helper.poll_field(
        ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=50000,
        interval=10,
    )
    assert ok, "Timeout waiting for response descriptor"

    # Read response descriptor
    resp = await helper.read(ctrl.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    data_length = resp & 0xFFFF
    tid = (resp >> 24) & 0xF

    tb.log.info(f"  Response: 0x{resp:08X}")
    tb.log.info(f"    err_status: {err_status} (0x{err_status:X})")
    tb.log.info(f"    data_length: {data_length}")
    tb.log.info(f"    tid: {tid}")

    # Verify error status is Ovl (0x6 = receive overflow or transfer underflow)
    OVL_ERROR = 0x6
    assert err_status == OVL_ERROR, (
        f"Expected Ovl error (0x{OVL_ERROR:X}), got err_status=0x{err_status:X}"
    )

    tb.log.info(f"  OVERFLOW ERROR DETECTED: err_status=0x{err_status:X} (Ovl) as expected")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: FIFO overflow test passed!")
    tb.log.info("  Controller correctly reported Ovl (overflow) error")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)


@cocotb.test(timeout_time=10000, timeout_unit="us")
async def i3c_tx_fifo_underflow(dut):
    """I3C TX FIFO underflow test: Start 200-byte write but only fill 5 TX entries.

    This test:
    1. Initialize controller and target, perform SETDASA
    2. Issue a 200-byte private write (regular descriptor)
    3. Fill only 5 entries (20 bytes) to controller TX FIFO
    4. Stop filling - controller should detect underflow
    5. Verify response descriptor reports Ovl (0x6) error status
    """
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C TX FIFO Underflow Test")
    tb.log.info("=" * 60)

    await Timer(500, units="ns")
    await tb.setup_axi_master()
    await tb.wait_for_reset()

    r = RandMgr(name="tx_fifo_underflow")  # seed logged; +seed/SEED override

    # Create API objects
    helper = I3CHelper(tb.axi_master, dut, tb.log)
    ctrl = I3CController(CTRL_BASE, helper)
    tgt = I3CTarget(TGT_BASE, helper)

    # Initialize controller
    tb.log.info("Initializing controller...")
    await ctrl.initialize()
    await ctrl.configure_timing_od_i3c()
    await ctrl.configure_timing_pp()

    tb.log.info("Configuring controller thresholds...")
    await ctrl.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    # Initialize target
    tb.log.info("Initializing target...")
    await tgt.initialize(TARGET_STATIC_ADDR)
    tb.log.info("Configuring target thresholds...")
    await tgt.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    # SETDASA - assign dynamic address
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

    # Random declared write length vs a deliberately insufficient fill.
    # Constraint: bytes_to_fill < data_len (both dword-aligned) so the TX FIFO
    # underflows for every seed; fill stays a small handful of entries.
    bytes_per_entry = 4
    data_len = r.randint(25, 75) * 4  # 100 .. 300 bytes declared
    bytes_to_fill = r.randint(2, 8) * 4  # 8 .. 32 bytes actually supplied
    dat_idx = 0

    # Generate random test data
    tx_data = rand_bytes(r, data_len)

    tb.log.info("-" * 60)
    tb.log.info(f"Testing {data_len}-byte write with only {bytes_to_fill} bytes filled (underflow)")
    tb.log.info("-" * 60)

    tb.log.info(f"  Declared write length: {data_len} bytes")
    tb.log.info(
        f"  Actual bytes to fill: {bytes_to_fill} bytes ({bytes_to_fill // bytes_per_entry} entries)"
    )

    # Issue regular write command (attr=0)
    # cmd_lo: attr=0, dat_idx, wroc=1, toc=1
    cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 30) | (1 << 31)
    cmd_hi = data_len << 16  # data_length in upper 16 bits
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
    tb.log.debug(f"  Write command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})")

    # Wait for TX_THLD_STAT to indicate we can write to TX FIFO
    tb.log.info("Waiting for TX threshold interrupt...")
    ok, reg = await helper.poll_field(
        ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "tx_thld_stat",
        max_polls=5000,
        interval=10,
    )
    assert ok, "Timeout waiting for TX threshold interrupt"

    # Fill only 5 entries (20 bytes) - NOT enough for 200-byte write
    tb.log.info(f"Filling only {bytes_to_fill} bytes to TX FIFO (deliberately insufficient)...")
    for i in range(0, bytes_to_fill, bytes_per_entry):
        word = helper.pack_bytes(tx_data[i : i + bytes_per_entry])
        await helper.write(ctrl.base + PIOCONTROL_TX_DATA_PORT_REG_ADDR, word)
        tb.log.debug(f"  TX entry {i // bytes_per_entry}: 0x{word:08X}")

    tb.log.info("Stopping TX FIFO fill - waiting for underflow error...")

    # Wait for controller response descriptor (should get Ovl error)
    ok, reg = await helper.poll_field(
        ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=100000,
        interval=10,
    )
    assert ok, "Timeout waiting for response descriptor"

    # Read response descriptor
    resp = await helper.read(ctrl.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    data_length = resp & 0xFFFF
    tid = (resp >> 24) & 0xF

    tb.log.info(f"  Response: 0x{resp:08X}")
    tb.log.info(f"    err_status: {err_status} (0x{err_status:X})")
    tb.log.info(f"    data_length: {data_length}")
    tb.log.info(f"    tid: {tid}")

    # Verify error status is Ovl (0x6 = receive overflow or transfer underflow)
    OVL_ERROR = 0x6
    assert err_status == OVL_ERROR, (
        f"Expected Ovl error (0x{OVL_ERROR:X}), got err_status=0x{err_status:X}"
    )

    tb.log.info(f"  UNDERFLOW ERROR DETECTED: err_status=0x{err_status:X} (Ovl) as expected")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: TX FIFO underflow test passed!")
    tb.log.info("  Controller correctly reported Ovl (underflow) error")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)


@cocotb.test(timeout_time=10000, timeout_unit="us")
async def i3c_ibi_fifo_overflow(dut):
    """I3C IBI FIFO overflow test: Fill IBI FIFO completely, then send another IBI.

    This test:
    1. Initialize controller and target, perform SETDASA
    2. Enable IBI on both sides
    3. Read IBI FIFO size dynamically from QUEUE_SIZE register
    4. Target sends first IBI with payload that fills IBI FIFO completely
    5. DO NOT read from controller IBI FIFO
    6. Queue a regular private write and another IBI on target
    7. Wait and end test - user checks waveforms for NACK on second IBI, and that private write continues uninterrupted (since IBI FIFO overflow should not affect regular transfers)
    """
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C IBI FIFO Overflow Test")
    tb.log.info("=" * 60)

    await Timer(500, units="ns")
    await tb.setup_axi_master()
    await tb.wait_for_reset()

    # Create API objects
    helper = I3CHelper(tb.axi_master, dut, tb.log)
    ctrl = I3CController(CTRL_BASE, helper)
    tgt = I3CTarget(TGT_BASE, helper)

    # Initialize controller
    tb.log.info("Initializing controller...")
    await ctrl.initialize()
    await ctrl.configure_timing_od_i3c()
    await ctrl.configure_timing_pp()

    tb.log.info("Configuring controller thresholds...")
    await ctrl.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    # Initialize target
    tb.log.info("Initializing target...")
    await tgt.initialize(TARGET_STATIC_ADDR)
    tb.log.info("Configuring target thresholds...")
    await tgt.configure_thresholds(tx_buf=1, tx_start=0, rx_buf=1, rx_start=0)

    r = RandMgr(name="ibi_fifo_overflow")  # seed logged; +seed/SEED override

    # Enable IBI on both sides
    tb.log.info("Enabling IBI mode on target...")
    await tgt.enable_ibi_mode()
    tb.log.info("Enabling IBI interrupts on controller...")
    await ctrl.enable_ibi_interrupts(ibi_threshold=1)

    # SETDASA - assign dynamic address
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

    # Read IBI FIFO size from QUEUE_SIZE register
    # QUEUE_SIZE format: {tx_data_buffer_size[31:24], rx_data_buffer_size[23:16],
    #                     ibi_status_size[15:8], cr_queue_size[7:0]}
    queue_size_reg = await helper.read(ctrl.base + PIOCONTROL_QUEUE_SIZE_REG_ADDR)
    ibi_fifo_size = (queue_size_reg >> 8) & 0xFF
    tb.log.info(f"  QUEUE_SIZE register: 0x{queue_size_reg:08X}")
    tb.log.info(f"  IBI FIFO size: {ibi_fifo_size} entries ({ibi_fifo_size * 4} bytes)")

    # Calculate IBI payload size to fill FIFO completely
    # IBI FIFO layout:
    #   - 1 entry reserved for status descriptor
    #   - (ibi_fifo_size - 1) entries available for IBI data
    #   - Each entry = 4 bytes
    #   - IBI data = MDB (1 byte) + payload
    # To fill completely: payload = ((ibi_fifo_size - 1) * 4) - 1
    ibi_payload_size = ((ibi_fifo_size - 1) * 4) - 1
    tb.log.info(
        f"  Calculated IBI payload size: {ibi_payload_size} bytes "
        f"(status=1 entry, data={ibi_fifo_size - 1} entries, MDB=1 byte)"
    )

    # SETMRL - Set IBI payload size
    tb.log.info(f"Sending SETMRL (mrl=0x100, ibi_payload_size={ibi_payload_size})...")
    ok, resp = await ctrl.setmrl(0x100, ibi_payload_size)
    assert ok, f"SETMRL failed with response 0x{resp:08X}"

    # Test: Send first IBI that fills the IBI FIFO
    tb.log.info("-" * 60)
    tb.log.info("Sending first IBI to fill IBI FIFO completely")
    tb.log.info("-" * 60)

    mdb_1 = rand_ibi_mdb(r)
    ibi_payload_1 = rand_bytes(r, ibi_payload_size)
    tb.log.info(f"Target writing IBI #1: mdb=0x{mdb_1:02X}, payload_size={len(ibi_payload_1)}")

    ok = await tgt.write_ibi(mdb_1, ibi_payload_1)
    assert ok, "Target write_ibi #1 failed"

    # Wait for IBI to be received by controller (but DO NOT read it)
    tb.log.info("Waiting for controller to receive IBI #1...")
    ok, reg = await ctrl.wait_ibi_received(max_polls=50000, interval=10)
    assert ok, "Timeout waiting for IBI #1 to reach controller"

    tb.log.info("IBI #1 received - NOT reading from IBI FIFO (deliberately)")

    # Wait for target IBI transmission complete
    tb.log.info("Waiting for target IBI #1 transmission complete...")
    ok, last_ibi_status = await tgt.wait_ibi_done()
    assert ok, "Timeout waiting for IBI_DONE #1"
    tb.log.info(f"  Target IBI #1 transmission complete (status={last_ibi_status})")

    # Send second IBI - this should be NACKed because IBI FIFO is full
    tb.log.info("-" * 60)
    tb.log.info("Sending second IBI (should be NACKed - FIFO full)")
    tb.log.info("-" * 60)

    mdb_2 = rand_ibi_mdb(r)
    ibi_payload_2 = rand_bytes(r, 4)  # small payload for second IBI
    tb.log.info(f"Target writing IBI #2: mdb=0x{mdb_2:02X}, payload_size={len(ibi_payload_2)}")

    # Queue IBI #2
    ok = await tgt.write_ibi(mdb_2, ibi_payload_2)
    assert ok, "Target write_ibi #2 queue failed"

    # Also do a regular 8-byte private write to verify bus continues working
    tb.log.info("Issuing 8-byte private write to verify bus operation...")
    write_data = [0xDE, 0xAD, 0xBE, 0xEF, 0xCA, 0xFE, 0xBA, 0xBE]
    cmd_lo, cmd_hi = build_immediate_write_cmd(write_data[:4], dat_idx=0, tid=1)
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

    # Monitor for NACK on 9th SCL bit (IBI transaction happens in hardware)
    nack_detected = await wait_for_9th_scl_and_check_nack(dut, tb.log)
    assert nack_detected, "Controller did not NACK the second IBI as expected!"
    tb.log.info("Controller correctly NACKed the second IBI (IBI FIFO full)")

    # Wait for write response
    tb.log.info("Waiting for write response...")
    ok, reg = await helper.poll_field(
        ctrl.base + PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=50000,
        interval=10,
    )
    if ok:
        resp = await helper.read(ctrl.base + PIOCONTROL_RESPONSE_PORT_REG_ADDR)
        err_status = (resp >> 28) & 0xF
        tb.log.info(f"  Write response: 0x{resp:08X}, err_status={err_status}")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: IBI FIFO Overflow Test Complete")
    tb.log.info("  IBI FIFO was filled completely")
    tb.log.info("  Controller correctly NACKed second IBI")
    tb.log.info("  Private write continued uninterrupted")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)
