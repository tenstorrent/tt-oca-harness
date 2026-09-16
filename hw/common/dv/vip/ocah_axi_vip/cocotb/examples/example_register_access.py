# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
example_register_access.py — AXI master/slave agent usage examples.

Demonstrates:
  1. AXI4-Lite single-beat register read/write  (OcahAxiLiteMasterAgent)
  2. AXI4 full-bus single and burst transactions (OcahAxiMasterAgent)
  3. Slave/RAM responder setup                   (OcahAxiLiteSlaveAgent)
  4. Passive monitoring with checker callbacks   (OcahAxiMonitor)

These are not stand-alone cocotb tests; they show the API patterns that a real
test would follow.  Copy-paste the relevant block into your test module and
replace ``dut.axil_if`` / ``dut.axi_if`` with the actual handle names in your
testbench.

Assumptions / conventions
--------------------------
- Clock is driven externally by the test; these snippets call cocotb.start_soon
  for the Clock helper before using the masters.
- Interface names shown (axil_if, axi_if) stand for the testbench's AXI4-Lite
  and AXI4 interface instance handles.
- All data values are plain Python ints; no cocotb BinaryValue objects.
- DUT register addresses shown below are illustrative; substitute the actual
  address map from your register specification.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

from ocah_axi_vip import (
    RESP_DECERR,
    RESP_OKAY,
    RESP_SLVERR,
    OcahAxiChecker,
    OcahAxiLiteMasterAgent,
    OcahAxiLiteSlaveAgent,
    OcahAxiMasterAgent,
    OcahAxiMonitor,
)

# ---------------------------------------------------------------------------
# Example 1 — AXI4-Lite register access (most common OCAH use case)
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_axilite_register_access(dut):
    """Write and read a control register over AXI4-Lite."""

    # Start the clock.  10 ns period = 100 MHz.
    cocotb.start_soon(Clock(dut.aclk, 10, units="ns").start())

    # Construct the master agent once (SV interface handle in, test-facing
    # sequence API out).  Tests drive the VIP through the sequence surface.
    master = OcahAxiLiteMasterAgent(
        dut.axil_if,  # must match interface name in testbench SV
        name="axilite_host",
        timeout_cycles=500,
        data_width=32,
    ).sequence

    # Initialise all master output signals to idle before the first clock edge.
    master.init_signals()

    # Wait for the DUT's active-low reset to deassert.
    await master.wait_for_reset()

    # ---------- write ----------
    # Write 0x1 to control register at offset 0x00.
    resp_code = await master.write(0x0000_0000, 0x0000_0001)
    assert resp_code == RESP_OKAY, f"write failed: resp=0x{resp_code:X}"

    # ---------- read-back ----------
    read_result = await master.read_result(0x0000_0000)
    assert read_result.ok and read_result.resp == RESP_OKAY
    assert read_result.data == 0x0000_0001, f"readback mismatch: got 0x{read_result.data:08X}"

    # ---------- protected access ----------
    # Use PPROT=0b001 (privileged, non-secure, data) for secure registers.
    await master.write(0x0000_0100, 0xDEAD_BEEF, prot=0b001)
    val = await master.read(0x0000_0100, prot=0b001)
    assert val == 0xDEAD_BEEF

    # ---------- statistics ----------
    stats = master.get_statistics()
    assert stats["write_transactions"] == 2
    assert stats["read_transactions"] == 2

    cocotb.log.info("example_axilite_register_access PASSED")


# ---------------------------------------------------------------------------
# Example 1b — AXI4-Lite non-OKAY response inspection
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_axilite_error_response(dut):
    """Inspect a non-OKAY read response without leaking backend enum types."""

    cocotb.start_soon(Clock(dut.aclk, 10, units="ns").start())
    master = OcahAxiLiteMasterAgent(
        dut.axil_if,
        name="axilite_host",
        timeout_ns=50_000,
        raise_on_error=False,
    ).sequence
    await master.wait_for_reset()

    result = await master.read_result(0xFFFF_0000, check_response=False)
    if not result.ok:
        assert result.resp in (RESP_DECERR, RESP_SLVERR)
        cocotb.log.info("AXI-Lite negative read resp=0x%x", result.resp)


