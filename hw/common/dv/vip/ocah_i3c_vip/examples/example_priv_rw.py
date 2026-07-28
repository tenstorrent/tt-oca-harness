# SPDX-License-Identifier: Apache-2.0
# Copyright 2025 Tenstorrent Inc.
"""
example_priv_rw.py — OcahI3cBus and OcahI3cTarget usage examples.

Demonstrates:
  1. SDR private write  (OcahI3cBus.priv_write)
  2. SDR private read   (OcahI3cBus.priv_read)
  3. CCC — RSTDAA and GETSTATUS  (OcahI3cBus.send_ccc)
  4. IBI listen         (OcahI3cBus.ibi_listen)
  5. Passive monitor    (OcahI3cMonitor)

These are NOT stand-alone cocotb tests — they show the API patterns that a
real test would follow.  Copy-paste the relevant block into your test module
and replace ``dut.i3c_scl_*`` / ``dut.i3c_sda_*`` with the actual signal
handles in your testbench.

Assumptions / conventions
--------------------------
- The DUT exposes separate ``*_i`` (input to testbench, output from DUT) and
  ``*_o`` (output from testbench, input to DUT) signals for SCL and SDA.
  This matches the split-signal convention used by cocotbext-i3c.
- The I3C target model (OcahI3cTarget) is used when the DUT contains an I3C
  controller and the testbench needs to emulate target devices.
- The I3C bus host (OcahI3cBus) is used when the DUT contains an I3C target
  or stub and the testbench drives controller traffic.
- All data values are plain Python ints / bytes; no cocotbext_i3c types appear.

Python-path requirement
-----------------------
The wrapper depends on cocotbext_i3c.  Add the checked-in copy to PYTHONPATH
before running::

    export PYTHONPATH=$PYTHONPATH:<repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/src

Or install it::

    pip install <repo>/vendor/chipsalliance/i3c-core/upstream/third_party/cocotbext-i3c/
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer

from ocah_i3c_vip import (
    OcahI3cBus,
    OcahI3cTarget,
    OcahI3cMonitor,
    OcahI3cBusError,
    OcahI3cImportError,
)


# ---------------------------------------------------------------------------
# Example 1 — SDR private write and read-back
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_priv_write_read(dut):
    """
    Issue a private write then a private read to/from an I3C target stub.

    Testbench signal assumptions:
      dut.clk_i        — primary clock (used for reset synchronisation only)
      dut.rst_ni       — active-low reset
      dut.i3c_sda_i    — SDA from DUT perspective (TB reads this)
      dut.i3c_sda_o    — SDA driven by testbench (TB writes this)
      dut.i3c_scl_i    — SCL from DUT perspective
      dut.i3c_scl_o    — SCL driven by testbench

    The DUT here is assumed to be an I3C target stub (Task #6 RTL shim); the
    testbench acts as the I3C controller.
    """

    # 1. Start system clock (100 MHz).
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    # 2. Construct the I3C controller BFM.
    bus = OcahI3cBus(
        sda_i=dut.i3c_sda_i,
        sda_o=dut.i3c_sda_o,
        scl_i=dut.i3c_scl_i,
        scl_o=dut.i3c_scl_o,
        name="i3c_ctrl",
        speed_hz=12.5e6,     # I3C SDR full speed
        timeout_ns=100_000,
        raise_on_nack=True,
    )

    # 3. Drive SCL/SDA to idle state before the first clock edge.
    bus.init_signals()

    # 4. Wait for the DUT reset to deassert.
    await bus.wait_for_reset(dut.rst_ni)

    # 5. Private write: send 4 bytes to target at dynamic address 0x08.
    DYNAMIC_ADDR = 0x08
    write_payload = bytes([0xDE, 0xAD, 0xBE, 0xEF])

    await bus.priv_write(addr=DYNAMIC_ADDR, data=write_payload)
    cocotb.log.info(f"[priv_write] sent {write_payload.hex()} to 0x{DYNAMIC_ADDR:02X}")

    # 6. Private read: receive 4 bytes back from the same target.
    rx = await bus.priv_read(addr=DYNAMIC_ADDR, length=4)
    cocotb.log.info(f"[priv_read]  got  {rx.hex()} from 0x{DYNAMIC_ADDR:02X}")

    assert rx == write_payload, (
        f"priv_read mismatch: expected {write_payload.hex()}, got {rx.hex()}"
    )

    cocotb.log.info("example_priv_write_read PASSED")


# ---------------------------------------------------------------------------
# Example 2 — CCC: RSTDAA broadcast + GETSTATUS directed read
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_ccc_rstdaa_getstatus(dut):
    """
    Issue RSTDAA (broadcast) then GETSTATUS (directed read) to a target.
    """

    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    bus = OcahI3cBus(
        sda_i=dut.i3c_sda_i,
        sda_o=dut.i3c_sda_o,
        scl_i=dut.i3c_scl_i,
        scl_o=dut.i3c_scl_o,
        name="i3c_ctrl",
    )
    bus.init_signals()
    await bus.wait_for_reset(dut.rst_ni)

    # RSTDAA — broadcast, no payload.
    await bus.send_ccc(0x06, broadcast=True)
    cocotb.log.info("[ccc] RSTDAA broadcast sent")

    # GETSTATUS — directed read from target 0x08; payload = [target_addr].
    TARGET_ADDR = 0x08
    status_bytes = await bus.send_ccc(
        0x90,                            # GETSTATUS
        payload=bytes([TARGET_ADDR]),    # directed read — target address
    )
    cocotb.log.info(f"[ccc] GETSTATUS response: {status_bytes.hex()}")

    assert len(status_bytes) == 2, (
        f"GETSTATUS should return 2 bytes, got {len(status_bytes)}"
    )

    cocotb.log.info("example_ccc_rstdaa_getstatus PASSED")


# ---------------------------------------------------------------------------
# Example 3 — IBI listen
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_ibi_listen(dut):
    """
    Register an IBI callback and wait for a target to assert an interrupt.
    """

    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    bus = OcahI3cBus(
        sda_i=dut.i3c_sda_i,
        sda_o=dut.i3c_sda_o,
        scl_i=dut.i3c_scl_i,
        scl_o=dut.i3c_scl_o,
        name="i3c_ctrl",
    )
    bus.init_signals()
    await bus.wait_for_reset(dut.rst_ni)

    # Accumulate IBI records.
    ibi_records = []

    def on_ibi(addr: int, data: bytes) -> None:
        ibi_records.append({"addr": addr, "data": data})
        cocotb.log.info(f"[ibi] addr=0x{addr:02X} data={data.hex()}")

    bus.ibi_listen(on_ibi)

    # The DUT (target stub) is expected to assert an IBI after reset.
    # Wait up to 10 µs for the event.
    await Timer(10_000, "ns")

    # In a real test, assert that at least one IBI was received.
    # Here we just show the pattern.
    cocotb.log.info(f"[ibi] received {len(ibi_records)} IBI event(s)")
    cocotb.log.info("example_ibi_listen PASSED")


# ---------------------------------------------------------------------------
# Example 4 — OcahI3cTarget: emulate a target when DUT is a controller
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_target_model(dut):
    """
    Use OcahI3cTarget to emulate a target device when the DUT is an I3C
    controller (e.g. the SMC cdni3c stub).

    The DUT drives SCL and SDA; the testbench target model responds.
    Signal mapping is reversed compared to examples 1–3.
    """

    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    TARGET_STATIC_ADDR = 0x12

    # Construct the target model.  Note: sda_i/sda_o from the *target's*
    # perspective — i.e. sda_i is what the bus drives in, sda_o is what
    # the target drives out.
    tgt = OcahI3cTarget(
        sda_i=dut.i3c_sda_i,
        sda_o=dut.i3c_sda_o,
        scl_i=dut.i3c_scl_i,
        scl_o=dut.i3c_scl_o,
        name="i3c_target_0",
        static_addr=TARGET_STATIC_ADDR,
    )

    # Pre-load a 4-byte response for the next private read.
    tgt.set_response(bytes([0xCA, 0xFE, 0xBA, 0xBE]))

    # The DUT controller is now free to issue a private read to 0x12.
    # Allow the DUT some time to complete the transaction.
    await Timer(50_000, "ns")

    cocotb.log.info("example_target_model PASSED")


# ---------------------------------------------------------------------------
# Example 5 — Passive monitor alongside a controller
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_passive_monitor(dut):
    """
    Attach a passive monitor and an active controller to the same bus.
    """

    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    bus = OcahI3cBus(
        sda_i=dut.i3c_sda_i,
        sda_o=dut.i3c_sda_o,
        scl_i=dut.i3c_scl_i,
        scl_o=dut.i3c_scl_o,
        name="i3c_ctrl",
    )
    bus.init_signals()
    await bus.wait_for_reset(dut.rst_ni)

    # Attach a passive monitor.  Pass only the *input* handles so the monitor
    # never drives the bus.
    mon = OcahI3cMonitor(
        sda_i=dut.i3c_sda_i,
        scl_i=dut.i3c_scl_i,
        name="i3c_mon",
    )

    events = []
    mon.add_transfer_callback(lambda rec: events.append(rec))
    await mon.start()

    # Drive some traffic.
    await bus.priv_write(addr=0x08, data=bytes([0x11, 0x22]))
    await bus.priv_read(addr=0x08, length=2)

    await Timer(1_000, "ns")  # let the monitor dispatch

    await mon.stop()

    stats = mon.get_statistics()
    cocotb.log.info(f"Monitor stats: {stats}")
    cocotb.log.info(f"Observed {len(events)} bus event(s)")

    cocotb.log.info("example_passive_monitor PASSED")
