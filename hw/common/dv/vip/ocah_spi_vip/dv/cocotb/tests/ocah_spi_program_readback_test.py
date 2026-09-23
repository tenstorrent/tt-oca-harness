# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: page program and readback.

A seeded span inside one page is programmed after WRITE ENABLE, read back
with READ and FAST READ, and programmed again with a second pattern so the
readback shows the bit-clearing semantics; a second span wraps around the end
of its page. READ STATUS REGISTER 1 after each program shows the consumed
latch. The device array equals the reference model, the reference equals the
source image the test computed, and a probe checker handed a corrupted source
must reject it.

``OCAH_SPI_SELFTEST_NEGATIVE`` corrupts the source image handed to the test's
own checker so ``CHK-SPI-MEM-SOURCE`` fails and the run must fail.
"""

from __future__ import annotations

import logging

import cocotb
from ocah_spi_vip import PAGE_SIZE, OcahSpiOpcode
from ocah_spi_vip_harness import (
    build_stack,
    negative_armed,
    random_page_span,
    random_payload,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_spi_program_readback_test")

REQUIRED_IDS = (
    "CHK-SPI-WREN-ORDER",
    "CHK-SPI-READ-DATA",
    "CHK-SPI-HOST-READBACK",
    "CHK-SPI-STATUS-WEL",
    "CHK-SPI-MEM-GOLDEN",
    "CHK-SPI-MEM-SOURCE",
    "CHK-SPI-NONVAC-PROGRAM",
    "CHK-SPI-NONVAC-READ",
    "CHK-SPI-CMD-ORDER",
    "CHK-SPI-NEG-PATTERN",
)
_ERASED = 0xFF


def _corrupted(image: bytes) -> bytes:
    """``image`` with one bit of its first byte flipped."""
    return bytes([image[0] ^ 0x01]) + image[1:]


@cocotb.test()
async def ocah_spi_program_readback_test(dut) -> None:
    rng = scenario_rng("program_readback")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    host, checker = harness.host, harness.checker
    addr, length = random_page_span(rng)
    first = random_payload(rng, length)
    second = random_payload(rng, length)
    expected = bytes(a & b for a, b in zip(first, second))
    wrap_page = (rng.randrange(0, harness.flash.flash_size // PAGE_SIZE)) * PAGE_SIZE
    wrap_tail = rng.randint(1, 8)
    wrap_len = wrap_tail + rng.randint(1, 8)
    wrap_addr = wrap_page + PAGE_SIZE - wrap_tail
    wrap_data = random_payload(rng, wrap_len)
    negative = negative_armed()
    log.info(
        "start: span addr=0x%06x len=%d, wrap addr=0x%06x len=%d, negative=%s",
        addr,
        length,
        wrap_addr,
        wrap_len,
        negative,
    )

    await host.write_enable()
    await host.page_program(addr, first)
    await host.read(addr, length)
    await host.fast_read(addr, length)
    await host.read_status1()
    await host.write_enable()
    await host.page_program(addr, second)
    await host.read(addr, length)
    await host.write_enable()
    await host.page_program(wrap_addr, wrap_data)
    await host.read(wrap_page, PAGE_SIZE)
    await host.read_status1()
    await harness.stop()

    wrap_image = bytearray([_ERASED] * PAGE_SIZE)
    for index, value in enumerate(wrap_data):
        wrap_image[(PAGE_SIZE - wrap_tail + index) % PAGE_SIZE] &= value

    checker.replay()
    host.check_host_responses()
    checker.check_command_order(
        [
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.FAST_READ,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.READ_SR1,
        ]
    )
    source = _corrupted(expected) if negative else expected
    if negative:
        log.warning(
            "NEGATIVE VALIDATION: the source image handed to the checker is corrupted; "
            "CHK-SPI-MEM-SOURCE must fail"
        )
    checker.check_memory(source=source, addr=addr, context="two programs, bit-clearing")
    checker.check_memory(source=bytes(wrap_image), addr=wrap_page, context="page wrap")
    checker.check_nonvacuous()

    records = harness.flash.get_transactions()
    rejected = rejects(
        "pattern",
        harness.flash,
        lambda probe: (
            probe.replay(records),
            probe.check_memory(source=_corrupted(expected), addr=addr),
        ),
    )
    checker.expect_true(
        "CHK-SPI-NEG-PATTERN", rejected, context="a wrong source image must be rejected"
    )
    checker.finalize()
