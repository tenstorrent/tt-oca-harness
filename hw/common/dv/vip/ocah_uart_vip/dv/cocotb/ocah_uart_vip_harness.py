# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared setup for the UART VIP wire-harness selftests.

Two serial nets exist in ``tb_top.sv``: ``uart_h2d`` (host to device) and
``uart_d2h`` (device to host). The shared console host (``OcahUartConsole``)
drives the first and samples the second; a device-side pair made of the same
engines (``OcahUartMasterDriver`` on ``uart_d2h``, ``OcahUartLineMonitor`` on
``uart_h2d``) stands in for a DUT's UART. ``OcahUartMonitor`` taps both nets,
and one ``OcahUartChecker`` collects every ``CHK-*`` record of a test from
the driven and sampled frame histories.

Each selftest carries an in-band negative case: a second, fail-fast checker
with a silent logger receives a wrong expectation and must raise. The
``OCAH_UART_SELFTEST_NEGATIVE`` knob turns ``ocah_uart_data_test`` (a
corrupted expected byte list), ``ocah_uart_error_test`` (a clean frame
claimed as a break), and ``ocah_uart_timeout_test`` (a wrong declared bound)
into runs that must fail.

``clk`` is a free-running reference clock this module drives so the
simulator always holds a timed event while the engines bit-bang the lines.

