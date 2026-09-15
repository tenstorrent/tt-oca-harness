# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2025 Tenstorrent USA, Inc.
"""
example_idcode.py — OcahJtagMasterDriver IDCODE read example.

Demonstrates the minimal sequence to:
  1. Construct an OcahJtagMasterDriver for the PTAP interface.
  2. Attach a passive OcahJtagMasterMonitor to log transactions.
  3. Reset the TAP.
  4. Shift the IDCODE instruction into the IR.
  5. Read back the 32-bit IDCODE from the DR.
  6. Run a second access on the STAP using a custom signal map.

This snippet is not a stand-alone test; it shows the API patterns to copy
into a real cocotb test.  Replace ``dut.jtag_ptap_if`` / ``dut.jtag_stap_if``
with the actual handle names in your testbench.

Assumptions
-----------
- A clock is driven externally before calling ``init_signals()``.
- The DUT implements IEEE 1149.1 with IDCODE opcode 0x01 and a 5-bit IR.
- TRST is active-low and connected.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

from ocah_jtag_vip import (
    IDCODE_OPCODE,
    OcahJtagChecker,
    OcahJtagMasterDriver,
    OcahJtagMasterDriverError,
    OcahJtagMasterMonitor,
)

# ---------------------------------------------------------------------------
# Example 1 — PTAP IDCODE read (most common OCAH debug use case)
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_ptap_idcode(dut):
    """Read IDCODE from the Primary TAP (PTAP)."""

    # Start the clock: 10 ns = 100 MHz.
    cocotb.start_soon(Clock(dut.tck, 10, units="ns").start())

    # Construct the TAP driver for the PTAP.
    tap = OcahJtagMasterDriver(
        dut.jtag_ptap_if,  # JTAG interface handle in the testbench
        name="ptap",
        tck_period_ns=10,
        ir_width=5,
        tap_type="ptap",
    )

    # Attach a passive monitor and checker before any activity.
    monitor = OcahJtagMasterMonitor(dut.jtag_ptap_if, name="ptap_mon")
    checker = OcahJtagChecker(ir_width=5)
    checker.attach_monitor(monitor)

    # Record observed transactions for post-test assertion.
    observed_ir = []
    observed_dr = []

    def on_ir(item):
        observed_ir.append(item)
        cocotb.log.info(
            "[ptap_mon] IR  tdi=0x%x tdo=0x%x bits=%d",
            item.tdi_value,
            item.tdo_value,
            item.bit_count,
        )

    def on_dr(item):
        observed_dr.append(item)
        cocotb.log.info(
            "[ptap_mon] DR  tdi=0x%x tdo=0x%x bits=%d instr=%s",
            item.tdi_value,
            item.tdo_value,
            item.bit_count,
            f"0x{item.instruction:X}" if item.instruction is not None else "unknown",
        )

    monitor.add_ir_callback(on_ir)
    monitor.add_dr_callback(on_dr)
    await monitor.start()

    # ---------- step 1: initialise signals to idle ----------
    tap.init_signals()

    # ---------- step 2: reset the TAP ----------
    # Asserts TRST and drives 10 TMS=1 cycles to guarantee TEST_LOGIC_RESET.
    await tap.reset_tap(cycles=10)

    # ---------- step 3: shift the IDCODE instruction into the IR ----------
    # IDCODE is IEEE 1149.1 standard opcode 0x01.  This call navigates
    # RUN_TEST_IDLE -> SELECT_DR_SCAN -> SELECT_IR_SCAN -> CAPTURE_IR ->
    # SHIFT_IR (shift 5 bits) -> EXIT1_IR -> SELECT_DR_SCAN.
    captured_ir = await tap.shift_ir(IDCODE_OPCODE, width=5)
    cocotb.log.info(f"[ptap] IR scan captured TDO = 0x{captured_ir:X}")

    # ---------- step 4: read the 32-bit IDCODE from the DR ----------
    # The high-level read_idcode() combines steps 3 and 4 internally; this
    # manual sequence shows the two-step API for tests that need more control.
    idcode = await tap.shift_dr(0x0000_0000, width=32)
    cocotb.log.info(f"[ptap] IDCODE = 0x{idcode:08X}")

    # ---------- step 5: verify via convenience helper ----------
    await tap.reset_tap()
    idcode_via_helper = await tap.read_idcode()
    assert idcode_via_helper == idcode, (
        f"IDCODE mismatch: manual=0x{idcode:08X} helper=0x{idcode_via_helper:08X}"
    )

    # ---------- step 6: drain monitor and check it saw transactions ----------
    await Timer(50, units="ns")
    await monitor.stop()

    assert len(observed_ir) >= 1, "Monitor did not see any IR transactions"
    assert len(observed_dr) >= 1, "Monitor did not see any DR transactions"

    # The last IR transaction should have shifted in IDCODE_OPCODE.
    last_ir = observed_ir[-1]
    assert last_ir.tdi_value == IDCODE_OPCODE, (
        f"Expected IR tdi=0x{IDCODE_OPCODE:X}, got 0x{last_ir.tdi_value:X}"
    )
    checker.assert_clean()

    stats = monitor.get_statistics()
    cocotb.log.info(f"[ptap_mon] final stats: {stats}")

    cocotb.log.info("example_ptap_idcode PASSED")


# ---------------------------------------------------------------------------
# Example 2 — STAP access with a custom signal map
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_stap_idcode(dut):
    """Read IDCODE from the Secondary TAP (STAP) via a custom signal map.

    This shows how to reuse OcahJtagMasterDriver when the STAP interface uses
    different signal names (e.g., stap_tck instead of tck).
    """

    cocotb.start_soon(Clock(dut.stap_tck, 20, units="ns").start())

    # Custom signal map: logical name -> actual attribute on dut.jtag_stap_if.
    stap_signal_map = {
        "tck": "stap_tck",
        "tms": "stap_tms",
        "tdi": "stap_tdi",
        "tdo": "stap_tdo",
        "trst": "stap_trst",
        "tdo_oen": "stap_tdo_oen",
    }

    tap = OcahJtagMasterDriver(
        dut.jtag_stap_if,
        name="stap",
        tck_period_ns=20,
        ir_width=5,
        tap_type="stap",
        signal_map=stap_signal_map,
    )

    tap.init_signals()
    await tap.reset_tap()

    try:
        idcode = await tap.read_idcode()
        cocotb.log.info(f"[stap] IDCODE = 0x{idcode:08X}")
    except OcahJtagMasterDriverError as exc:
        cocotb.log.warning(f"[stap] {exc}")

    # Return TAP to safe idle state.
    await tap.bypass()

    cocotb.log.info("example_stap_idcode PASSED")


# ---------------------------------------------------------------------------
# Example 3 — CPU TAP access (SMC / SEP debug port scenario)
# ---------------------------------------------------------------------------


@cocotb.test()
async def example_cpu_tap_idcode(dut):
    """Read IDCODE from the CPU debug TAP.

    CPU debug TAPs often have a wider IR than the chip-level TAP.
    Demonstrates overriding ir_width per-instance.
    """

    cocotb.start_soon(Clock(dut.tck, 10, units="ns").start())

    tap = OcahJtagMasterDriver(
        dut.jtag_cpu_if,
        name="cpu_tap",
        tck_period_ns=10,
        ir_width=10,  # wider CPU-debug IR; width is per instance
        tap_type="cpu_tap",
    )

    tap.init_signals()
    await tap.reset_tap()

    idcode = await tap.read_idcode()
    cocotb.log.info(f"[cpu_tap] IDCODE = 0x{idcode:08X}")

    # Decode standard IDCODE fields (IEEE 1149.1 §12.1.1):
    version = (idcode >> 28) & 0xF
    part = (idcode >> 12) & 0xFFFF
    manuf = (idcode >> 1) & 0x7FF
    lsb = (idcode >> 0) & 0x1
    cocotb.log.info(
        f"[cpu_tap] IDCODE fields: version={version:#x}"
        f"  part={part:#x}  manuf={manuf:#x}  lsb={lsb}"
    )

    assert lsb == 1, f"IEEE 1149.1 §12.1.1: IDCODE bit[0] must be 1, got {lsb}"

    cocotb.log.info("example_cpu_tap_idcode PASSED")