# ---------------------------------------------------------------------------
# Example 2 — AXI4 single and burst transactions
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_axi4_burst_access(dut):
    """Demonstrate single-beat and burst AXI4 master transactions."""

    cocotb.start_soon(Clock(dut.aclk, 10, units="ns").start())

    master = OcahAxiMasterAgent(
        dut.axi_if,
        name="axi4_host",
        timeout_cycles=1000,
        addr_width=32,
        data_width=32,
    ).sequence
    master.init_signals()
    await master.wait_for_reset()

    # ---------- single write / read ----------
    await master.write(0x0001_0000, 0xCAFE_BABE)
    val = await master.read(0x0001_0000)
    assert val == 0xCAFE_BABE, f"single read mismatch: 0x{val:08X}"

    # ---------- burst write (4 beats, INCR) ----------
    burst_data = [0x1111_1111, 0x2222_2222, 0x3333_3333, 0x4444_4444]
    resp_code = await master.burst_write(0x0002_0000, burst_data)
    assert resp_code == RESP_OKAY

    # ---------- burst read ----------
    recv = await master.burst_read(0x0002_0000, length=4)
    assert recv == burst_data, f"burst read mismatch: {recv}"

    # ---------- response-object conversion ----------
    result = await master.write_result(0x0003_0000, 0xABCD_0000)
    item = result.to_item(protocol="axi4", source="example")
    assert item.ok and item.address == 0x0003_0000

    cocotb.log.info("example_axi4_burst_access PASSED")


# ---------------------------------------------------------------------------
# Example 3 — Memory-backed responder
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_memory_backed_responders(dut):
    """Show AXI-Lite RAM responder construction."""

    cocotb.start_soon(Clock(dut.aclk, 10, units="ns").start())

    axil_ram = OcahAxiLiteSlaveAgent.from_prefix(
        dut,
        "cfg_axil",
        dut.aclk,
        dut.aresetn,
        reset_active_level=False,
        size=2**16,
    ).sequence
    axil_ram.write32(0x10, 0xA5A5_5A5A)
    axil_ram.inject_error(0x20, RESP_DECERR, read=True, write=False)
    axil_ram.inject_error(0x30, RESP_SLVERR, read=True, write=False)

    assert axil_ram.read32(0x10) == 0xA5A5_5A5A


# ---------------------------------------------------------------------------
# Example 4 — Passive monitoring with checkers
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_axi4_monitor_checker(dut):
    """Show how to attach a passive AXI4 monitor and checker."""

    cocotb.start_soon(Clock(dut.aclk, 10, units="ns").start())

    master = OcahAxiMasterAgent(dut.axi_if, name="master").sequence
    master.init_signals()
    await master.wait_for_reset()

    observed_writes = []
    observed_reads = []

    monitor = OcahAxiMonitor(dut.axi_if, dut.aclk, name="passive_mon")
    checker = OcahAxiChecker()
    checker.attach_monitor(monitor)

    def on_write(item):
        observed_writes.append(item)
        cocotb.log.info("[monitor] write addr=0x%08x resp=%s", item.address, item.resp_list)

    def on_read(item):
        observed_reads.append(item)
        cocotb.log.info("[monitor] read addr=0x%08x data=%s", item.address, item.data_words)

    monitor.add_write_callback(on_write)
    monitor.add_read_callback(on_read)
    await monitor.start()

    # Drive some traffic.
    await master.write(0x0000_1000, 0xDEAD_C0DE)
    await master.read(0x0000_1000)
    await Timer(100, units="ns")  # let the monitor dispatch

    await monitor.stop()

    # Verify monitor saw what the master sent.
    assert len(observed_writes) >= 1
    assert len(observed_reads) >= 1
    assert observed_writes[0].address == 0x0000_1000
    checker.assert_clean()

    stats = monitor.get_statistics()
    cocotb.log.info(f"Monitor stats: {stats}")

    cocotb.log.info("example_axi4_monitor_checker PASSED")
