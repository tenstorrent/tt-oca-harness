# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared setup for the SPI VIP wire-harness selftests.

One single-SPI connection exists in ``tb_top.sv`` (``spi_cs_n``, ``spi_sclk``,
``spi_mosi``, ``spi_miso``). The shared controller engine
(``OcahSpiMasterBfm`` behind ``OcahSpiMasterSequence``) drives chip-select,
clock, and MOSI and samples MISO; the shared flash device (``OcahSpiFlash``)
samples the same nets and drives MISO. ``OcahSpiMonitor`` listens on the
connection, and one ``OcahSpiFlashChecker`` collects every ``CHK-*`` record of
a test from the device's records and the controller's responses.

The device is a 1 MiB flash with JEDEC ID ``0xEF4018`` and a non-zero status
register 2, so a receive path stuck at zero fails the status evidence.

Each selftest carries an in-band negative case: a second, fail-fast checker
with a silent logger receives a wrong expectation or a faulty record stream
and must raise. The ``OCAH_SPI_SELFTEST_NEGATIVE`` knob turns
``ocah_spi_program_readback_test`` (a corrupted source image) and
``ocah_spi_ordering_test`` (a device that programs without WRITE ENABLE) into
runs that must fail.

``clk`` is a free-running reference clock this module drives so the
simulator always holds a timed event while the controller bit-bangs sclk.

The seed accessor and the salted scenario RNG live here: these selftests are
plain cocotb tests without a base test class.
"""

from __future__ import annotations

import logging
import os
import random
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer
from ocah_checker import OcahCheckerError
from ocah_lib import OcahKnobs, OcahRng
from ocah_spi_vip import (
    PAGE_SIZE,
    SECTOR_SIZE,
    OcahSpiFlash,
    OcahSpiFlashChecker,
    OcahSpiMasterBfm,
    OcahSpiMasterSequence,
    OcahSpiMonitor,
)

__all__ = [
    "FLASH_SIZE",
    "JEDEC_ID",
    "NEGATIVE_KNOB",
    "STATUS_REG2",
    "SpiHarness",
    "base_seed",
    "build_stack",
    "negative_armed",
    "random_page_span",
    "random_payload",
    "rejects",
    "scenario_rng",
]

PREFIX = "spi"
CLK_PERIOD_NS = 4
HALF_PERIOD_NS = 10
JEDEC_ID = 0xEF4018
STATUS_REG2 = 0x5A
FLASH_SIZE = 1 << 20
NEGATIVE_KNOB = "OCAH_SPI_SELFTEST_NEGATIVE"
_SEED_ENV = "RANDOM_SEED"
_ERASED = 0xFF


@dataclass(frozen=True)
class SpiHarness:
    """The bound stack of one selftest: the controller surface, the device, the monitor, the checker."""

    host: OcahSpiMasterSequence
    flash: OcahSpiFlash
    monitor: OcahSpiMonitor
    checker: OcahSpiFlashChecker

    async def stop(self) -> None:
        """Stop the monitor and the device; their histories survive.

        The monitor's swallowed-callback count is recorded on the test's
        checker, so a subscriber exception the monitor logged cannot pass.
        """
        await self.monitor.stop()
        await self.flash.stop()
        self.checker.expect_equal(
            "CHK-SPI-MON-CALLBACKS",
            self.monitor.get_statistics()["callback_errors"],
            0,
            context="subscriber exceptions the monitor swallowed",
        )


async def build_stack(
    dut: Any,
    *,
    required_ids: Iterable[str],
    log: logging.Logger,
    preload: bytes | None = None,
) -> SpiHarness:
    """Start the reference clock and attach the controller, device, monitor, and checker."""
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())
    flash = OcahSpiFlash(
        dut.spi_cs_n,
        dut.spi_sclk,
        mosi=dut.spi_mosi,
        miso=dut.spi_miso,
        name="harness_flash",
        jedec_id=JEDEC_ID,
        flash_size=FLASH_SIZE,
        status_reg2=STATUS_REG2,
    )
    if preload is not None:
        flash.preload(preload)
    flash.init_signals()
    bfm = OcahSpiMasterBfm.from_prefix(
        dut, PREFIX, name="harness_host", half_period_ns=HALF_PERIOD_NS
    )
    bfm.init_signals()
    monitor = OcahSpiMonitor(
        dut.spi_cs_n, dut.spi_sclk, mosi=dut.spi_mosi, miso=dut.spi_miso, name="harness_monitor"
    )
    checker = OcahSpiFlashChecker(
        name="ocah_spi_harness", flash=flash, required_ids=required_ids, logger=log
    )
    await flash.start()
    await monitor.start()
    await Timer(HALF_PERIOD_NS, "ns")
    return SpiHarness(
        host=OcahSpiMasterSequence(bfm, checker), flash=flash, monitor=monitor, checker=checker
    )


def base_seed() -> int:
    """Runner-provided seed; the harness's one read of the seed variable."""
    return int(os.environ.get(_SEED_ENV, "1"), 0)


def scenario_rng(label: str) -> random.Random:
    """Seeded stream for one scenario, salted by ``label``."""
    return random.Random(OcahRng.salted_seed(base_seed(), label))


def negative_armed() -> bool:
    """Whether the must-fail knob of the run is set."""
    return bool(OcahKnobs.is_set(NEGATIVE_KNOB))


def random_page_span(rng: random.Random, *, max_len: int = 64) -> tuple[int, int]:
    """A random ``(addr, length)`` that stays inside one page of one sector."""
    length = rng.randint(1, max_len)
    sector = rng.randrange(0, FLASH_SIZE // SECTOR_SIZE)
    page = rng.randrange(0, SECTOR_SIZE // PAGE_SIZE)
    offset = rng.randrange(0, PAGE_SIZE - length + 1)
    return sector * SECTOR_SIZE + page * PAGE_SIZE + offset, length


def random_payload(rng: random.Random, length: int) -> bytes:
    """``length`` random bytes with at least one bit clear, so a program changes the array."""
    data = bytearray(rng.randbytes(length))
    if all(value == _ERASED for value in data):
        data[0] = 0x00
    return bytes(data)


def rejects(
    label: str,
    flash: OcahSpiFlash,
    action: Callable[[OcahSpiFlashChecker], object],
) -> bool:
    """Run ``action`` on a fail-fast checker with a silent logger; True when it raised.

    The probe checker owns no evidence of the test: the caller records the
    outcome under a ``CHK-SPI-NEG-*`` identifier on the test's checker.
    """
    quiet = logging.getLogger(f"cocotb.tb.ocah_spi_harness.negative.{label}")
    quiet.setLevel(logging.CRITICAL)
    probe = OcahSpiFlashChecker(name=f"negative.{label}", flash=flash, logger=quiet)
    try:
        action(probe)
    except OcahCheckerError:
        return True
    return False
