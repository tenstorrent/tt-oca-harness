# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: sector erase.

A blank sector is erased first, so the scenario carries an erase that flips
nothing. Then one page in a seeded sector and one page in its neighbour are
programmed and read back, the seeded sector is erased through an address
inside it, and the readback shows the erased page blank and the neighbour
intact. The device array equals the reference model, the neighbour equals
its source image, and the erase counted as non-vacuous. A probe checker that
sees only the blank-sector erase must reject the scenario as vacuous.
"""

from __future__ import annotations

import logging

import cocotb
from ocah_spi_vip import SECTOR_SIZE, OcahSpiOpcode
from ocah_spi_vip_harness import (
    FLASH_SIZE,
    build_stack,
    random_page_span,
    random_payload,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_spi_erase_test")

REQUIRED_IDS = (
    "CHK-SPI-WREN-ORDER",
    "CHK-SPI-READ-DATA",
    "CHK-SPI-HOST-READBACK",
    "CHK-SPI-STATUS-WEL",
    "CHK-SPI-MEM-GOLDEN",
    "CHK-SPI-MEM-SOURCE",
    "CHK-SPI-NONVAC-PROGRAM",
    "CHK-SPI-NONVAC-READ",
    "CHK-SPI-NONVAC-ERASE",
    "CHK-SPI-ERASE-BLANK",
    "CHK-SPI-ERASE-NEIGHBOUR",
    "CHK-SPI-CMD-ORDER",
    "CHK-SPI-NEG-ERASE",
)
_ERASED = 0xFF
_BLANK_ERASE_FRAMES = 3


@cocotb.test()
async def ocah_spi_erase_test(dut) -> None:
    rng = scenario_rng("erase")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    host, checker = harness.host, harness.checker
    addr, length = random_page_span(rng)
    sector = addr & ~(SECTOR_SIZE - 1)
    neighbour_addr = addr ^ SECTOR_SIZE
    blank_sector = (sector + 2 * SECTOR_SIZE) % FLASH_SIZE
    data = random_payload(rng, length)
    neighbour_data = random_payload(rng, length)
    erase_addr = sector + rng.randrange(0, SECTOR_SIZE)
    log.info(
        "start: page addr=0x%06x len=%d, neighbour=0x%06x, erase via 0x%06x, blank sector 0x%06x",
        addr,
        length,
        neighbour_addr,
        erase_addr,
        blank_sector,
    )

    await host.write_enable()
    await host.sector_erase(blank_sector)
    await host.read(blank_sector, 4)
    await host.write_enable()
    await host.page_program(addr, data)
    await host.write_enable()
    await host.page_program(neighbour_addr, neighbour_data)
    await host.read(addr, length)
    await host.read(neighbour_addr, length)
    await host.write_enable()
    await host.sector_erase(erase_addr)
    erased = await host.read(addr, length)
    kept = await host.read(neighbour_addr, length)
    await host.read_status1()
    await harness.stop()

    checker.replay()
    host.check_host_responses()
    checker.check_command_order(
        [
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.SECTOR_ERASE,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.SECTOR_ERASE,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.READ_SR1,
        ]
    )
    checker.expect_equal(
        "CHK-SPI-ERASE-BLANK",
        erased,
        bytes([_ERASED] * length),
        context=f"page at 0x{addr:06x} after erasing its sector via 0x{erase_addr:06x}",
    )
    checker.expect_equal(
        "CHK-SPI-ERASE-NEIGHBOUR",
        kept,
        neighbour_data,
        context=f"neighbour page at 0x{neighbour_addr:06x} after the erase",
    )
    checker.check_memory(source=neighbour_data, addr=neighbour_addr, context="neighbour intact")
    checker.check_nonvacuous(require_erase=True)

    records = harness.flash.get_transactions()
    rejected = rejects(
        "erase",
        harness.flash,
        lambda probe: (
            probe.replay(records[:_BLANK_ERASE_FRAMES]),
            probe.check_nonvacuous(require_program=False, require_read=False, require_erase=True),
        ),
    )
    checker.expect_true(
        "CHK-SPI-NEG-ERASE",
        rejected,
        context="an erase that flips no programmed byte must not count as erase evidence",
    )
    checker.finalize()
