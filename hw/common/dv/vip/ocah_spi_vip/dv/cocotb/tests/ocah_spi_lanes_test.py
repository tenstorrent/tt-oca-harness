# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: dual and quad data on four lanes, and the output-enable checks.

On the four-lane link the controller enables writes, programs a seeded page
with QUAD PAGE PROGRAM (single-lane command and address, four-lane payload),
then reads it back with READ, DUAL OUTPUT READ, QUAD OUTPUT READ, DUAL I/O
READ and QUAD I/O READ:

* ``CHK-SPI-LANE-PROGRAM``: the device record holds the payload, the
  monitor's four-lane decode of the payload phase equals it, and the monitor
  record carries the address and the payload.
* ``CHK-SPI-LANE-READ``: every read returns the payload to the controller, the
  device record's ``data_out`` equals it, and the monitor's lane decode of the
  response phase equals it, each at the command's lane width; the monitor
  record carries the address and the response.
* ``CHK-SPI-LANE-JEDEC``: READ JEDEC ID answers on lane 1 in standard mode.
* ``CHK-SPI-LANE-REFUSE``: a quad program ending one nibble into a payload byte is refused as
  ``partial_byte``, a quad I/O read ending in its four-lane address as
  ``partial_address`` and in its dummy clocks as ``partial_dummy``; memory and
  the latch are unchanged.
* ``CHK-SPI-LANE-OE``: the legal frames give no output-enable violation; a
  single-lane frame that enables lane 1 instead of lane 0 gives exactly
  ``oe_lanes`` and ``oe_data``, a lane enable raised with chip select high
  gives exactly ``oe_idle``, a lane enable still on when chip select rises
  gives exactly ``oe_idle``, a frame with the chip-select enable low gives
  ``oe_ctrl``, a WRITE ENABLE shifted on lane 0 with its output enable off
  gives exactly ``oe_data``, and (4-state simulator only) a lane 0 change on
  a sample edge while a disabled lane holds X gives exactly ``mosi_edge``;
  ``stop()`` then
  raises. A single-lane ``transfer()`` on the four-lane link turns its lane
  enable off before chip select rises, so it adds no violation.

The checker replays the accepted frames (``CHK-SPI-READ-DATA``,
``CHK-SPI-FRAME-SHAPE``, ``CHK-SPI-MEM-GOLDEN``) and ``CHK-SPI-LEDGER``
matches the device records against the monitor frames in input clocks.
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
from ocah_spi_vip import (
    FRAME_SHAPE_REASONS,
    OcahSpiMonitorError,
    OcahSpiOpcode,
    command_format,
    lanes_to_bytes,
)
from ocah_spi_vip_harness import JEDEC_ID, build_lane_stack, random_page_span, scenario_rng

log = logging.getLogger("cocotb.tb.ocah_spi_lanes_test")

FOUR_STATE = "verilator" not in str(getattr(cocotb, "SIM_NAME", "") or "").lower()


def _lanes_value(handle: Any, text: str) -> Any:
    """A four-lane value with X/Z bits, most significant lane first."""
    try:
        from cocotb.types import LogicArray  # cocotb 2.x

        return LogicArray(text)
    except ImportError:  # cocotb 1.x
        from cocotb.binary import BinaryValue

        return BinaryValue(text.lower(), n_bits=len(handle))


REQUIRED_IDS = (
    "CHK-SPI-LANE-PROGRAM",
    "CHK-SPI-LANE-READ",
    "CHK-SPI-LANE-JEDEC",
    "CHK-SPI-LANE-REFUSE",
    "CHK-SPI-LANE-OE",
    "CHK-SPI-LEDGER",
    "CHK-SPI-FRAME-SHAPE",
    "CHK-SPI-FRAME-BYTES",
    "CHK-SPI-READ-DATA",
    "CHK-SPI-MEM-GOLDEN",
)

ADDR_BYTES = 3

READS = (
    OcahSpiOpcode.READ,
    OcahSpiOpcode.DUAL_OUTPUT_READ,
    OcahSpiOpcode.QUAD_OUTPUT_READ,
    OcahSpiOpcode.DUAL_IO_READ,
    OcahSpiOpcode.QUAD_IO_READ,
)


def read_segments(opcode: int, addr: int, length: int) -> list:
    """Command segments of a read at its lane widths."""
    fmt = command_format(opcode)
    assert fmt is not None
    segs: list[tuple[int, str, Any]] = [
        (1, "tx", bytes([opcode])),
        (fmt.addr_lanes, "tx", addr.to_bytes(ADDR_BYTES, "big")),
    ]
    if fmt.dummy_clocks:
        segs.append((fmt.data_lanes if fmt.addr_lanes > 1 else 1, "dummy", fmt.dummy_clocks))
    segs.append((fmt.data_lanes, "rx", length))
    return segs


def phase_bytes(beats, start: int, lanes: int, field: int) -> bytes:
    """Monitor lane decode from beat ``start`` on: field 0 lanes out, field 2 lanes in."""
    values = [beat[field] or 0 for beat in beats[start:]]
    if lanes == 1:
        values = [(v >> (0 if field == 0 else 1)) & 1 for v in values]
    return bytes(lanes_to_bytes(values, lanes)[0])


