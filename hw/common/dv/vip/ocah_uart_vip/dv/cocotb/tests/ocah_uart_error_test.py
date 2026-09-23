# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared UART VIP selftest: malformed frames are classified, not swallowed.

With even parity, the device sends good frames interleaved with a bad-stop
frame, an inverted-parity frame, a break, and a sub-half-bit glitch. The
console delivers every frame with its flags, the sampler's classification
sequence equals the driven one, each fault kind is counted once, the glitch
yields no frame, and the counters agree. The console then switches to
raising on flagged frames: a good frame reads, the bad frame raises and is
consumed, and the next good frame reads. The console's own bad-stop frame is
classified by the device sampler. A probe checker handed a classification
with one flag flipped must reject it.

``OCAH_UART_SELFTEST_NEGATIVE`` claims a clean frame as a break in the
expected classification so ``CHK-UART-CLASSIFY`` fails and the run must fail.
"""

from __future__ import annotations

import logging
from dataclasses import replace

import cocotb
from ocah_uart_vip import OcahUartError, OcahUartFrame, OcahUartParity
from ocah_uart_vip_harness import (
    STANDARD_BAUDS,
    build_stack,
    negative_armed,
    random_values,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_uart_error_test")

REQUIRED_IDS = (
    "CHK-UART-CLASSIFY",
    "CHK-UART-FRAMING-ERROR",
    "CHK-UART-PARITY-ERROR",
    "CHK-UART-BREAK",
    "CHK-UART-GLITCH",
    "CHK-UART-ERROR-COUNT",
    "CHK-UART-CONSOLE-FLAGS",
    "CHK-UART-CONSOLE-DATA",
    "CHK-UART-RAISE",
    "CHK-UART-RAISE-CONSUMED",
    "CHK-UART-STATS",
    "CHK-UART-NEG-CLASSIFY",
)
GLITCH_NS = 7
FAULT_FRAMES = 8


def _flipped(frames: list[OcahUartFrame], index: int) -> list[OcahUartFrame]:
    """``frames`` with the break flag of entry ``index`` inverted."""
    target = frames[index]
    return frames[:index] + [replace(target, is_break=not target.is_break)] + frames[index + 1 :]


@cocotb.test()
async def ocah_uart_error_test(dut) -> None:
    rng = scenario_rng("error")
    baud = rng.choice(STANDARD_BAUDS)
    good = random_values(rng, 9)
    negative = negative_armed()
    log.info("start: baud=%d even parity, negative=%s", baud, negative)
    harness = await build_stack(
        dut, baud=baud, required_ids=REQUIRED_IDS, log=log, parity=OcahUartParity.EVEN
    )
    host, device_tx, device_rx, tap, checker = (
        harness.host,
        harness.device_tx,
        harness.device_rx,
        harness.tap,
        harness.checker,
    )

    await device_tx.write([good[0]])
    await device_tx.inject_framing_error(good[1])
    await device_tx.write([good[2]])
    await device_tx.inject_parity_error(good[3])
    await device_tx.write([good[4]])
    await device_tx.send_break()
    await device_tx.write([good[5]])
    await device_tx.send_glitch(GLITCH_NS)
    await device_tx.write([good[6]])
    delivered = [await host.read_frame() for _ in range(FAULT_FRAMES)]
    await harness.drain()

    expected = device_tx.get_frames()
    if negative:
        log.warning(
            "NEGATIVE VALIDATION: a clean frame is claimed as a break; CHK-UART-CLASSIFY must fail"
        )
        expected = _flipped(expected, 0)
    observed = host.rx_frames()
    checker.check_classification(observed, expected, label="d2h")
    checker.check_classification(tap.get_rx_frames(), expected, label="tap_d2h")
    checker.check_glitches(
        host.sink.get_statistics(),
        1,
        frames_expected=FAULT_FRAMES,
        frames_observed=len(observed),
        label="d2h",
    )
    checker.check_error_counts(
        host.sink.get_statistics(),
        label="d2h",
        framing_errors=1,
        parity_errors=1,
        breaks=1,
        glitches=1,
    )
    checker.expect_equal(
        "CHK-UART-CONSOLE-FLAGS",
        [frame.flags for frame in delivered],
        [frame.flags for frame in expected],
        context="read_frame delivers the flags",
    )
    checker.expect_equal(
        "CHK-UART-CONSOLE-DATA",
        [frame.data for frame in delivered],
        [good[0], good[1], good[2], good[3], good[4], 0, good[5], good[6]],
        context="read_frame delivers the data of a flagged frame",
    )

    host.raise_on_frame_error = True
    await device_tx.write([good[7]])
    await device_tx.inject_framing_error(good[8])
    await device_tx.write([good[0]])
    first = await host.read_byte()
    raised = ""
    try:
        await host.read_byte()
    except OcahUartError as exc:
        raised = str(exc)
        log.info("raised as required: %s", exc)
    third = await host.read_byte()
    checker.expect_true(
        "CHK-UART-RAISE", "framing" in raised, context=f"first=0x{first:02x} message={raised!r}"
    )
    checker.expect_equal(
        "CHK-UART-RAISE-CONSUMED",
        (first, third),
        (good[7], good[0]),
        context="the frames around the raised one read in order",
    )

    await host.send_framing_error(good[2])
    await host.send_bytes([good[3]])
    await harness.drain()
    await harness.stop()
    checker.check_classification(device_rx.get_frames(), host.tx_frames(), label="h2d")
    checker.check_statistics(
        host.get_statistics(),
        {"bytes_received": FAULT_FRAMES + 3, "frame_errors": 4, "timeouts": 0},
        label="console",
    )
    checker.check_statistics(
        device_tx.get_statistics(),
        {"bytes_driven": 10, "framing_faults": 2, "parity_faults": 1, "breaks": 1, "glitches": 1},
        label="device_tx",
    )

    rejected = rejects(
        "classify",
        lambda probe: probe.check_classification(
            observed, _flipped(device_tx.get_frames()[:FAULT_FRAMES], 2), label="d2h"
        ),
    )
    checker.expect_true(
        "CHK-UART-NEG-CLASSIFY", rejected, context="a wrong classification must be rejected"
    )
    checker.finalize()
