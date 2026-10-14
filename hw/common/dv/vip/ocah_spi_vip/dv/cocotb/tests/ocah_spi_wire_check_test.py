# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: the monitor grades the controller pins in all four SPI modes.

``CHK-SPI-WIRE-LEGAL``: in each of the four modes the controller sends legal
frames of seeded bits; the monitor records no violation and decodes the bits
it was sent, so it samples on the mode's sample edge. Two hand-driven frames
are legal too: MOSI changes half way through the half period that starts at a
shift edge (Mode 0), and MOSI changes in a held gap after a sample edge before
the next segment (Mode 1).

Each violation leg drives the pins directly and must give exactly the named
violation, and no other:

* ``CHK-SPI-WIRE-IDLE-FALL``: chip-select falls with SCK off its CPOL level
  (CPOL 1, SCK low).
* ``CHK-SPI-WIRE-IDLE-RISE``: chip-select rises with SCK off its CPOL level
  (Mode 0 with SCK high, Mode 3 with SCK low).
* ``CHK-SPI-WIRE-MOSI-EDGE``: MOSI changes on the sample edge (CPHA 0 and
  CPHA 1), and MOSI changes after a sample edge and before the next shift
  edge of the running clock.
* ``CHK-SPI-WIRE-SCK-IDLE``: SCK leaves the CPOL level while chip-select is
  high.
* ``CHK-SPI-WIRE-XZ``: MOSI is X at a sample edge. A 2-state simulator
  cannot hold X, so the leg runs on a 4-state simulator only.

