# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Tenstorrent Inc.
"""
example_deterministic_entropy.py — OcahEntropySource usage examples.

Demonstrates:
  1. Default deterministic single-word mode (matches trng_core_stub behavior).
  2. Fixed-pattern mode (multiple deterministic words).
  3. Backpressure stress test with reproducible delays.
  4. PRNG mode (opt-in, explicit seed).
  5. IRQ and alarm injection for negative tests.
  6. Passive monitoring with OcahEntropyMonitor.

These are not stand-alone cocotb tests in the strict sense — they show the
API patterns that a real test would follow.  Copy the relevant block into
your test module and replace ``dut`` with the actual testbench handle.

Assumptions
-----------
- Clock: ``dut.clk_i`` at 10 ns (100 MHz).
- DUT has standard SEP AXI-Stream naming::
    ext_trng_axis_req_i_tvalid[0], ext_trng_axis_req_i_tdata[0],
    ext_trng_axis_req_i_tstrb[0], ext_trng_axis_rsp_o_tready[0],
    ext_trng_irq_i, ext_trng_alarm_i
- Alternatively, pass a ``signals`` dict for non-standard naming.
"""

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer, RisingEdge

from ocah_entropy_vip import OcahEntropySource, OcahEntropyMonitor


# ---------------------------------------------------------------------------
# Helper: wait for DUT reset deassertion (adapt to your testbench convention)
# ---------------------------------------------------------------------------

async def _await_reset(dut, cycles: int = 10) -> None:
    """Drive reset low, hold for ``cycles`` edges, then release."""
    dut.rst_ni.value = 0
    for _ in range(cycles):
        await RisingEdge(dut.clk_i)
    dut.rst_ni.value = 1


# ---------------------------------------------------------------------------
# Example 1 — Default deterministic single-word mode
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_deterministic_default(dut):
    """Default mode: emits 0xDEAD_BEEF once then stalls.

    This mirrors the Task #12 trng_core_stub behavior.  The same word is
    produced on every run with no plusarg needed.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    src = OcahEntropySource(
        dut.clk_i,
        dut=dut,
        name="entropy_default",
    )
    mon = OcahEntropyMonitor(
        dut.clk_i,
        dut=dut,
        name="entropy_mon",
    )

    # Initialise signals before any clock edge to avoid X-propagation.
    src.init_signals()

    await _await_reset(dut)

    await src.start()
    await mon.start()

    # Wait enough time for the DUT to consume the single entropy word.
    await Timer(200, units="ns")

    await src.stop()
    await mon.stop()

    stats = mon.get_statistics()
    words = mon.get_words()
    cocotb.log.info(f"Monitor stats: {stats}")

    # The default deterministic word must appear at least once.
    assert 0xDEAD_BEEF in words, (
        f"Expected 0xDEAD_BEEF in consumed words; got {[hex(w) for w in words]}"
    )
    # After the single word, no further transfers should occur.
    assert stats["handshakes"] <= 1, (
        f"Expected at most 1 handshake in single-word mode; got {stats['handshakes']}"
    )
    cocotb.log.info("example_deterministic_default PASSED")


# ---------------------------------------------------------------------------
# Example 2 — Fixed-pattern mode (multiple deterministic words)
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_fixed_pattern(dut):
    """Deliver an explicit list of entropy words in order, then stall."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    src = OcahEntropySource(dut.clk_i, dut=dut, name="entropy_pattern")
    mon = OcahEntropyMonitor(dut.clk_i, dut=dut, name="entropy_mon")

    PATTERN = [0xAAAA_AAAA, 0x5555_5555, 0x1234_5678, 0xDEAD_C0DE]

    src.init_signals()
    src.set_pattern(PATTERN)  # call before start()

    await _await_reset(dut)
    await src.start()
    await mon.start()

    # Allow time for the DUT to consume all 4 words.
    await Timer(500, units="ns")

    await src.stop()
    await mon.stop()

    words = mon.get_words()
    cocotb.log.info(f"Consumed words: {[hex(w) for w in words]}")

    # Verify all pattern words were received in order.
    for expected, actual in zip(PATTERN, words):
        assert actual == expected, (
            f"Pattern mismatch: expected 0x{expected:08X}, got 0x{actual:08X}"
        )
    # After the pattern, the BFM should stall.
    assert len(words) == len(PATTERN), (
        f"Expected exactly {len(PATTERN)} words; got {len(words)}"
    )
    cocotb.log.info("example_fixed_pattern PASSED")


