# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared SPI VIP selftest: identifier and status registers.

READ JEDEC ID streams the configured identifier and the controller decodes
it; READ STATUS REGISTER 1 follows the write-enable latch through WRITE
ENABLE and WRITE DISABLE; READ STATUS REGISTER 2 returns the configured
non-zero register; the monitor sees the same opcodes as the device and the
identifier bytes on MISO. A probe checker configured with a different
identifier must reject the same records.
"""

from __future__ import annotations

import logging

import cocotb
from ocah_spi_vip import OcahSpiFlashChecker, OcahSpiOpcode
from ocah_spi_vip_harness import JEDEC_ID, build_stack, rejects, scenario_rng

log = logging.getLogger("cocotb.tb.ocah_spi_jedec_test")

REQUIRED_IDS = (
    "CHK-SPI-JEDEC-ID",
    "CHK-SPI-HOST-JEDEC",
    "CHK-SPI-STATUS-WEL",
    "CHK-SPI-STATUS-SR2",
    "CHK-SPI-HOST-STATUS",
    "CHK-SPI-CMD-ORDER",
    "CHK-SPI-MON-OPCODES",
    "CHK-SPI-MON-JEDEC",
    "CHK-SPI-NEG-JEDEC",
)


@cocotb.test()
async def ocah_spi_jedec_test(dut) -> None:
    rng = scenario_rng("jedec")
    harness = await build_stack(dut, required_ids=REQUIRED_IDS, log=log)
    host, checker = harness.host, harness.checker
    repeats = rng.randint(1, 3)
    log.info("start: %d JEDEC reads, latch walk, SR2, monitor cross-check, negative probe", repeats)

    for _ in range(repeats):
        await host.jedec_id()
    await host.read_status1()
    await host.write_enable()
    await host.read_status1()
    await host.write_disable()
    await host.read_status1()
    await host.read_status2()
    await harness.stop()

    checker.replay()
    host.check_host_responses()
    checker.check_command_order(
        [OcahSpiOpcode.JEDEC_ID] * repeats
        + [
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.WRITE_ENABLE,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.WRITE_DISABLE,
            OcahSpiOpcode.READ_SR1,
            OcahSpiOpcode.READ_SR2,
        ]
    )

    observed = harness.monitor.get_transactions()
    checker.expect_equal(
        "CHK-SPI-MON-OPCODES",
        [txn["opcode"] for txn in observed],
        checker.opcodes,
        context="monitor frames against device records",
    )
    checker.expect_equal(
        "CHK-SPI-MON-JEDEC",
        [txn["data_miso"] for txn in observed if txn["opcode"] == OcahSpiOpcode.JEDEC_ID],
        [JEDEC_ID.to_bytes(3, "big")] * repeats,
        context="identifier bytes on MISO after the opcode phase",
    )

    records = harness.flash.get_transactions()

    def _replay_with_wrong_id(probe: OcahSpiFlashChecker) -> None:
        probe.jedec_id = JEDEC_ID ^ 0x01
        probe.replay(records)

    rejected = rejects("jedec", harness.flash, _replay_with_wrong_id)
    checker.expect_true(
        "CHK-SPI-NEG-JEDEC", rejected, context="a different expected identifier must be rejected"
    )
    checker.finalize()
