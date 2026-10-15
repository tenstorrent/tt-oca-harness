# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: the monitor grades the controller pins in all four SPI modes.

``CHK-SPI-WIRE-LEGAL``: in each of the four modes the controller sends legal
READ frames with a seeded address; the monitor records no violation and
decodes all 32 bits it was sent (command byte and address), so it samples on
the mode's sample edge; no violation is recorded on the bus between frames
either. Two hand-driven frames
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
* ``CHK-SPI-WIRE-XZ``: MOSI is X at a sample edge, and MOSI is X between a
  shift edge and the next sample edge and resolves before that sample edge.
  A 2-state simulator cannot hold X, so the legs run on a 4-state simulator
  only.

``CHK-SPI-MON-WHOLE-BYTES``: a PAGE PROGRAM frame that ends three bits into
its second payload byte reports the one complete payload byte as data, and
its ``bit_count`` keeps the three extra bits. ``CHK-SPI-MON-RX-XZ`` (4-state
simulator only): a READ STATUS REGISTER 1 frame whose response bit is X has
that response byte in ``data_miso_xz``.

``CHK-SPI-WIRE-STOP``: ``stop()`` raises ``OcahSpiMonitorError`` after the
violations. The flash model is stopped before any frame: it answers Mode 0
only and is not graded here.
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
from ocah_spi_vip import OcahSpiMonitorError, OcahSpiOpcode
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
    "CHK-SPI-MON-WHOLE-BYTES",
) + (("CHK-SPI-WIRE-XZ", "CHK-SPI-MON-RX-XZ") if FOUR_STATE else ())

MODES = ((0, 0), (0, 1), (1, 0), (1, 1))


def _miso_value(handle: Any, value: Any) -> Any:
    """``value`` as the handle takes it; ``"x"`` becomes a one-bit logic value."""
    if not isinstance(value, str):
        return value
    try:
        from cocotb.types import Logic  # cocotb 2.x

        return Logic(value)
    except ImportError:  # cocotb 1.x
        from cocotb.binary import BinaryValue

        return BinaryValue(value, n_bits=len(handle))