@cocotb.test()
async def ocah_spi_lanes_test(dut) -> None:
    rng = scenario_rng("lanes")
    harness = await build_lane_stack(dut, required_ids=REQUIRED_IDS, log=log)
    bfm, flash, monitor, checker = harness.host.bfm, harness.flash, harness.monitor, harness.checker
    addr, length = random_page_span(rng)
    payload = bytes(rng.randrange(256) for _ in range(length))
    # Byte 0 is neither erased nor zero: a READ grades real data, and the refused
    # program's zero byte would clear its set bits if it were taken.
    payload = bytes([(payload[0] & 0x7F) | 0x01]) + payload[1:]
    log.info("start: page addr=0x%06x len=%d", addr, length)

    def frames_since(mark: int) -> list:
        return list(monitor.get_transactions()[mark:])

    wren = [(1, "tx", bytes([OcahSpiOpcode.WRITE_ENABLE]))]
    await bfm.lane_frame(wren)
    mark = len(monitor.get_transactions())
    rec_mark = len(flash.get_transactions())
    await bfm.lane_frame(
        [
            (1, "tx", bytes([OcahSpiOpcode.QUAD_PAGE_PROGRAM]) + addr.to_bytes(ADDR_BYTES, "big")),
            (4, "tx", payload),
        ]
    )
    pp_rec = flash.get_transactions()[rec_mark]
    pp_frame = frames_since(mark)[0]
    pp_wire = phase_bytes(pp_frame["beats"], 32, 4, 0)
    checker.expect_equal(
        "CHK-SPI-LANE-PROGRAM",
        (
            pp_rec["ok"],
            pp_rec["reason"],
            pp_rec["data_in"],
            pp_wire,
            flash.write_enabled,
            pp_frame["addr"],
            pp_frame["data_mosi"],
        ),
        (True, "", payload, payload, False, addr, payload),
        context=f"QUAD PAGE PROGRAM addr=0x{addr:06x} len={length}",
    )

    for opcode in READS:
        fmt = command_format(opcode)
        assert fmt is not None
        mark = len(monitor.get_transactions())
        rec_mark = len(flash.get_transactions())
        host = (await bfm.lane_frame(read_segments(opcode, addr, length)))[0]
        rec = flash.get_transactions()[rec_mark]
        frame = frames_since(mark)[0]
        wire = phase_bytes(frame["beats"], fmt.input_clocks(ADDR_BYTES), fmt.data_lanes, 2)
        checker.expect_equal(
            "CHK-SPI-LANE-READ",
            (rec["ok"], host, rec["data_out"], wire, frame["addr"], frame["data_miso"]),
            (True, payload, payload, payload, addr, payload),
            context=(
                f"{OcahSpiOpcode(opcode).name} addr_lanes={fmt.addr_lanes} "
                f"dummy={fmt.dummy_clocks} data_lanes={fmt.data_lanes} len={length}"
            ),
        )

    jedec = (await bfm.lane_frame([(1, "tx", bytes([OcahSpiOpcode.JEDEC_ID])), (1, "rx", 3)]))[0]
    checker.expect_equal(
        "CHK-SPI-LANE-JEDEC", jedec, JEDEC_ID.to_bytes(3, "big"), context="standard mode, lane 1"
    )

    # Refusals inside the lane phases; the latch is set for the program case.
    await bfm.lane_frame(wren)
    memory = flash.read_memory(addr, length)
    rec_mark = len(flash.get_transactions())
    head = bytes([OcahSpiOpcode.QUAD_PAGE_PROGRAM]) + addr.to_bytes(ADDR_BYTES, "big")
    await bfm.lane_frame([(1, "tx", head), (4, "tx", b"\x00"), (4, "clocks", [0])])
    eb = command_format(OcahSpiOpcode.QUAD_IO_READ)
    assert eb is not None
    eb_cmd = (1, "tx", bytes([OcahSpiOpcode.QUAD_IO_READ]))
    await bfm.lane_frame([eb_cmd, (4, "tx", addr.to_bytes(ADDR_BYTES, "big")[:2])])
    await bfm.lane_frame(
        [eb_cmd, (4, "tx", addr.to_bytes(ADDR_BYTES, "big")), (4, "dummy", eb.dummy_clocks - 1)]
    )
    refused = flash.get_transactions()[rec_mark:]
    checker.expect_equal(
        "CHK-SPI-LANE-REFUSE",
        (
            [(r["ok"], r["reason"]) for r in refused],
            flash.read_memory(addr, length),
            flash.write_enabled,
        ),
        (
            [(False, "partial_byte"), (False, "partial_address"), (False, "partial_dummy")],
            memory,
            True,
        ),
        context="quad program cut one nibble into a byte; quad I/O read cut in its address and its dummy",
    )
    await bfm.lane_frame([(1, "tx", bytes([OcahSpiOpcode.WRITE_DISABLE]))])

    # A single-lane transfer() on the four-lane link releases its lane enable.
    await bfm.transfer(OcahSpiOpcode.READ_SR1, rx_len=1)

    # Output-enable violations, one per leg.
    legal_errors = monitor.get_wire_errors()
    legs = []
    half = bfm.half_period_ns

    before = len(monitor.get_wire_errors())
    await bfm.drive(cs_n=0)
    dut.spi4_sd_oe.value = 0b0010
    await bfm.drive(sclk=1)
    await bfm.drive(sclk=0)
    dut.spi4_sd_oe.value = 0
    await bfm.drive(cs_n=1, hold_ns=3 * half)
    legs.append(("lane1_in_x1", [e.split(":")[0] for e in monitor.get_wire_errors()[before:]]))

    before = len(monitor.get_wire_errors())
    dut.spi4_sd_oe.value = 0b0001
    await bfm.drive(hold_ns=2 * half)
    dut.spi4_sd_oe.value = 0
    await bfm.drive(hold_ns=2 * half)
    legs.append(("oe_with_cs_high", [e.split(":")[0] for e in monitor.get_wire_errors()[before:]]))

    before = len(monitor.get_wire_errors())
    await bfm.drive(cs_n=0)
    dut.spi4_sd_oe.value = 0b0001
    await bfm.drive(sclk=1)
    await bfm.drive(sclk=0)
    await bfm.drive(cs_n=1, hold_ns=2 * half)
    dut.spi4_sd_oe.value = 0
    await bfm.drive(hold_ns=2 * half)
    legs.append(("oe_on_at_cs_rise", [e.split(":")[0] for e in monitor.get_wire_errors()[before:]]))

    before = len(monitor.get_wire_errors())
    dut.spi4_cs_oe.value = 0
    await bfm.drive(cs_n=0)
    dut.spi4_sd_oe.value = 0b0001
    await bfm.drive(sclk=1)
    await bfm.drive(sclk=0)
    dut.spi4_sd_oe.value = 0
    await bfm.drive(cs_n=1)
    dut.spi4_cs_oe.value = 1
    await bfm.drive(hold_ns=3 * half)
    legs.append(("cs_oe_low", [e.split(":")[0] for e in monitor.get_wire_errors()[before:]]))

    # WRITE ENABLE shifted on lane 0 with its output enable off.
    before = len(monitor.get_wire_errors())
    await bfm.drive(cs_n=0)
    for bit in [(int(OcahSpiOpcode.WRITE_ENABLE) >> k) & 1 for k in range(7, -1, -1)]:
        dut.spi4_sd_out.value = bit
        await bfm.drive(sclk=1)
        await bfm.drive(sclk=0)
    await bfm.drive(cs_n=1, hold_ns=3 * half)
    dut.spi4_sd_out.value = 0
    legs.append(("lane0_oe_off", [e.split(":")[0] for e in monitor.get_wire_errors()[before:]]))

    # X on a disabled lane does not hide a lane 0 change on a sample edge.
    if FOUR_STATE:
        before = len(monitor.get_wire_errors())
        await bfm.drive(cs_n=0)
        dut.spi4_sd_oe.value = 0b0001
        dut.spi4_sd_out.value = _lanes_value(dut.spi4_sd_out, "X000")
        await bfm.drive(hold_ns=half)
        dut.spi4_sd_out.value = _lanes_value(dut.spi4_sd_out, "X001")
        await bfm.drive(sclk=1)  # lane 0 changes on the sample edge
        await bfm.drive(sclk=0)
        dut.spi4_sd_oe.value = 0
        dut.spi4_sd_out.value = 0
        await bfm.drive(cs_n=1, hold_ns=3 * half)
        legs.append(
            ("x_on_disabled_lane", [e.split(":")[0] for e in monitor.get_wire_errors()[before:]])
        )
    else:
        log.info("OBS-SPI-LANE-XZ graded=0 reason=2-state simulator holds no X")

    errors = monitor.get_wire_errors()
    expected_stop = f"{monitor.name}: {len(errors)} wire-check violation(s); first: {errors[0]}"
    stop_text = ""
    try:
        await monitor.stop()
    except OcahSpiMonitorError as exc:
        stop_text = str(exc)
    checker.expect_equal(
        "CHK-SPI-LANE-OE",
        (legal_errors, legs, stop_text == expected_stop),
        (
            [],
            [
                ("lane1_in_x1", ["oe_lanes", "oe_data"]),
                ("oe_with_cs_high", ["oe_idle"]),
                ("oe_on_at_cs_rise", ["oe_idle"]),
                ("cs_oe_low", ["oe_ctrl"]),
                ("lane0_oe_off", ["oe_data"]),
            ]
            + ([("x_on_disabled_lane", ["mosi_edge"])] if FOUR_STATE else []),
            True,
        ),
        context=f"stop() raised {stop_text!r}",
    )
    await flash.stop()

    records = flash.get_transactions()
    frames = monitor.get_transactions()
    checker.check_ledger(frames, records)
    checker.replay([r for r in records if r["reason"] not in FRAME_SHAPE_REASONS])
    checker.check_memory(context="quad page program")
    log.info("LANES_SUMMARY records=%d frames=%d", len(records), len(frames))
    checker.finalize()
