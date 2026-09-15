# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.

"""
I3C Immediate Write Sanity Test

Tests immediate data transfer where data (up to 4 bytes) is embedded directly
in the command descriptor instead of being written to the TX FIFO.

Uses i3c_api.py for all I3C operations.
"""

import logging
import os

# Import register addresses
import sys

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge, Timer
from cocotbext.axi import AxiLiteBus, AxiLiteMaster
from env.i3c_api import I3CController, I3CHelper, I3CTarget

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../regs/gen/py"))
import oca_i3c_wrap_reg as _csr

# Address mapping
CTRL_BASE = 0x0000
TGT_BASE = 0x1000
TARGET_STATIC_ADDR = 0x10
TARGET_DYNAMIC_ADDR = 0x10

# Test cases: (description, data_bytes)
TEST_CASES = [
    ("1-byte", [0xAA]),
    ("2-byte", [0xBB, 0xCC]),
    ("3-byte", [0xDD, 0xEE, 0xFF]),
    ("4-byte", [0x11, 0x22, 0x33, 0x44]),
]


class TB:
    """Minimal testbench for I3C immediate write test."""

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


async def immediate_write(helper, ctrl, tgt, data_bytes, tid=0, dat_idx=0):
    """
    Perform immediate write transfer.

    Unlike private_write, data is embedded in the command descriptor
    and no TX FIFO writes are needed.

    Returns: (success, response, rx_data)
    """
    from env.i3c_api import PioIntrStatus

    cmd_lo, cmd_hi = build_immediate_write_cmd(data_bytes, dat_idx, tid)

    helper.log.debug(
        f"immediate_write: {len(data_bytes)} bytes, data={[f'0x{b:02X}' for b in data_bytes]}"
    )
    helper.log.debug(f"  cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X}")

    # Write command descriptor (no TX FIFO writes needed)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

    # Wait for controller response
    ok, reg = await helper.poll_field(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
    )
    if not ok:
        helper.log.error("immediate_write: timeout waiting for response")
        return False, 0, []

    # Read response descriptor
    resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    resp_data_length = resp & 0xFFFF
    helper.log.debug(
        f"immediate_write: response=0x{resp:08X}, err={err_status}, data_length={resp_data_length}"
    )

    if err_status != 0:
        helper.log.error(f"immediate_write: transfer error, err_status={err_status}")
        return False, resp, []

    # Wait for target RX descriptor to be ready. Expiry must fail the transfer: reading
    # the descriptor queue after failing to observe it non-empty parses whatever that
    # read returned. Mirrors the shared API's hardened wait (i3c_api.py private_write).
    TTI_RX_DESC_THLD_STAT = 1 << 11
    POLLS = 1000
    tgt_status = 0
    for _ in range(POLLS):
        tgt_status = await helper.read(
            tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR
        )
        if tgt_status & TTI_RX_DESC_THLD_STAT:
            break
        await ClockCycles(helper.dut.clk, 10)
    else:
        helper.log.error(
            f"immediate_write: timeout waiting for target RX descriptor after {POLLS} "
            f"polls; last TTI_INTERRUPT_STATUS=0x{tgt_status:08X}, "
            f"expected {len(data_bytes)} bytes"
        )
        return False, resp, []

    # Read target RX descriptor
    tgt_rx_desc = await helper.read(
        tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_RX_DESC_QUEUE_PORT_REG_ADDR
    )
    tgt_rx_data_length = tgt_rx_desc & 0xFFFF
    tgt_rx_error = (tgt_rx_desc >> 20) & 0xFFF
    helper.log.debug(
        f"immediate_write: target RX descriptor=0x{tgt_rx_desc:08X}, "
        f"data_length={tgt_rx_data_length}, error={tgt_rx_error}"
    )

    # A target-side receive error is fatal to the transfer, not a warning: the shared
    # API treats the identical field that way (i3c_api.py private_write).
    if tgt_rx_error != 0:
        helper.log.error(f"immediate_write: target RX descriptor reports error={tgt_rx_error}")
        return False, resp, []

    # Drain target RX FIFO
    rx_data = []
    bytes_remaining = tgt_rx_data_length
    while bytes_remaining > 0:
        word = await helper.read(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_RX_DATA_PORT_REG_ADDR)
        bytes_to_take = min(4, bytes_remaining)
        unpacked = helper.unpack_bytes(word, bytes_to_take)
        helper.log.debug(
            f"immediate_write: RX word=0x{word:08X} -> {[f'0x{b:02X}' for b in unpacked]}"
        )
        rx_data.extend(unpacked)
        bytes_remaining -= bytes_to_take

    return True, resp, rx_data[: len(data_bytes)]


@cocotb.test(timeout_time=5000, timeout_unit="us")
async def test_immediate_write_sanity(dut):
    """I3C immediate write test: SETDASA + immediate writes (1-4 bytes)."""
    tb = TB(dut)

    tb.log.info("=" * 60)
    tb.log.info("I3C Immediate Write Sanity Test")
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

    # Disable TX_THLD_STAT interrupt - not needed for immediate writes (no TX FIFO used)
    from env.i3c_api import PioIntrStatusEnable

    intr_en = PioIntrStatusEnable()
    intr_en.f.rx_thld_stat_en = 1
    intr_en.f.resp_ready_stat_en = 1
    intr_en.f.cmd_queue_ready_stat_en = 1
    # tx_thld_stat_en = 0 (not set, disabled)
    await helper.write(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_ENABLE_REG_ADDR, intr_en.val
    )
    tb.log.info("Disabled TX_THLD_STAT interrupt (not needed for immediate writes)")

    # Run all immediate write test cases
    tb.log.info("-" * 60)
    tb.log.info("Testing immediate writes (1-4 bytes)")
    tb.log.info("-" * 60)

    for tid, (desc, write_data) in enumerate(TEST_CASES):
        tb.log.info(f"Test case: {desc} write, data={[f'0x{b:02X}' for b in write_data]}")

        ok, resp, rx_data = await immediate_write(helper, ctrl, tgt, write_data, tid=tid)
        tb.log.info(f"  Response: 0x{resp:08X}, success={ok}")
        tb.log.info(f"  Target received: {[f'0x{b:02X}' for b in rx_data]}")

        assert ok, f"{desc} immediate write failed with response 0x{resp:08X}"

        # Verify data
        if rx_data == write_data:
            tb.log.info(f"  {desc} verification: PASSED")
        else:
            tb.log.error(f"  {desc} verification: FAILED")
            tb.log.error(f"  Expected: {[f'0x{b:02X}' for b in write_data]}")
            tb.log.error(f"  Received: {[f'0x{b:02X}' for b in rx_data]}")
            assert False, f"{desc} data mismatch"

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: All immediate write tests passed!")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)