@cocotb.test()
async def ocah_spi_wire_check_test(dut) -> None:
    rng = scenario_rng("wire_check")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    await harness.flash.stop(require_closed=True)
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
    legal: list[tuple[str, list[tuple[Any, ...]], list[tuple[Any, ...]]]] = []
    for cpol, cpha in MODES:
        set_mode(cpol, cpha)
        await bfm.drive(hold_ns=2 * bfm.half_period_ns)
        for _ in range(2):
            addr = rng.randrange(1 << 24)
            frame = bytes([OcahSpiOpcode.READ]) + addr.to_bytes(3, "big")
            bits = [(byte >> i) & 1 for byte in frame for i in range(7, -1, -1)]
            before = len(monitor.get_transactions())
            await bfm.raw_frame(bits)
            txns = monitor.get_transactions()[before:]
            log.info("legal mode=%d%d frame=%s frames=%s", cpol, cpha, frame.hex(), txns)
            observed = [
                (t["bit_count"], t["opcode"], t["addr"], t["wire_errors"], t["cpol"], t["cpha"])
                for t in txns
            ]
            expected = [(32, int(OcahSpiOpcode.READ), addr, (), cpol, cpha)]
            legal.append((f"mode{cpol}{cpha}", observed, expected))
    # Every violation since start counts, including one on the idle bus
    # between frames, which no frame record carries.
    checker.expect_equal(
        "CHK-SPI-WIRE-LEGAL",
        ([(name, got) for name, got, _ in legal], monitor.get_wire_errors()),
        ([(name, want) for name, _, want in legal], []),
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

    async def program_tail() -> None:
        set_mode(0, 0)
        await bfm.drive(hold_ns=2 * half)
        frame = bytes([OcahSpiOpcode.PAGE_PROGRAM]) + (0x12345).to_bytes(3, "big") + b"\xa5"
        bits = [(byte >> i) & 1 for byte in frame for i in range(7, -1, -1)]
        await bfm.raw_frame(bits + [1, 0, 1])

    mark = len(monitor.get_transactions())
    await leg("CHK-SPI-WIRE-LEGAL", [], program_tail, context="mode=00 program_tail")
    tail = monitor.get_transactions()[mark:]
    checker.expect_equal(
        "CHK-SPI-MON-WHOLE-BYTES",
        [(t["opcode"], t["addr"], t["data_mosi"], t["bit_count"]) for t in tail],
        [(int(OcahSpiOpcode.PAGE_PROGRAM), 0x12345, b"\xa5", 43)],
        context="PAGE PROGRAM with one payload byte and three tail bits",
    )

    if FOUR_STATE:

        async def mosi_x() -> None:
            set_mode(0, 0)
            await bfm.drive(hold_ns=2 * half)
            await bfm.drive(cs_n=0, mosi="x")
            await bfm.drive(sclk=1)  # sample edge with MOSI at X
            await bfm.drive(sclk=0, mosi=0)
            await bfm.drive(cs_n=1)

        await leg("CHK-SPI-WIRE-XZ", ["xz"], mosi_x, context="mode=00 mosi=X")

        async def mosi_x_between_edges() -> None:
            set_mode(0, 0)
            await bfm.drive(hold_ns=2 * half)
            await bfm.drive(cs_n=0, mosi=1)
            await bfm.drive(sclk=1)  # sample edge with MOSI at 1
            await bfm.drive(sclk=0, hold_ns=half // 4)  # shift edge
            await bfm.drive(mosi="x", hold_ns=half // 4)  # X inside the shift half period
            await bfm.drive(mosi=0, hold_ns=half - 2 * (half // 4))  # resolves before sampling
            await bfm.drive(sclk=1)  # sample edge with MOSI at 0
            await bfm.drive(sclk=0)
            await bfm.drive(cs_n=1)

        await leg(
            "CHK-SPI-WIRE-XZ",
            ["xz"],
            mosi_x_between_edges,
            context="mode=00 mosi=X between a shift and a sample edge",
        )

        async def status_rx_x() -> None:
            set_mode(0, 0)
            await bfm.drive(hold_ns=2 * half)
            await bfm.drive(cs_n=0)
            response = [1, 0, "x", 1, 0, 1, 1, 0]
            for i, bit in enumerate(
                [(int(OcahSpiOpcode.READ_SR1) >> k) & 1 for k in range(7, -1, -1)] + [0] * 8
            ):
                miso = response[i - 8] if i >= 8 else 0
                dut.spi_miso.value = _miso_value(dut.spi_miso, miso)
                await bfm.drive(mosi=bit)
                await bfm.drive(sclk=1)
                await bfm.drive(sclk=0)
            await bfm.drive(cs_n=1)
            dut.spi_miso.value = 0

        mark = len(monitor.get_transactions())
        await leg("CHK-SPI-WIRE-LEGAL", [], status_rx_x, context="mode=00 status_rx_x")
        rx = monitor.get_transactions()[mark:]
        checker.expect_equal(
            "CHK-SPI-MON-RX-XZ",
            [(t["opcode"], len(t["data_miso"]), t["data_miso_xz"]) for t in rx],
            [(int(OcahSpiOpcode.READ_SR1), 1, (0,))],
            context="READ STATUS REGISTER 1 with response bit 5 at X",
        )
    else:
        log.info("OBS-SPI-WIRE-XZ graded=0 reason=2-state simulator holds no X")

    errors = monitor.get_wire_errors()
    total = len(errors)
    expected_stop = f"{monitor.name}: {total} wire-check violation(s); first: {errors[0]}"
    stop_error: BaseException | None = None
    try:
        await monitor.stop()
    except OcahSpiMonitorError as exc:
        stop_error = exc
    checker.expect_true(
        "CHK-SPI-WIRE-STOP",
        stop_error is not None and str(stop_error) == expected_stop,
        context=f"violations={total} stop() raised {stop_error!r}",
    )
    checker.finalize()