The seed accessor and the salted scenario RNG live here: these selftests are
plain cocotb tests without a base test class.
"""

from __future__ import annotations

import logging
import math
import os
import random
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import Timer
from ocah_checker import OcahCheckerError
from ocah_lib import OcahKnobs, OcahRng
from ocah_uart_vip import (
    OcahUartChecker,
    OcahUartConsole,
    OcahUartLineMonitor,
    OcahUartMasterDriver,
    OcahUartMonitor,
    OcahUartParity,
    bit_period_ns,
    frame_periods,
)

__all__ = [
    "CLK_PERIOD_NS",
    "NEGATIVE_KNOB",
    "STANDARD_BAUDS",
    "UartHarness",
    "base_seed",
    "build_stack",
    "frame_us",
    "negative_armed",
    "random_values",
    "rejects",
    "scenario_rng",
]

CLK_PERIOD_NS = 100
NEGATIVE_KNOB = "OCAH_UART_SELFTEST_NEGATIVE"
STANDARD_BAUDS = (9600, 19200, 38400, 57600, 115200, 230400, 460800, 921600)
_SEED_ENV = "RANDOM_SEED"


@dataclass(frozen=True)
class UartHarness:
    """The bound stack of one selftest: the console host, the device engines, the tap, the checker."""

    host: OcahUartConsole
    device_tx: OcahUartMasterDriver
    device_rx: OcahUartLineMonitor
    tap: OcahUartMonitor
    checker: OcahUartChecker
    baud: int

    @property
    def bit_ns(self) -> int:
        return int(bit_period_ns(self.baud))

    async def settle(self, periods: float = 2) -> None:
        """Idle ``periods`` bit periods so samplers and the tap deliver what is in flight."""
        await Timer(max(1, round(self.bit_ns * periods)), "ns")

    async def drain(self) -> None:
        """Wait until both drivers idle, then settle."""
        await self.host.flush()
        await self.device_tx.wait()
        await self.settle()

    async def configure(
        self,
        *,
        baud: int | None = None,
        bits: int | None = None,
        parity: OcahUartParity | str | None = None,
        stop_bits: float | None = None,
    ) -> UartHarness:
        """Reconfigure every engine and return the harness view with the new baud."""
        if baud is not None:
            await self.host.set_baud(baud)
        self.host.configure(bits=bits, parity=parity, stop_bits=stop_bits)
        self.device_tx.configure(baud=baud, bits=bits, parity=parity, stop_bits=stop_bits)
        self.device_rx.configure(baud=baud, bits=bits, parity=parity, stop_bits=stop_bits)
        self.tap.configure(baud=baud, bits=bits, parity=parity, stop_bits=stop_bits)
        return UartHarness(
            host=self.host,
            device_tx=self.device_tx,
            device_rx=self.device_rx,
            tap=self.tap,
            checker=self.checker,
            baud=baud if baud is not None else self.baud,
        )

    async def stop(self) -> None:
        """Stop the tap and the device sampler; their histories survive.

        The swallowed-callback counts of the tap and both samplers are
        recorded on the test's checker, so a subscriber exception a monitor
        logged cannot pass.
        """
        await self.tap.stop()
        self.device_rx.stop()
        self.checker.expect_equal(
            "CHK-UART-MON-CALLBACKS",
            (
                self.tap.get_statistics()["callback_errors"],
                self.device_rx.get_statistics()["callback_errors"],
                self.host.sink.get_statistics()["callback_errors"],
            ),
            (0, 0, 0),
            context="subscriber exceptions the tap, the device sampler, and the host sampler swallowed",
        )


def frame_us(
    baud: int, *, bits: int = 8, parity: OcahUartParity = OcahUartParity.NONE, stop_bits: float = 1
) -> int:
    """Whole microseconds one frame occupies at ``baud``, rounded up."""
    return int(math.ceil(frame_periods(bits, parity, stop_bits) * bit_period_ns(baud) / 1000))


async def build_stack(
    dut: Any,
    *,
    baud: int,
    required_ids: tuple[str, ...],
    log: logging.Logger,
    bits: int = 8,
    parity: OcahUartParity | str = OcahUartParity.NONE,
    stop_bits: float = 1,
    timeout_us: int | None = None,
    raise_on_timeout: bool = True,
    raise_on_frame_error: bool = False,
) -> UartHarness:
    """Start the reference clock and attach the host, the device engines, the tap, and the checker.

    Drivers are constructed before the samplers of their nets, so every
    sampler sees the idle level from its first sample. The console's default
    timeout covers four frames at ``baud`` unless ``timeout_us`` is given.
    """
    cocotb.start_soon(Clock(dut.clk, CLK_PERIOD_NS, "ns").start())
    fmt: dict[str, Any] = {"baud": baud, "bits": bits, "parity": parity, "stop_bits": stop_bits}
    budget = (
        timeout_us
        if timeout_us is not None
        else 4
        * frame_us(baud, bits=bits, parity=OcahUartParity.coerce(parity), stop_bits=stop_bits)
    )
    device_tx = OcahUartMasterDriver(dut.uart_d2h, name="device.tx", **fmt)
    host = OcahUartConsole(
        dut.uart_h2d,
        dut.uart_d2h,
        dut.clk,
        name="host",
        timeout_us=budget,
        raise_on_timeout=raise_on_timeout,
        raise_on_frame_error=raise_on_frame_error,
        **fmt,
    )
    host.init_signals()
    device_rx = OcahUartLineMonitor(dut.uart_h2d, name="device.rx", **fmt)
    tap = OcahUartMonitor(dut.uart_h2d, dut.uart_d2h, dut.clk, name="tap", **fmt)
    checker = OcahUartChecker(name="ocah_uart_harness", required_ids=required_ids, logger=log)
    await tap.start()
    await Timer(CLK_PERIOD_NS, "ns")
    return UartHarness(
        host=host, device_tx=device_tx, device_rx=device_rx, tap=tap, checker=checker, baud=baud
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


def random_values(rng: random.Random, count: int, *, bits: int = 8) -> list[int]:
    """``count`` random frame values of ``bits`` bits; the first carries both 0 and 1 bits."""
    mask = (1 << bits) - 1
    values = [rng.getrandbits(bits) for _ in range(count)]
    if values and values[0] in (0, mask):
        values[0] = 0x15 & mask
    return values


def rejects(label: str, action: Callable[[OcahUartChecker], object]) -> bool:
    """Run ``action`` on a fail-fast checker with a silent logger; True when it raised.

    The probe checker owns no evidence of the test: the caller records the
    outcome under a ``CHK-UART-NEG-*`` identifier on the test's checker.
    """
    quiet = logging.getLogger(f"cocotb.tb.ocah_uart_harness.negative.{label}")
    quiet.setLevel(logging.CRITICAL)
    probe = OcahUartChecker(name=f"negative.{label}", logger=quiet)
    try:
        action(probe)
    except OcahCheckerError:
        return True
    return False
