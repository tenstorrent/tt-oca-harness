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
from env.i3c_api import I3CController, I3CHelper, I3CTarget, PioIntrStatus, TtiQueueStatus

# Import register addresses
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../../regs/gen/py"))
# Constrained-random framework (shared, IP-agnostic core via i3c domain layer)
import oca_i3c_wrap_reg as _csr
from env.i3c_rand import RandMgr, rand_bytes, rand_i3c_addr, rand_ibi_mdb

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
        bool: True if NACK detected (bus SDA released high on the 9th SCL rising edge)
    """
    log.info("NACK monitor: Monitoring SCL for 9th rising edge...")
    scl_edge_count = 0

    # Monitor the resolved open-drain bus through scl_i[0] and sda_i[0];
    # per-instance outputs do not represent the shared bus level.
    def bus_scl():
        return int(dut.scl_i.value) & 1

    def bus_sda():
        return int(dut.sda_i.value) & 1

    # Wait for a genuine START condition on the bus: SDA falling while SCL is high.
    log.info(f"Waiting for Start Condition - simulation time: {get_sim_time(units='ns')} ns")
    prev_sda = bus_sda()
    while True:
        await RisingEdge(dut.clk)
        cur_sda = bus_sda()
        if prev_sda == 1 and cur_sda == 0 and bus_scl() == 1:
            break
        prev_sda = cur_sda
    log.info(f"Start Condition Received - simulation time: {get_sim_time(units='ns')} ns")

    # Count 9 BUS SCL rising edges (8 address/RnW bits + the ACK slot); sample SDA on the 9th.
    while True:
        while bus_scl() == 1:  # wait for SCL low
            await RisingEdge(dut.clk)
        while bus_scl() == 0:  # then the rising edge
            await RisingEdge(dut.clk)

        scl_edge_count += 1
        sda_value = bus_sda()
        log.debug(f"NACK monitor: SCL rising edge #{scl_edge_count}, bus SDA = {sda_value}")

        # On the 9th edge, check the ACK/NACK bit on the bus (NACK = SDA released high).
        if scl_edge_count == 9:
            if sda_value == 1:
                log.info("NACK monitor: NACK detected (SDA=1 on 9th SCL)")
                return True
            else:
                log.error("NACK monitor: ACK detected (SDA=0 on 9th SCL) - Expected NACK!")
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

    # First require the immediate-write descriptor path to succeed against the
    # assigned address, preventing malformed descriptors from satisfying the
    # negative case.
    tb.log.info("-" * 60)
    tb.log.info("Positive control: immediate write to the ASSIGNED address (DAT 0)")
    tb.log.info("-" * 60)
    good_data = rand_bytes(r, 4)
    cmd_lo, cmd_hi = build_immediate_write_cmd(good_data, dat_idx=0, tid=0)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

    ok, _reg = await helper.poll_field(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=50000,
        interval=10,
    )
    assert ok, "positive control: timeout waiting for the response descriptor"
    good_resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    good_err = (good_resp >> 28) & 0xF  # ERR_STATUS, HCI v1.2 Table 146
    tb.log.info(f"  Positive control response: 0x{good_resp:08X} err_status={good_err}")
    assert good_err == 0, (
        f"positive control failed: immediate write to the assigned address returned "
        f"err_status=0x{good_err:X}, expected 0x0 SUCCESS (resp=0x{good_resp:08X}). "
        f"The negative leg below cannot be trusted while this path errors."
    )
    tb.log.info("  Positive control passed: descriptor path succeeds when it should")

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

    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)

    # Wait for response
    tb.log.info("Waiting for response (expecting error)...")
    ok, reg = await helper.poll_field(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=50000,
        interval=10,
    )
    assert ok, "Timeout waiting for response descriptor"

    # Read response descriptor
    resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
    err_status = (resp >> 28) & 0xF
    data_length = resp & 0xFFFF
    tid = (resp >> 24) & 0xF

    tb.log.info(f"  Response: 0x{resp:08X}")
    tb.log.info(f"    err_status: {err_status} (0x{err_status:X})")
    tb.log.info(f"    data_length: {data_length}")
    tb.log.info(f"    tid: {tid}")

    # Verify error status is non-zero
    assert err_status != 0, f"Expected non-zero error status, got err_status={err_status}"
    tb.log.info(f"  ERR_STATUS DETECTED: err_status={err_status} (as expected)")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: Error handling test passed!")
    tb.log.info("  Transaction to wrong address was correctly aborted")
    tb.log.info(f"  Error status: {err_status}")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)


@cocotb.test(timeout_time=10000, timeout_unit="us")
async def i3c_fifo_overflow(dut):
    """RX FIFO overflow: read past the FIFO capacity without draining it.

    1. Initialize controller and target, perform SETDASA
    2. Issue a private read longer than the RX FIFO depth read from QUEUE_SIZE
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

    # Verify the target received its dynamic address.
    ok, dyn_addr = await tgt.wait_dynamic_addr()
    tb.log.info(f"  Target dynamic address: 0x{dyn_addr:02X}, valid={ok}")
    assert ok, "Target did not receive dynamic address"
    assert dyn_addr == TARGET_DYNAMIC_ADDR

    bytes_per_entry = 4
    dat_idx = 0
    # Derive RX FIFO capacity from QUEUE_SIZE and request a larger transfer to
    # guarantee overflow regardless of the configured depth. QUEUE_SIZE =
    # {tx_data_buffer_size[31:24], rx_data_buffer_size[23:16],
    # ibi_status_size[15:8], cr_queue_size[7:0]}; data-buffer sizes are encoded as
    # 2^(N+1) entries.
    queue_size_reg = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_QUEUE_SIZE_REG_ADDR)
    rx_fifo_entries = 1 << (((queue_size_reg >> 16) & 0xFF) + 1)
    rx_fifo_bytes = rx_fifo_entries * bytes_per_entry
    # Read well past the RX FIFO so it overflows while the drain stays off. Kept a
    # multiple of 4 for clean FIFO-entry accounting.
    data_len = rx_fifo_bytes + r.randint(16, 96) * 4  # RX FIFO + 64..384 bytes

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
    TTI_TX_DESC_COMPLETE = 1 << 26

    tb.log.info(f"  Data length: {data_len} bytes")
    tb.log.info(
        f"  Target TX threshold: {tx_bytes_per_interrupt} bytes ({tx_entries_per_interrupt} entries)"
    )

    # Arm the target before issuing the read because it NACKs a private-read
    # address while its TX queue is empty. The overflow is caused by leaving the
    # controller RX FIFO undrained while the target streams data.
    bytes_written = 0  # bytes written to target TX FIFO
    loop_count = 0

    # Poll QUEUE_STATUS for target TX descriptor space because TX_DESC_THLD_STAT is
    # not a reliable readiness indication.
    ok, _qs = await helper.poll_field_clear(
        tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_QUEUE_STATUS_REG_ADDR,
        TtiQueueStatus,
        "tx_desc_queue_full",
        max_polls=1000,
        interval=10,
    )
    assert ok, (
        "timeout waiting for target TX descriptor queue space "
        f"(tx_desc_queue_full never cleared in 1000 polls, data_len={data_len})"
    )

    # Write TX descriptor to target - tells target how many bytes to send
    tx_desc = data_len << 16
    await helper.write(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TX_DESC_QUEUE_PORT_REG_ADDR, tx_desc)
    tb.log.debug(f"  Wrote TX descriptor 0x{tx_desc:08X} (byte_count={data_len})")

    # Before issuing the read, prefill until the target TX queue is full or the
    # complete payload is queued. The target only ACKs when enough data is queued
    # to start the transfer.
    while bytes_written < data_len:
        qs = await helper.read_into(
            tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_QUEUE_STATUS_REG_ADDR, TtiQueueStatus
        )
        if qs.f.tx_data_queue_full:
            break
        word = helper.pack_bytes(tx_data[bytes_written : bytes_written + bytes_per_entry])
        await helper.write(tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, word)
        bytes_written += min(bytes_per_entry, data_len - bytes_written)
    tb.log.debug(f"  Pre-filled {bytes_written}/{data_len} bytes to target TX (to FULL/threshold)")

    # Issue the read command AFTER the target is armed (cmd_lo rnw=1, cmd_hi data_length)
    cmd_lo = (0x0 << 0) | (dat_idx << 16) | (1 << 29) | (1 << 30) | (1 << 31)  # rnw=1
    cmd_hi = data_len << 16
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
    tb.log.debug(f"  Read command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})")

    # Main loop - wait for controller response (overflow error) or target TX_DESC_COMPLETE
    # NOTE: Intentionally NOT draining controller RX FIFO to cause overflow
    while True:
        loop_count += 1
        if loop_count % 100 == 0:
            tb.log.debug(f"  Loop {loop_count}, written={bytes_written}/{data_len}")

        # Check if controller response is ready (overflow error will trigger this)
        ctrl_status = await helper.read_into(
            ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR, PioIntrStatus
        )
        if ctrl_status.f.resp_ready_stat:
            tb.log.debug(f"  Controller response ready, bytes_written={bytes_written}")
            break

        # Check if target TX transaction is complete
        tgt_status = await helper.read(
            tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_INTERRUPT_STATUS_REG_ADDR
        )
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
                await helper.write(
                    tgt.base + _csr.I3C_CSR_0__I3C_EC_TTI_TX_DATA_PORT_REG_ADDR, word
                )
            bytes_written += chunk
            tb.log.debug(f"  Wrote {chunk} bytes to target TX, total={bytes_written}/{data_len}")

        # Do not drain the controller RX FIFO; the requested length exceeds its
        # runtime-derived capacity.

        await ClockCycles(dut.clk, 10)

    # Wait for controller response descriptor (may already be ready from loop above)
    tb.log.info("Waiting for controller response (expecting overflow error)...")
    ok, reg = await helper.poll_field(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=50000,
        interval=10,
    )
    assert ok, "Timeout waiting for response descriptor"

    # Read response descriptor
    resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
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

    tb.log.info(f"  OVERFLOW ERR_STATUS DETECTED: err_status=0x{err_status:X} (Ovl) as expected")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: FIFO overflow test passed!")
    tb.log.info("  Controller correctly reported Ovl (overflow) error")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)


