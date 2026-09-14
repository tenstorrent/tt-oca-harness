# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: write-enable ordering.

A PAGE PROGRAM and a SECTOR ERASE issued without WRITE ENABLE, and a PAGE
PROGRAM after WRITE ENABLE then WRITE DISABLE, are refused and leave the page
blank; a PAGE PROGRAM after WRITE ENABLE lands and consumes the latch, so the
program that follows without a new WRITE ENABLE is refused and the data stays.
The opcode sequence is exact. A probe checker handed a wrong expected sequence
must reject it, and a probe that replays a device which programmed without
WRITE ENABLE must reject the ordering.

``OCAH_SPI_SELFTEST_NEGATIVE`` makes the device accept the first unprotected
PAGE PROGRAM so ``CHK-SPI-WREN-ORDER`` fails and the run must fail.
"""

from __future__ import annotations

import logging

import cocotb
from ocah_spi_vip import OcahSpiOpcode
from ocah_spi_vip_harness import (
    build_stack,
    negative_armed,
    random_page_span,
    random_payload,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_spi_ordering_test")

REQUIRED_IDS = (
    "CHK-SPI-WREN-ORDER",
    "CHK-SPI-READ-DATA",
    "CHK-SPI-HOST-READBACK",
    "CHK-SPI-STATUS-WEL",
    "CHK-SPI-MEM-GOLDEN",
    "CHK-SPI-MEM-SOURCE",
    "CHK-SPI-REFUSED-BLANK",
    "CHK-SPI-REFUSED-KEPT",
    "CHK-SPI-NONVAC-PROGRAM",
    "CHK-SPI-NONVAC-READ",
    "CHK-SPI-CMD-ORDER",
    "CHK-SPI-NEG-ORDER",
    "CHK-SPI-NEG-WEL",
)
_ERASED = 0xFF
EXPECTED_ORDER = [
    OcahSpiOpcode.PAGE_PROGRAM,
    OcahSpiOpcode.READ,
    OcahSpiOpcode.SECTOR_ERASE,
    OcahSpiOpcode.WRITE_ENABLE,
    OcahSpiOpcode.WRITE_DISABLE,
    OcahSpiOpcode.PAGE_PROGRAM,
    OcahSpiOpcode.READ_SR1,
    OcahSpiOpcode.WRITE_ENABLE,
    OcahSpiOpcode.PAGE_PROGRAM,
    OcahSpiOpcode.READ,
    OcahSpiOpcode.PAGE_PROGRAM,
    OcahSpiOpcode.READ,
    OcahSpiOpcode.READ_SR1,
]


def _unprotected_program(flash):
    """A device handler that programs on PAGE PROGRAM whatever the latch says."""

    async def handler(opcode: int, addr: int, payload: bytes) -> None:
        current = bytearray(flash.read_memory(addr, len(payload)))
        flash.write_memory(addr, bytes(a & b for a, b in zip(current, payload)))

    return handler


@cocotb.test()
async def ocah_spi_ordering_test(dut) -> None:
    rng = scenario_rng("ordering")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    host, checker, flash = harness.host, harness.checker, harness.flash
    addr, length = random_page_span(rng)
    data = random_payload(rng, length)
    other = random_payload(rng, length)
    negative = negative_armed()
    log.info("start: page addr=0x%06x len=%d, negative=%s", addr, length, negative)

    if negative:
        log.warning(
            "NEGATIVE VALIDATION: the device programs without WRITE ENABLE; "
            "CHK-SPI-WREN-ORDER must fail"
        )
        flash.register_command_callback(OcahSpiOpcode.PAGE_PROGRAM, _unprotected_program(flash))

    await host.page_program(addr, data)
    blank = await host.read(addr, length)
    await host.sector_erase(addr)
    await host.write_enable()
    await host.write_disable()
    await host.page_program(addr, data)
    await host.read_status1()
    await host.write_enable()
    await host.page_program(addr, data)
    await host.read(addr, length)
    await host.page_program(addr, other)
    kept = await host.read(addr, length)
    await host.read_status1()

    checker.replay()
    host.check_host_responses()
    checker.check_command_order(EXPECTED_ORDER)
    checker.expect_equal(
        "CHK-SPI-REFUSED-BLANK",
        blank,
        bytes([_ERASED] * length),
        context="page after a PAGE PROGRAM issued without WRITE ENABLE",
    )
    checker.expect_equal(
        "CHK-SPI-REFUSED-KEPT",
        kept,
        data,
        context="page after a PAGE PROGRAM issued with the latch consumed",
    )
    checker.check_memory(source=data, addr=addr, context="one accepted program")
    checker.check_nonvacuous()

    records = flash.get_transactions()
    rejected_order = rejects(
        "order",
        flash,
        lambda probe: (
            probe.replay(records),
            probe.check_command_order(EXPECTED_ORDER[1:] + EXPECTED_ORDER[:1]),
        ),
    )
    checker.expect_true(
        "CHK-SPI-NEG-ORDER", rejected_order, context="a wrong expected sequence must be rejected"
    )

    flash.register_command_callback(OcahSpiOpcode.PAGE_PROGRAM, _unprotected_program(flash))
    faulty_addr = addr ^ 0x100
    await host.page_program(faulty_addr, other)
    flash.unregister_command_callback(OcahSpiOpcode.PAGE_PROGRAM)
    await harness.stop()
    rejected_latch = rejects("latch", flash, lambda probe: probe.replay(flash.get_transactions()))
    checker.expect_true(
        "CHK-SPI-NEG-WEL",
        rejected_latch,
        context=f"a device that programmed 0x{faulty_addr:06x} without WRITE ENABLE must be rejected",
    )
    checker.finalize()
