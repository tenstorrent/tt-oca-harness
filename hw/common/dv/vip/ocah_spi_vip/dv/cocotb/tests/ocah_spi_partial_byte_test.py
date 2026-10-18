# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: a PAGE PROGRAM that ends mid-byte is refused.

After WRITE ENABLE, the controller sends a PAGE PROGRAM frame whose
chip-select rises a seeded 1 to 7 bits into the byte after the payload. The
device refuses it: the record carries ``ok=False, reason="partial_byte"`` and
the complete payload bytes, READ STATUS REGISTER 1 still shows the latch set,
and a READ of the span returns the erased 0xFF. The same payload sent again on
a byte boundary is the live control: it is accepted and read back. A
registered PAGE PROGRAM callback is then given a second mid-byte frame with a
new payload: the device refuses it before the callback runs, and memory keeps
the control's bytes.

The checker replays the frames other than the two refused ones. A fail-fast probe
checker handed the refused record must raise ``CHK-SPI-FRAME-BYTES``.
"""

from __future__ import annotations

import logging

import cocotb
from ocah_spi_vip import OcahSpiOpcode
from ocah_spi_vip_harness import (
    build_stack,
    random_page_span,
    random_payload,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_spi_partial_byte_test")

REQUIRED_IDS = (
    "CHK-SPI-PARTIAL-REFUSED",
    "CHK-SPI-PARTIAL-ERASED",
    "CHK-SPI-CALLBACK-WEL-GATE",
    "CHK-SPI-PARTIAL-CALLBACK",
    "CHK-SPI-CALLBACK-ACCEPT",
    "CHK-SPI-FRAME-SCOPE",
    "CHK-SPI-FRAME-BYTES",
    "CHK-SPI-WREN-ORDER",
    "CHK-SPI-STATUS-WEL",
    "CHK-SPI-READ-DATA",
    "CHK-SPI-HOST-READBACK",
    "CHK-SPI-MEM-GOLDEN",
    "CHK-SPI-MEM-SOURCE",
    "CHK-SPI-NONVAC-PROGRAM",
    "CHK-SPI-NONVAC-READ",
    "CHK-SPI-CMD-ORDER",
    "CHK-SPI-NEG-FRAME",
)
_ERASED = 0xFF
_PARTIAL_FRAME = 1
_WEL_CLEAR_CALLBACK_FRAME = 6
_CALLBACK_FRAME = 8
_ACCEPTED_CALLBACK_FRAME = 9


@cocotb.test()
async def ocah_spi_partial_byte_test(dut) -> None:
    rng = scenario_rng("partial_byte")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    host, flash, checker = harness.host, harness.flash, harness.checker
    addr, length = random_page_span(rng)
    data = random_payload(rng, length)
    tail_bits = rng.randint(1, 7)
    other = random_payload(rng, length)
    callback_data = bytes(a & b for a, b in zip(data, other))
    callback_calls: list[int] = []

    async def program_callback(opcode: int, addr: int, payload: bytes) -> None:
        callback_calls.append(addr)
        current = flash.read_memory(addr, len(payload))
        flash.write_memory(addr, bytes(a & b for a, b in zip(current, payload)))

    log.info("start: page addr=0x%06x len=%d tail_bits=%d", addr, length, tail_bits)

    await host.write_enable()
    await host.raw_command(OcahSpiOpcode.PAGE_PROGRAM, addr=addr, tx=data, tail_bits=tail_bits)
    await host.read_status1()
    erased = await host.read(addr, length)
    await host.page_program(addr, data)
    await host.read(addr, length)
    flash.register_command_callback(OcahSpiOpcode.PAGE_PROGRAM, program_callback)
    await host.raw_command(OcahSpiOpcode.PAGE_PROGRAM, addr=addr, tx=other)
    calls_after_wel_clear = len(callback_calls)
    memory_after_wel_clear = flash.read_memory(addr, length)
    await host.write_enable()
    await host.raw_command(OcahSpiOpcode.PAGE_PROGRAM, addr=addr, tx=other, tail_bits=tail_bits)
    calls_after_partial = len(callback_calls)
    wel_after_partial = flash.write_enabled
    memory_after_partial = flash.read_memory(addr, length)
    await host.raw_command(OcahSpiOpcode.PAGE_PROGRAM, addr=addr, tx=other)
    status_after_callback = await host.read_status1()
    flash.unregister_command_callback(OcahSpiOpcode.PAGE_PROGRAM)
    await harness.stop()

    records = flash.get_transactions()
    partial = records[_PARTIAL_FRAME]
    checker.expect_equal(
        "CHK-SPI-PARTIAL-REFUSED",
        (partial["opcode"], partial["addr"], partial["ok"], partial["reason"], partial["data_in"]),
        (OcahSpiOpcode.PAGE_PROGRAM, addr, False, "partial_byte", data),
        context=f"PAGE PROGRAM ended {tail_bits} bit(s) into a payload byte",
    )
    checker.expect_equal(
        "CHK-SPI-PARTIAL-ERASED",
        erased,
        bytes([_ERASED]) * length,
        context="controller READ after the refused PAGE PROGRAM",
    )
    wel_clear_callback = records[_WEL_CLEAR_CALLBACK_FRAME]
    checker.expect_equal(
        "CHK-SPI-CALLBACK-WEL-GATE",
        (
            wel_clear_callback["ok"],
            wel_clear_callback["reason"],
            wel_clear_callback["data_in"],
            calls_after_wel_clear,
            memory_after_wel_clear,
        ),
        (False, "wel_clear", b"", 0, data),
        context="PAGE PROGRAM callback remains behind the write-enable gate",
    )
    via_callback = records[_CALLBACK_FRAME]
    checker.expect_equal(
        "CHK-SPI-PARTIAL-CALLBACK",
        (
            via_callback["opcode"],
            via_callback["ok"],
            via_callback["reason"],
            via_callback["data_in"],
            calls_after_partial,
            memory_after_partial,
            wel_after_partial,
        ),
        (OcahSpiOpcode.PAGE_PROGRAM, False, "partial_byte", other, 0, data, True),
        context=f"PAGE PROGRAM with a registered callback ended {tail_bits} bit(s) into a byte",
    )
    accepted_callback = records[_ACCEPTED_CALLBACK_FRAME]
    checker.expect_equal(
        "CHK-SPI-CALLBACK-ACCEPT",
        (
            accepted_callback["ok"],
            accepted_callback["reason"],
            accepted_callback["data_in"],
            callback_calls,
            status_after_callback,
            flash.write_enabled,
            flash.read_memory(addr, length),
        ),
        (True, "", other, [addr], 0, False, callback_data),
        context="a byte-complete callback PAGE PROGRAM consumes the write-enable latch",
    )

    checker.replay(
        [
            record
            for index, record in enumerate(records)
            if index not in (_PARTIAL_FRAME, _CALLBACK_FRAME)
        ]
    )
    checker.expect_equal(
        "CHK-SPI-FRAME-SCOPE",
        sum(finding.check_id == "CHK-SPI-FRAME-BYTES" for finding in checker.evidence.findings),
        2,
        context="only latch-set PAGE PROGRAM frames earn byte-boundary evidence",
    )
    checker.check_host_responses(OcahSpiOpcode.READ, host.responses(OcahSpiOpcode.READ))
    checker.check_command_order(
        [
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ_SR1,
        ]
    )
    checker.check_memory(
        source=callback_data,
        addr=addr,
        context="byte-complete built-in and callback PAGE PROGRAM operations",
    )
    checker.check_nonvacuous()
    checker.expect_true(
        "CHK-SPI-NEG-FRAME",
        rejects(
            "frame",
            flash,
            lambda probe: probe.replay(records[: _PARTIAL_FRAME + 1]),
            check_id="CHK-SPI-FRAME-BYTES",
        ),
        context="a probe checker handed the refused record must fail CHK-SPI-FRAME-BYTES",
    )
    checker.finalize()
