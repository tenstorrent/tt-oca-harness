# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared UART VIP selftest: frame formats and baud rates.

A seeded sample of frame formats (5..9 data bits, none, even, or odd
parity, 1, 1.5, or 2 stop bits), each at a seeded standard baud rate and
always including 8-N-1, is applied to every engine in turn. For each format
the device sends a seeded burst to the console and the console one to the
device; the reconstructed frames equal the driven ones, carry no flag, and
show the format's bit period on the wire. A sampler then runs at twice the
line rate and must not deliver the burst as clean frames. A probe checker
handed a wrong baud rate must reject the timing evidence.
"""

from __future__ import annotations

import itertools
import logging

import cocotb
from ocah_uart_vip import OcahUartParity
from ocah_uart_vip_harness import (
    STANDARD_BAUDS,
    build_stack,
    random_values,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_uart_format_test")

REQUIRED_IDS = (
    "CHK-UART-DATA",
    "CHK-UART-CLEAN",
    "CHK-UART-BAUD",
    "CHK-UART-NONVAC",
    "CHK-UART-BAUD-DETECT",
    "CHK-UART-NEG-BAUD",
)
ANCHOR = (8, OcahUartParity.NONE, 1.0)
SAMPLED_FORMATS = 6
BURST = 6


@cocotb.test()
async def ocah_uart_format_test(dut) -> None:
    rng = scenario_rng("format")
    space = [
        combo
        for combo in itertools.product((5, 6, 7, 8, 9), tuple(OcahUartParity), (1.0, 1.5, 2.0))
        if combo != ANCHOR
    ]
    formats = [ANCHOR] + rng.sample(space, SAMPLED_FORMATS)
    bauds = [rng.choice(STANDARD_BAUDS) for _ in formats]
    log.info("start: %d formats: %s", len(formats), list(zip(formats, bauds)))
    harness = await build_stack(dut, baud=bauds[0], required_ids=REQUIRED_IDS, log=log)
    checker = harness.checker

    for (bits, parity, stop_bits), baud in zip(formats, bauds):
        harness = await harness.configure(baud=baud, bits=bits, parity=parity, stop_bits=stop_bits)
        label = f"{bits}{parity.value[0].upper()}{stop_bits:g}@{baud}"
        d2h = random_values(rng, BURST, bits=bits)
        h2d = random_values(rng, BURST, bits=bits)
        before_d2h = len(harness.host.rx_frames())
        before_h2d = len(harness.device_rx.get_frames())

        await harness.device_tx.write(d2h)
        await harness.host.source.write(h2d)
        await harness.drain()

        checker.check_line(
            d2h,
            harness.host.rx_frames()[before_d2h:],
            baud=baud,
            label=f"d2h {label}",
            min_frames=BURST,
        )
        checker.check_line(
            h2d,
            harness.device_rx.get_frames()[before_h2d:],
            baud=baud,
            label=f"h2d {label}",
            min_frames=BURST,
        )

    harness = await harness.configure(
        baud=bauds[0], bits=8, parity=OcahUartParity.NONE, stop_bits=1
    )
    wrong_rate = 2 * harness.baud
    harness.host.sink.baud = wrong_rate
    burst = random_values(rng, BURST)
    before = len(harness.host.rx_frames())
    await harness.device_tx.write(burst)
    await harness.device_tx.wait()
    await harness.settle(4)
    harness.host.sink.baud = harness.baud
    checker.check_baud_mismatch(
        burst, harness.host.rx_frames()[before:], label=f"d2h sampler@{wrong_rate}"
    )
    await harness.settle(4)
    await harness.stop()

    good = harness.device_rx.get_frames()
    rejected = rejects(
        "baud", lambda probe: probe.check_baud(good, 3 * bauds[0], label="h2d wrong baud")
    )
    checker.expect_true("CHK-UART-NEG-BAUD", rejected, context="a wrong baud rate must be rejected")
    checker.finalize()
