# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared UART VIP selftest: full-duplex data at a standard baud rate.

The console sends a seeded byte burst to the device while the device sends a
seeded burst followed by a text line to the console, both at one seeded
standard baud rate. Every frame reconstructed on each net equals the frame
driven onto it, carries no flag, and shows the configured bit period on the
wire; the console returns the device's bytes and line through ``read_bytes``
and ``read_line``; the passive tap sees the same frames; and every
component's counters agree with the traffic. A probe checker handed a
corrupted expected burst must reject it.

``OCAH_UART_SELFTEST_NEGATIVE`` corrupts the expected burst handed to the
test's own checker so ``CHK-UART-DATA`` fails and the run must fail.
"""

from __future__ import annotations

import logging

import cocotb
from ocah_uart_vip_harness import (
    STANDARD_BAUDS,
    build_stack,
    negative_armed,
    random_values,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_uart_data_test")

REQUIRED_IDS = (
    "CHK-UART-IDLE-HIGH",
    "CHK-UART-DATA",
    "CHK-UART-CLEAN",
    "CHK-UART-BAUD",
    "CHK-UART-NONVAC",
    "CHK-UART-CONSOLE-RX",
    "CHK-UART-CONSOLE-LINE",
    "CHK-UART-STATS",
    "CHK-UART-NEG-DATA",
)
LINE = b"ready\n"


def _corrupted(values: list[int]) -> list[int]:
    """``values`` with one bit of its first entry flipped."""
    return [values[0] ^ 0x01] + values[1:]


@cocotb.test()
async def ocah_uart_data_test(dut) -> None:
    rng = scenario_rng("data")
    baud = rng.choice(STANDARD_BAUDS)
    h2d = random_values(rng, rng.randint(8, 24))
    d2h = random_values(rng, rng.randint(8, 24))
    d2h_all = d2h + list(LINE)
    negative = negative_armed()
    log.info(
        "start: baud=%d h2d=%d frames d2h=%d frames + %r, negative=%s",
        baud,
        len(h2d),
        len(d2h),
        LINE,
        negative,
    )
    harness = await build_stack(dut, baud=baud, required_ids=REQUIRED_IDS, log=log)
    host, device_tx, device_rx, tap, checker = (
        harness.host,
        harness.device_tx,
        harness.device_rx,
        harness.tap,
        harness.checker,
    )

    await host.send_bytes(h2d)
    await device_tx.write(d2h_all)
    received = await host.read_bytes(len(d2h))
    line = await host.read_line()
    await harness.drain()
    await harness.stop()

    checker.check_idle_high(device_rx.initial_level, label="h2d")
    checker.check_idle_high(host.sink.initial_level, label="d2h")
    expected_h2d = _corrupted(h2d) if negative else h2d
    if negative:
        log.warning(
            "NEGATIVE VALIDATION: the expected host-to-device burst is corrupted; "
            "CHK-UART-DATA must fail"
        )
    checker.check_line(
        expected_h2d, device_rx.get_frames(), baud=baud, label="h2d", min_frames=len(h2d)
    )
    checker.check_line(d2h_all, host.rx_frames(), baud=baud, label="d2h", min_frames=len(d2h_all))
    checker.expect_equal(
        "CHK-UART-CONSOLE-RX", received, bytes(d2h), context="read_bytes returned the burst"
    )
    checker.expect_equal(
        "CHK-UART-CONSOLE-LINE", line, LINE[:-1].decode(), context="read_line returned the text"
    )
    checker.check_data(h2d, tap.get_tx_frames(), label="tap_h2d")
    checker.check_data(d2h_all, tap.get_rx_frames(), label="tap_d2h")
    checker.check_statistics(
        host.get_statistics(),
        {
            "bytes_sent": len(h2d),
            "bytes_received": len(d2h_all),
            "lines_received": 1,
            "timeouts": 0,
            "frame_errors": 0,
        },
        label="console",
    )
    checker.check_statistics(
        device_tx.get_statistics(), {"bytes_driven": len(d2h_all)}, label="device_tx"
    )
    checker.check_statistics(
        device_rx.get_statistics(),
        {"bytes_sampled": len(h2d), "framing_errors": 0, "glitches": 0, "callback_errors": 0},
        label="device_rx",
    )
    checker.check_statistics(
        tap.get_statistics(),
        {
            "tx_bytes_observed": len(h2d),
            "rx_bytes_observed": len(d2h_all),
            "tx_frame_errors": 0,
            "rx_frame_errors": 0,
            "callback_errors": 0,
        },
        label="tap",
    )

    frames = device_rx.get_frames()
    rejected = rejects("data", lambda probe: probe.check_data(_corrupted(h2d), frames, label="h2d"))
    checker.expect_true(
        "CHK-UART-NEG-DATA", rejected, context="a wrong expected burst must be rejected"
    )
    checker.finalize()