@cocotb.test(timeout_time=10000, timeout_unit="us")
async def i3c_tx_fifo_underflow(dut):
    """TX FIFO underflow: declare a write longer than the bytes actually supplied.

    1. Initialize controller and target, perform SETDASA
    2. Issue a randomized 100..300 byte private write (regular descriptor)
    3. Supply only 8..32 bytes to the controller TX FIFO
    4. Stop filling, so the controller runs the queue dry mid-transfer
    5. Verify the response descriptor reports Ovl (0x6) error status
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
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_lo)
    await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_COMMAND_PORT_REG_ADDR, cmd_hi)
    tb.log.debug(f"  Write command issued (cmd_lo=0x{cmd_lo:08X}, cmd_hi=0x{cmd_hi:08X})")

    # Wait for TX_THLD_STAT to indicate we can write to TX FIFO
    tb.log.info("Waiting for TX threshold interrupt...")
    ok, reg = await helper.poll_field(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "tx_thld_stat",
        max_polls=5000,
        interval=10,
    )
    assert ok, "Timeout waiting for TX threshold interrupt"

    # Supply fewer bytes than the command declared, so the FIFO runs dry.
    tb.log.info(f"Filling only {bytes_to_fill} bytes to TX FIFO (deliberately insufficient)...")
    for i in range(0, bytes_to_fill, bytes_per_entry):
        word = helper.pack_bytes(tx_data[i : i + bytes_per_entry])
        await helper.write(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_TX_DATA_PORT_REG_ADDR, word)
        tb.log.debug(f"  TX entry {i // bytes_per_entry}: 0x{word:08X}")

    tb.log.info("Stopping TX FIFO fill - waiting for underflow error...")

    # Wait for controller response descriptor (should get Ovl error)
    ok, reg = await helper.poll_field(
        ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_PIO_INTR_STATUS_REG_ADDR,
        PioIntrStatus,
        "resp_ready_stat",
        max_polls=100000,
        interval=10,
    )
    assert ok, "Timeout waiting for response descriptor"

    # Read response descriptor
    resp = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_RESPONSE_PORT_REG_ADDR)
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

    tb.log.info(f"  UNDERFLOW ERR_STATUS DETECTED: err_status=0x{err_status:X} (Ovl) as expected")

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: TX FIFO underflow test passed!")
    tb.log.info("  Controller correctly reported Ovl (underflow) error")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)


@cocotb.test(timeout_time=10000, timeout_unit="us")
async def i3c_ibi_fifo_overflow(dut):
    """A full IBI Queue must stop the controller ACKing incoming IBIs.

    Per MIPI I3C HCI v1.2 section 6.5.4, the controller accepts incoming IBIs
    unless the IBI Queue is full. The test fills the queue with one IBI, leaves
    it unread, and verifies that the next IBI is NACKed on the bus. It does not
    require unrelated transfers to progress while the queue remains full.
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

    # Program DAT.ibi_payload from BCR[2]; the controller aborts inbound IBIs
    # when this policy bit is clear.
    await ctrl.configure_target_ibi(0, TARGET_STATIC_ADDR, TARGET_DYNAMIC_ADDR)

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
    queue_size_reg = await helper.read(ctrl.base + _csr.I3C_CSR_0__PIOCONTROL_QUEUE_SIZE_REG_ADDR)
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

    # Arm the NACK monitor before queuing IBI #2 so it observes that IBI's
    # arbitration attempt.
    monitor_task = cocotb.start_soon(wait_for_9th_scl_and_check_nack(dut, tb.log))

    # Queue IBI #2 -- the transaction the monitor observes is this IBI's arbitration attempt
    ok = await tgt.write_ibi(mdb_2, ibi_payload_2)
    assert ok, "Target write_ibi #2 queue failed"

    nack_detected = await monitor_task
    assert nack_detected, "Controller did not NACK the second IBI as expected!"
    tb.log.info("Controller correctly NACKed the second IBI (IBI FIFO full)")

    # Wait for IBI #2 to settle before ending. With zero retries and a full queue
    # it cannot succeed, but its terminal status is unspecified and is not asserted.
    ok, last_ibi_status = await tgt.wait_ibi_done()
    tb.log.info(
        f"  Target IBI #2 settled: done={ok}, status={last_ibi_status} "
        f"(cannot succeed while the IBI Queue stays full)"
    )

    tb.log.info("=" * 60)
    tb.log.info("SUCCESS: IBI FIFO Overflow Test Complete")
    tb.log.info("  IBI FIFO was filled completely and left unread")
    tb.log.info("  Controller ACKed IBI #1 and NACKed IBI #2 (HCI v1.2 section 6.5.4)")
    tb.log.info("=" * 60)

    await ClockCycles(dut.clk, 100)
