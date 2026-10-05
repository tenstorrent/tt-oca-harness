# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: out-of-scope opcodes earn no credit.

After a page is programmed and read back, the controller issues dual-output
read, quad-output read, block erase, chip erase, and enter-4-byte-address
frames. The device drains each without a response or a payload, the erase
attempts leave the page intact, the monitor decodes them as unknown with empty
data fields, and the checker counts them as unsupported: the in-scope opcode
sequence and the memory evidence exclude them, and ``CHK-SPI-UNSUPPORTED``
names exactly the opcodes seen.
"""

from __future__ import annotations

import logging

import cocotb
from ocah_spi_vip import OcahSpiOpcode
from ocah_spi_vip_harness import build_stack, random_page_span, random_payload, scenario_rng

log = logging.getLogger("cocotb.tb.ocah_spi_unsupported_test")

REQUIRED_IDS = (
    "CHK-SPI-WREN-ORDER",
    "CHK-SPI-READ-DATA",
    "CHK-SPI-HOST-READBACK",
    "CHK-SPI-MEM-GOLDEN",
    "CHK-SPI-MEM-SOURCE",
    "CHK-SPI-NONVAC-PROGRAM",
    "CHK-SPI-NONVAC-READ",
    "CHK-SPI-CMD-ORDER",
    "CHK-SPI-UNSUPPORTED",
    "CHK-SPI-MON-UNKNOWN",
)
DUAL_OUTPUT_READ = 0x3B
QUAD_OUTPUT_READ = 0x6B
BLOCK_ERASE_64K = 0xD8
CHIP_ERASE = 0xC7
ENTER_4BYTE_ADDR = 0xB7
OUT_OF_SCOPE = (DUAL_OUTPUT_READ, QUAD_OUTPUT_READ, BLOCK_ERASE_64K, CHIP_ERASE, ENTER_4BYTE_ADDR)


@cocotb.test()
async def ocah_spi_unsupported_test(dut) -> None:
    rng = scenario_rng("unsupported")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    host, checker = harness.host, harness.checker
    addr, length = random_page_span(rng)
    data = random_payload(rng, length)
    log.info(
        "start: page addr=0x%06x len=%d, then %d out-of-scope frames",
        addr,
        length,
        len(OUT_OF_SCOPE),
    )

    await host.write_enable()
    await host.page_program(addr, data)
    await host.read(addr, length)
    await host.raw_command(DUAL_OUTPUT_READ, addr=addr, dummy_bytes=1, rx_len=4)
    await host.raw_command(QUAD_OUTPUT_READ, addr=addr, dummy_bytes=1, rx_len=4)
    await host.write_enable()
    await host.raw_command(BLOCK_ERASE_64K, addr=addr)
    await host.write_enable()
    await host.raw_command(CHIP_ERASE)
    await host.raw_command(ENTER_4BYTE_ADDR)
    await host.write_disable()
    await host.read(addr, length)
    await harness.stop()

    checker.replay()
    checker.check_host_responses(OcahSpiOpcode.READ, host.responses(OcahSpiOpcode.READ))
    checker.check_command_order(
        [
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.PAGE_PROGRAM,
            OcahSpiOpcode.READ,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.WRITE_DISABLE,
            OcahSpiOpcode.READ,
        ]
    )
    checker.check_unsupported(OUT_OF_SCOPE)
    checker.check_memory(source=data, addr=addr, context="page intact after out-of-scope erases")
    checker.check_nonvacuous()

    unknown = [
        (txn["data_mosi"], txn["data_miso"])
        for txn in harness.monitor.get_transactions()
        if txn["opcode"] in OUT_OF_SCOPE
    ]
    checker.expect_equal(
        "CHK-SPI-MON-UNKNOWN",
        unknown,
        [(b"", b"")] * len(OUT_OF_SCOPE),
        context="monitor carries no data for an unknown opcode",
    )
    checker.finalize()
