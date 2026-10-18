# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared setup for the SPI VIP wire-harness selftests.

One single-SPI connection exists in ``tb_top.sv`` (``spi_cs_n``, ``spi_sclk``,
``spi_mosi``, ``spi_miso``, and ``spi_miso_oe``, the device's MISO drive
enable that the monitor taps). The shared controller engine
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

import hashlib
import logging
import os
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
    "build_lane_stack",
    "build_stack",
    "negative_armed",
    "random_page_span",
    "random_payload",
    "rejects",
    "ScenarioRng",
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
# Every checker grades against these constants, not against the device under
# test, so a device that loses its configured identifier or status register 2
# fails the identifier and status evidence.
_CONFIG_GOLDENS = {"jedec_id": JEDEC_ID, "status_reg2": STATUS_REG2, "flash_size": FLASH_SIZE}
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
        A device frame still open at stop raises.
        """
        await self.monitor.stop()
        await self.flash.stop(require_closed=True)
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
        miso_oe=dut.spi_miso_oe,
        name="harness_flash",
        jedec_id=JEDEC_ID,
        flash_size=FLASH_SIZE,
        status_reg2=STATUS_REG2,
    )
    if preload is not None:
        flash.preload(preload)
    flash.init_signals()
    bfm = OcahSpiMasterBfm.from_prefix(
        dut,
        PREFIX,
        name="harness_host",
        half_period_ns=HALF_PERIOD_NS,
        miso_oe=dut.spi_miso_oe,
    )
    bfm.init_signals()
    monitor = OcahSpiMonitor(
        dut.spi_cs_n,
        dut.spi_sclk,
        mosi=dut.spi_mosi,
        miso=dut.spi_miso,
        miso_oe=dut.spi_miso_oe,
        name="harness_monitor",
    )
    checker = OcahSpiFlashChecker(
        name="ocah_spi_harness",
        flash=flash,
        required_ids=required_ids,
        logger=log,
        **_CONFIG_GOLDENS,
    )
    await flash.start()
    await monitor.start()
    await Timer(HALF_PERIOD_NS, "ns")
    return SpiHarness(
        host=OcahSpiMasterSequence(bfm, checker), flash=flash, monitor=monitor, checker=checker
    )


async def build_lane_stack(
    dut: Any,
    *,
    required_ids: Iterable[str],
    log: logging.Logger,
) -> SpiHarness:
    """Attach the controller, the four-lane device, the monitor and the checker to ``spi4_*``.

    The device runs ``mode="quad_io"``; the monitor taps every lane and output
    enable, so the output-enable checks run.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())
    flash = OcahSpiFlash(
        dut.spi4_cs_n,
        dut.spi4_sclk,
        dq_out=dut.spi4_sd_out,
        dq_in=dut.spi4_sd_in,
        name="harness_lane_flash",
        mode="quad_io",
        jedec_id=JEDEC_ID,
        flash_size=FLASH_SIZE,
        status_reg2=STATUS_REG2,
    )
    flash.init_signals()
    bfm = OcahSpiMasterBfm(
        dut.spi4_cs_n,
        dut.spi4_sclk,
        None,
        None,
        name="harness_lane_host",
        half_period_ns=HALF_PERIOD_NS,
        sd_out=dut.spi4_sd_out,
        sd_oe=dut.spi4_sd_oe,
        sd_in=dut.spi4_sd_in,
        cs_oe=dut.spi4_cs_oe,
        sck_oe=dut.spi4_sck_oe,
    )
    bfm.init_signals()
    monitor = OcahSpiMonitor(
        dut.spi4_cs_n,
        dut.spi4_sclk,
        sd_out=dut.spi4_sd_out,
        sd_oe=dut.spi4_sd_oe,
        sd_in=dut.spi4_sd_in,
        cs_oe=dut.spi4_cs_oe,
        sck_oe=dut.spi4_sck_oe,
        name="harness_lane_monitor",
    )
    checker = OcahSpiFlashChecker(
        name="ocah_spi_harness",
        flash=flash,
        required_ids=required_ids,
        logger=log,
        **_CONFIG_GOLDENS,
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


class ScenarioRng:
    """Seed-reproducible stimulus stream: SHA-256 in counter mode over the seed.

    A failing selftest replays with the same seed, so the stimulus is a pure
    function of it, stable across hosts and Python versions. It is not a
    CSPRNG: the stream is predictable from the seed by design. Never use it
    for a key, token, nonce, or any value that leaves the simulation.
    """

    def __init__(self, seed: int) -> None:
        self._seed = int(seed) & 0xFFFF_FFFF_FFFF_FFFF
        self._counter = 0
        self._buf = b""

    def randbytes(self, n: int) -> bytes:
        """``n`` bytes of the stream."""
        while len(self._buf) < n:
            self._buf += hashlib.sha256(
                self._seed.to_bytes(8, "little") + self._counter.to_bytes(8, "little")
            ).digest()
            self._counter += 1
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def getrandbits(self, k: int) -> int:
        """``k`` bits of the stream."""
        if k <= 0:
            raise ValueError("getrandbits: k must be positive")
        return int.from_bytes(self.randbytes((k + 7) // 8), "little") & ((1 << k) - 1)

    def randrange(self, start: int, stop: int | None = None) -> int:
        """Uniform in ``[start, stop)``, or ``[0, start)`` with one argument; no modulo bias."""
        if stop is None:
            start, stop = 0, start
        width = stop - start
        if width <= 0:
            raise ValueError(f"randrange: empty range [{start}, {stop})")
        bits = (width - 1).bit_length() or 1
        while True:
            value = self.getrandbits(bits)
            if value < width:
                return start + value

    def randint(self, low: int, high: int) -> int:
        """Uniform in ``[low, high]``."""
        return self.randrange(low, high + 1)

    def choice(self, seq):
        """One element of ``seq``."""
        if not seq:
            raise IndexError("choice: empty sequence")
        return seq[self.randrange(len(seq))]


def scenario_rng(label: str) -> ScenarioRng:
    """Seeded stream for one scenario, salted by ``label``."""
    return ScenarioRng(OcahRng.salted_seed(base_seed(), label))


def negative_armed() -> bool:
    """Whether the must-fail knob of the run is set."""
    return bool(OcahKnobs.is_set(NEGATIVE_KNOB))


def random_page_span(rng: ScenarioRng, *, max_len: int = 64) -> tuple[int, int]:
    """A random ``(addr, length)`` that stays inside one page of one sector."""
    length = rng.randint(1, max_len)
    sector = rng.randrange(0, FLASH_SIZE // SECTOR_SIZE)
    page = rng.randrange(0, SECTOR_SIZE // PAGE_SIZE)
    offset = rng.randrange(0, PAGE_SIZE - length + 1)
    return sector * SECTOR_SIZE + page * PAGE_SIZE + offset, length


def random_payload(rng: ScenarioRng, length: int) -> bytes:
    """``length`` random bytes with at least one bit clear, so a program changes the array."""
    data = bytearray(rng.randbytes(length))
    if all(value == _ERASED for value in data):
        data[0] = 0x00
    return bytes(data)


def rejects(
    label: str,
    flash: OcahSpiFlash,
    action: Callable[[OcahSpiFlashChecker], object],
    *,
    check_id: str,
) -> bool:
    """Run ``action`` on a fail-fast checker with a silent logger; True when it raised on ``check_id``.

    Only a failure of the rule ``check_id`` counts: a probe that raises on
    another rule returns False. The probe checker owns no evidence
    of the test: the caller records the outcome under a ``CHK-SPI-NEG-*``
    identifier on the test's checker.
    """
    quiet = logging.getLogger(f"cocotb.tb.ocah_spi_harness.negative.{label}")
    quiet.setLevel(logging.CRITICAL)
    probe = OcahSpiFlashChecker(
        name=f"negative.{label}", flash=flash, logger=quiet, **_CONFIG_GOLDENS
    )
    try:
        action(probe)
    except OcahCheckerError as exc:
        return str(exc).startswith(f"{check_id} ")
    return False