``CHK-SPI-WIRE-STOP``: ``stop()`` raises ``OcahSpiMonitorError`` after the
violations. The flash model answers Mode 0 only; its records are not graded
here.
"""

from __future__ import annotations

import logging

import cocotb
from ocah_spi_vip import OcahSpiMonitorError
from ocah_spi_vip_harness import build_stack, scenario_rng

log = logging.getLogger("cocotb.tb.ocah_spi_wire_check_test")

FOUR_STATE = "verilator" not in str(getattr(cocotb, "SIM_NAME", "") or "").lower()

REQUIRED_IDS = (
    "CHK-SPI-WIRE-LEGAL",
    "CHK-SPI-WIRE-IDLE-FALL",
    "CHK-SPI-WIRE-IDLE-RISE",
    "CHK-SPI-WIRE-MOSI-EDGE",
    "CHK-SPI-WIRE-SCK-IDLE",
    "CHK-SPI-WIRE-STOP",
) + (("CHK-SPI-WIRE-XZ",) if FOUR_STATE else ())

MODES = ((0, 0), (0, 1), (1, 0), (1, 1))


@cocotb.test()
async def ocah_spi_wire_check_test(dut) -> None:
    rng = scenario_rng("wire_check")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    bfm, monitor, checker = harness.host.bfm, harness.monitor, harness.checker
    log.info("start: four_state=%s", FOUR_STATE)

    def set_mode(cpol: int, cpha: int) -> None:
        monitor.set_mode(cpol, cpha)
        bfm.set_mode(cpol, cpha)

    async def leg(check_id: str, expected: list[str], body, *, context: str) -> None:
        """Run ``body``; the violations it adds must be exactly ``expected``, in order."""
        before = len(monitor.get_wire_errors())
        await body()
        await bfm.drive(hold_ns=3 * bfm.half_period_ns)
        added = [line.split(":", 1)[0] for line in monitor.get_wire_errors()[before:]]
        log.info("%s %s violations=%s", check_id, context, monitor.get_wire_errors()[before:])
        checker.expect_equal(check_id, added, expected, context=context)

    # Legal frames in every mode.
    legal = []
    for cpol, cpha in MODES:
        set_mode(cpol, cpha)
        await bfm.drive(hold_ns=2 * bfm.half_period_ns)
        for _ in range(2):
            value = rng.randrange(1 << 16)
            bits = [(value >> i) & 1 for i in range(15, -1, -1)]
            before = len(monitor.get_transactions())
            await bfm.raw_frame(bits)
            txns = monitor.get_transactions()[before:]
            legal.append(
                (
                    f"mode{cpol}{cpha}",
                    [
                        (t["bit_count"], t["opcode"], t["wire_errors"], t["cpol"], t["cpha"])
                        for t in txns
                    ],
                )
            )
            log.info("legal mode=%d%d bits=0x%04x frames=%s", cpol, cpha, value, txns)
            expected_txn = [(16, value >> 8, (), cpol, cpha)]
            legal[-1] = (legal[-1][0], legal[-1][1], expected_txn)
    checker.expect_equal(
        "CHK-SPI-WIRE-LEGAL",
        [(name, got) for name, got, _ in legal],
        [(name, want) for name, _, want in legal],
        context=f"frames={len(legal)} violations_total={len(monitor.get_wire_errors())}",
    )

    half = bfm.half_period_ns

    async def idle_fall() -> None:
        set_mode(1, 1)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(cs_n=0, sclk=0)  # chip-select falls with SCK at the active level
        await bfm.drive(sclk=1)  # back to idle: a sample edge in Mode 3
        await bfm.drive(cs_n=1)

    await leg("CHK-SPI-WIRE-IDLE-FALL", ["idle_at_cs_fall"], idle_fall, context="mode=11")

    async def idle_rise_mode0() -> None:
        set_mode(0, 0)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(cs_n=0, mosi=1)
        await bfm.drive(sclk=1)
        await bfm.drive(cs_n=1)  # chip-select rises with SCK high
        await bfm.drive(sclk=0)  # SCK returns to idle with chip-select high: legal

    async def idle_rise_mode3() -> None:
        set_mode(1, 1)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(cs_n=0)
        await bfm.drive(sclk=0, mosi=1)
        await bfm.drive(cs_n=1)  # chip-select rises with SCK low
        await bfm.drive(sclk=1)

    await leg("CHK-SPI-WIRE-IDLE-RISE", ["idle_at_cs_rise"], idle_rise_mode0, context="mode=00")
    await leg("CHK-SPI-WIRE-IDLE-RISE", ["idle_at_cs_rise"], idle_rise_mode3, context="mode=11")

    async def mosi_at_sample_cpha0() -> None:
        set_mode(0, 0)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(cs_n=0, mosi=1)
        await bfm.drive(sclk=1, mosi=0)  # MOSI changes on the sample edge
        await bfm.drive(sclk=0)
        await bfm.drive(cs_n=1)

    async def mosi_at_sample_cpha1() -> None:
        set_mode(0, 1)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(cs_n=0)
        await bfm.drive(sclk=1, mosi=1)  # shift edge: legal
        await bfm.drive(sclk=0, mosi=0)  # MOSI changes on the sample edge
        await bfm.drive(cs_n=1)

    async def mosi_after_sample() -> None:
        set_mode(0, 0)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(cs_n=0, mosi=1)
        await bfm.drive(sclk=1)
        await bfm.drive(sclk=0)
        await bfm.drive(sclk=1, hold_ns=half // 2)  # sample edge of the second bit
        await bfm.drive(mosi=0, hold_ns=half - half // 2)  # before the shift edge
        await bfm.drive(sclk=0)  # the shift edge on the running clock confirms it
        await bfm.drive(cs_n=1)

    async def legal_timing() -> None:
        set_mode(0, 0)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(cs_n=0, mosi=1)
        await bfm.drive(sclk=1)
        await bfm.drive(sclk=0, hold_ns=half // 2)  # shift edge
        await bfm.drive(mosi=0, hold_ns=half - half // 2)  # within the shift half period
        await bfm.drive(sclk=1)
        await bfm.drive(sclk=0)
        await bfm.drive(cs_n=1)
        set_mode(0, 1)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(cs_n=0)
        await bfm.drive(sclk=1, mosi=1)
        await bfm.drive(sclk=0, hold_ns=5 * half)  # sample edge, then a held gap
        await bfm.drive(mosi=0, hold_ns=5 * half)  # change in the gap
        await bfm.drive(sclk=1, mosi=1)  # the next segment's shift edge
        await bfm.drive(sclk=0)
        await bfm.drive(cs_n=1)

    await leg(
        "CHK-SPI-WIRE-MOSI-EDGE", ["mosi_edge"], mosi_at_sample_cpha0, context="mode=00 at_sample"
    )
    await leg(
        "CHK-SPI-WIRE-MOSI-EDGE", ["mosi_edge"], mosi_at_sample_cpha1, context="mode=01 at_sample"
    )
    await leg(
        "CHK-SPI-WIRE-MOSI-EDGE", ["mosi_edge"], mosi_after_sample, context="mode=00 after_sample"
    )
    await leg("CHK-SPI-WIRE-LEGAL", [], legal_timing, context="mode=00 shift_half mode=01 held_gap")

    async def sck_while_idle() -> None:
        set_mode(0, 0)
        await bfm.drive(hold_ns=2 * half)
        await bfm.drive(sclk=1)  # leaves CPOL with chip-select high
        await bfm.drive(sclk=0)  # returns to CPOL: legal

    await leg("CHK-SPI-WIRE-SCK-IDLE", ["sck_while_idle"], sck_while_idle, context="mode=00")

    if FOUR_STATE:

        async def mosi_x() -> None:
            set_mode(0, 0)
            await bfm.drive(hold_ns=2 * half)
            await bfm.drive(cs_n=0, mosi="x")
            await bfm.drive(sclk=1)  # sample edge with MOSI at X
            await bfm.drive(sclk=0, mosi=0)
            await bfm.drive(cs_n=1)

        await leg("CHK-SPI-WIRE-XZ", ["xz"], mosi_x, context="mode=00 mosi=X")
    else:
        log.info("OBS-SPI-WIRE-XZ graded=0 reason=2-state simulator holds no X")

    total = len(monitor.get_wire_errors())
    stop_error: BaseException | None = None
    try:
        await monitor.stop()
    except OcahSpiMonitorError as exc:
        stop_error = exc
    checker.expect_true(
        "CHK-SPI-WIRE-STOP",
        stop_error is not None and str(total) in str(stop_error),
        context=f"violations={total} stop() raised {stop_error!r}",
    )
    await harness.flash.stop()
    checker.finalize()
