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
    "CHK-SPI-PARTIAL-CALLBACK",
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
_CALLBACK_FRAME = 7


@cocotb.test()
async def ocah_spi_partial_byte_test(dut) -> None:
    rng = scenario_rng("partial_byte")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    host, flash, checker = harness.host, harness.flash, harness.checker
    addr, length = random_page_span(rng)
    data = random_payload(rng, length)
    tail_bits = rng.randint(1, 7)
    other = random_payload(rng, length)
    callback_calls: list[int] = []

    async def program_callback(opcode: int, addr: int, payload: bytes) -> None:
        callback_calls.append(addr)

    log.info("start: page addr=0x%06x len=%d tail_bits=%d", addr, length, tail_bits)

    await host.write_enable()
    await host.raw_command(OcahSpiOpcode.PAGE_PROGRAM, addr=addr, tx=data, tail_bits=tail_bits)
    await host.read_status1()
    erased = await host.read(addr, length)
    await host.page_program(addr, data)
    await host.read(addr, length)
    flash.register_command_callback(OcahSpiOpcode.PAGE_PROGRAM, program_callback)
    await host.write_enable()
    await host.raw_command(OcahSpiOpcode.PAGE_PROGRAM, addr=addr, tx=other, tail_bits=tail_bits)
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
    via_callback = records[_CALLBACK_FRAME]
    checker.expect_equal(
        "CHK-SPI-PARTIAL-CALLBACK",
        (
            via_callback["opcode"],
            via_callback["ok"],
            via_callback["reason"],
            via_callback["data_in"],
            len(callback_calls),
            flash.read_memory(addr, length),
        ),
        (OcahSpiOpcode.PAGE_PROGRAM, False, "partial_byte", other, 0, data),
        context=f"PAGE PROGRAM with a registered callback ended {tail_bits} bit(s) into a byte",
    )

    checker.replay(records[:_PARTIAL_FRAME] + records[_PARTIAL_FRAME + 1 : _CALLBACK_FRAME])
    checker.check_host_responses(OcahSpiOpcode.READ, host.responses(OcahSpiOpcode.READ))
    checker.check_command_order(
        [
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.WRITE_ENABLE,
        ]
    )
    checker.check_memory(source=data, addr=addr, context="live control on a byte boundary")
    checker.check_nonvacuous()
    checker.expect_true(
        "CHK-SPI-NEG-FRAME",
        rejects("frame", flash, lambda probe: probe.replay([partial])),
        context="a probe checker handed the refused record must fail CHK-SPI-FRAME-BYTES",
    )
    checker.finalize()
