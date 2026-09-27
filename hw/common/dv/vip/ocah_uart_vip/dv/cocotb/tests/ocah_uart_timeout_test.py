# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared UART VIP selftest: every console read is bounded and loses no data.

On a silent line ``read_byte`` raises, then returns ``None`` once raising is
off, each exactly the declared number of microseconds after it started.
``read_bytes`` asked for one frame more than the device sent times out at the
bound and the frames it took stay readable; ``read_line`` on text without a
newline times out and resumes once the newline arrives; ``expect`` raises at
the bound. A read with data present completes under its bound, and the
console's timeout counter equals the timeouts seen. A probe checker told a
completed read timed out must reject it.

``OCAH_UART_SELFTEST_NEGATIVE`` declares a bound one microsecond short for
the first read so ``CHK-UART-TIMEOUT-BOUND`` fails and the run must fail.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.utils import get_sim_time
from ocah_uart_vip import OcahUartError
from ocah_uart_vip_harness import (
    STANDARD_BAUDS,
    build_stack,
    frame_us,
    negative_armed,
    random_values,
    rejects,
    scenario_rng,
)

log = logging.getLogger("cocotb.tb.ocah_uart_timeout_test")

REQUIRED_IDS = (
    "CHK-UART-TIMEOUT",
    "CHK-UART-TIMEOUT-BOUND",
    "CHK-UART-NO-TIMEOUT",
    "CHK-UART-PARTIAL-KEPT",
    "CHK-UART-LINE-RESUMED",
    "CHK-UART-STATS",
    "CHK-UART-NEG-TIMEOUT",
)
TEXT = b"abc"


def _now() -> float:
    return float(get_sim_time("ns"))


@cocotb.test()
async def ocah_uart_timeout_test(dut) -> None:
    rng = scenario_rng("timeout")
    baud = rng.choice(STANDARD_BAUDS)
    bound_us = rng.choice((2, 3, 5)) * frame_us(baud)
    values = random_values(rng, 4)
    negative = negative_armed()
    log.info("start: baud=%d bound=%d us, negative=%s", baud, bound_us, negative)
    harness = await build_stack(
        dut, baud=baud, required_ids=REQUIRED_IDS, log=log, timeout_us=bound_us
    )
    host, device_tx, checker = harness.host, harness.device_tx, harness.checker

    started = _now()
    raised = False
    try:
        await host.read_byte()
    except OcahUartError as exc:
        raised = "timed out" in str(exc)
        log.info("raised as required: %s", exc)
    declared = bound_us - 1 if negative else bound_us
    if negative:
        log.warning(
            "NEGATIVE VALIDATION: the declared bound is one microsecond short; "
            "CHK-UART-TIMEOUT-BOUND must fail"
        )
    checker.check_timeout(
        timed_out=raised, elapsed_ns=_now() - started, timeout_us=declared, label="read_byte raise"
    )

    host.raise_on_timeout = False
    started = _now()
    value = await host.read_byte()
    checker.check_timeout(
        timed_out=value is None,
        elapsed_ns=_now() - started,
        timeout_us=bound_us,
        label="read_byte none",
    )

    await device_tx.write(values[:2])
    await device_tx.wait()
    started = _now()
    partial = await host.read_bytes(3)
    checker.check_timeout(
        timed_out=partial is None,
        elapsed_ns=_now() - started,
        timeout_us=bound_us,
        label="read_bytes short",
    )
    kept = await host.read_bytes(2)
    checker.expect_equal(
        "CHK-UART-PARTIAL-KEPT", kept, bytes(values[:2]), context="frames taken before a timeout"
    )

    await device_tx.write(TEXT)
    await device_tx.wait()
    started = _now()
    line = await host.read_line()
    checker.check_timeout(
        timed_out=line is None, elapsed_ns=_now() - started, timeout_us=bound_us, label="read_line"
    )
    await device_tx.write(b"\n")
    line = await host.read_line()
    checker.expect_equal(
        "CHK-UART-LINE-RESUMED", line, TEXT.decode(), context="the partial line completes"
    )

    host.raise_on_timeout = True
    started = _now()
    raised = False
    try:
        await host.expect("never")
    except OcahUartError as exc:
        raised = "timed out" in str(exc)
    checker.check_timeout(
        timed_out=raised, elapsed_ns=_now() - started, timeout_us=bound_us, label="expect"
    )

    await device_tx.write([values[2]])
    started = _now()
    value = await host.read_byte()
    elapsed = _now() - started
    checker.check_completed(timed_out=value is None, timeout_us=bound_us, label="read_byte data")
    checker.expect_equal(
        "CHK-UART-NO-TIMEOUT-DATA",
        value,
        values[2],
        context=f"elapsed_ns={round(elapsed)} bound_ns={bound_us * 1000}",
    )
    await harness.drain()
    await harness.stop()

    checker.check_statistics(
        host.get_statistics(),
        {"timeouts": 5, "bytes_received": 2 + len(TEXT) + 1 + 1, "lines_received": 1},
        label="console",
    )
    rejected = rejects(
        "timeout",
        lambda probe: probe.check_timeout(
            timed_out=False, elapsed_ns=bound_us * 1000, timeout_us=bound_us, label="probe"
        ),
    )
    checker.expect_true(
        "CHK-UART-NEG-TIMEOUT",
        rejected,
        context="a completed read claimed as a timeout must be rejected",
    )
    checker.finalize()