# ---------------------------------------------------------------------------
# Example 3 — Backpressure stress test (reproducible)
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_backpressure(dut):
    """Drive entropy with 50% backpressure; count must still reach target.

    Backpressure uses a fixed seed so the stall pattern is reproducible.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    src = OcahEntropySource(dut.clk_i, dut=dut, name="entropy_bp")
    mon = OcahEntropyMonitor(dut.clk_i, dut=dut, name="entropy_mon_bp")

    WORDS = [0xCAFE_BABE, 0xBEEF_CAFE, 0xFEED_FACE]

    src.init_signals()
    src.set_pattern(WORDS)
    src.set_backpressure(0.5)   # 50% stall probability, deterministic seed=0

    await _await_reset(dut)
    await src.start()
    await mon.start()

    # Allow extra time for backpressure delays (worst case ~2x normal).
    await Timer(1000, units="ns")

    await src.stop()
    await mon.stop()

    stats = mon.get_statistics()
    cocotb.log.info(
        f"Backpressure: handshakes={stats['handshakes']}, "
        f"bp_cycles={stats['backpressure_cycles']}"
    )

    words = mon.get_words()
    for expected, actual in zip(WORDS, words):
        assert actual == expected, (
            f"Backpressure test: expected 0x{expected:08X}, got 0x{actual:08X}"
        )
    assert stats["backpressure_cycles"] > 0, (
        "Expected at least one backpressure stall cycle at 50% probability"
    )
    cocotb.log.info("example_backpressure PASSED")


# ---------------------------------------------------------------------------
# Example 4 — PRNG mode (opt-in, explicit seed)
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_prng_mode(dut):
    """Opt-in random mode: same seed produces the same sequence every run."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    SEED = 0xC0FFEE42   # fixed; choose any non-zero int

    src = OcahEntropySource(dut.clk_i, dut=dut, name="entropy_prng")
    mon = OcahEntropyMonitor(dut.clk_i, dut=dut, name="entropy_mon_prng")

    src.init_signals()
    src.enable_random(seed=SEED)   # explicit opt-in; time-of-day seeds are forbidden

    await _await_reset(dut)
    await src.start()
    await mon.start()

    # Let the DUT consume some entropy words.
    await Timer(500, units="ns")

    await src.stop()
    await mon.stop()

    stats = mon.get_statistics()
    cocotb.log.info(
        f"PRNG mode: {stats['handshakes']} handshakes, "
        f"first word: 0x{mon.get_words()[0]:08X}" if mon.get_words() else ""
    )
    assert stats["handshakes"] > 0, "No entropy words were consumed in PRNG mode"
    cocotb.log.info("example_prng_mode PASSED")


# ---------------------------------------------------------------------------
# Example 5 — IRQ and alarm injection
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_irq_alarm_injection(dut):
    """Inject IRQ and alarm sideband signals; monitor records the events."""
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    src = OcahEntropySource(dut.clk_i, dut=dut, name="entropy_fault")
    mon = OcahEntropyMonitor(dut.clk_i, dut=dut, name="entropy_mon_fault")

    src.init_signals()

    await _await_reset(dut)
    await src.start()
    await mon.start()

    # Allow the DUT to start up.
    await Timer(100, units="ns")

    # Inject a 3-cycle IRQ pulse.
    await src.inject_irq(duration_cycles=3)
    cocotb.log.info("IRQ pulse injected")

    # Wait a few cycles, then inject a 1-cycle alarm.
    await Timer(50, units="ns")
    await src.inject_alarm(duration_cycles=1)
    cocotb.log.info("Alarm pulse injected")

    # Allow the DUT to respond.
    await Timer(100, units="ns")

    await src.stop()
    await mon.stop()

    irq_events   = mon.get_irq_events()
    alarm_events = mon.get_alarm_events()
    stats        = mon.get_statistics()

    cocotb.log.info(f"IRQ events:   {irq_events}")
    cocotb.log.info(f"Alarm events: {alarm_events}")
    cocotb.log.info(f"Stats: {stats}")

    # Check that the monitor recorded the rising edge events.
    irq_rises   = [e for e in irq_events   if e["level"] == 1]
    alarm_rises = [e for e in alarm_events if e["level"] == 1]

    assert len(irq_rises) >= 1, (
        f"Expected at least 1 IRQ assertion; got {len(irq_rises)}"
    )
    assert len(alarm_rises) >= 1, (
        f"Expected at least 1 alarm assertion; got {len(alarm_rises)}"
    )
    assert stats["irq_assertions"]   >= 1
    assert stats["alarm_assertions"] >= 1
    cocotb.log.info("example_irq_alarm_injection PASSED")


# ---------------------------------------------------------------------------
# Example 6 — non-standard signal names via signals dict
# ---------------------------------------------------------------------------

@cocotb.test()
async def example_custom_signal_names(dut):
    """Use the ``signals`` dict API when DUT wires use non-standard names.

    Replace the ``dut.<name>`` handles below with the actual signal handles
    in your testbench.
    """
    cocotb.start_soon(Clock(dut.clk_i, 10, units="ns").start())

    # Build an explicit signal map.  All six keys are required.
    sig_map = {
        "tvalid": dut.ext_trng_axis_req_i_tvalid[0],
        "tdata":  dut.ext_trng_axis_req_i_tdata[0],
        "tstrb":  dut.ext_trng_axis_req_i_tstrb[0],
        "tready": dut.ext_trng_axis_rsp_o_tready[0],
        "irq":    dut.ext_trng_irq_i,
        "alarm":  dut.ext_trng_alarm_i,
    }

    src = OcahEntropySource(dut.clk_i, signals=sig_map, name="entropy_custom")
    mon = OcahEntropyMonitor(dut.clk_i, signals=sig_map, name="entropy_mon_custom")

    src.init_signals()
    await _await_reset(dut)
    await src.start()
    await mon.start()

    await Timer(200, units="ns")

    await src.stop()
    await mon.stop()

    cocotb.log.info(f"Custom signals: {mon.get_statistics()}")
    cocotb.log.info("example_custom_signal_names PASSED")
