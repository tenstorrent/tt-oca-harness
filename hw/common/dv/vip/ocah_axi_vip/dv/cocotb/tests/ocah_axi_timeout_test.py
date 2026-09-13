# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared AXI VIP selftest: every blocking master operation is bounded.

A master built without a timeout carries the package default (or the
``+OCAH_AXI_TIMEOUT_NS`` plusarg), a completing transfer passes under it, and
a responder that withholds READY beyond the bound makes the operation time
out: with ``allow_timeout=True`` the result reports ``timed_out`` and
``RESP_TIMEOUT`` within the bound, and without it the operation raises. The
stall is released afterwards and a plain transfer completes. The AXI4 stack
(s_axi) and the AXI4-Lite stack (l_axi) run the same checks.
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_TIMEOUT, default_timeout_ns
from ocah_axi_vip_harness import (
    CLK_PERIOD_NS,
    build_full_stack,
    build_lite_stack,
    scenario_rng,
    start_clock_reset,
)
from ocah_checker import OcahChecker

log = logging.getLogger("cocotb.tb.ocah_axi_timeout_test")

CHK_DEFAULT = "CHK-AXI-TIMEOUT-DEFAULT"
CHK_COMPLETES = "CHK-AXI-TIMEOUT-COMPLETES"
CHK_OBSERVED = "CHK-AXI-TIMEOUT-OBSERVED"
CHK_BOUND = "CHK-AXI-TIMEOUT-BOUND"
CHK_RAISES = "CHK-AXI-TIMEOUT-RAISES"
CHK_RECOVERS = "CHK-AXI-TIMEOUT-RECOVERS"

# The shortened bound the stalled transfers run under, and a READY stall that
# outlasts it so the bound, not the responder, ends the wait.
SHORT_TIMEOUT_CYCLES = 200
SHORT_TIMEOUT_NS = SHORT_TIMEOUT_CYCLES * CLK_PERIOD_NS
STALL_CYCLES = 4 * SHORT_TIMEOUT_CYCLES
# Cycles for the released responder to retire the abandoned transfers.
DRAIN_CYCLES = 64
WORD_BYTES = 4


async def check_stack(
    dut: Any, checker: OcahChecker, *, side: str, master: Any, slave: Any, rng: Any
) -> None:
    """Run the default, observed-timeout, raising, and recovery checks on one stack."""
    seq = master.sequence
    addr = rng.randrange(0, 2**12) * WORD_BYTES
    data = rng.getrandbits(32)
    context = f"side={side} addr=0x{addr:08x}"

    stats = seq.get_statistics()
    checker.expect_equal(CHK_DEFAULT, stats["timeout_ns"], default_timeout_ns(), context=context)
    checker.expect_true(f"{CHK_DEFAULT}-FINITE", stats["timeout_ns"] > 0, context=context)

    wres = await seq.write_result(addr, data)
    rres = await seq.read_result(addr)
    checker.expect_true(
        CHK_COMPLETES,
        wres.ok and rres.ok and rres.data == data,
        context=f"{context} wresp={wres.resp} rresp={rres.resp} data=0x{rres.data:08x}",
    )

    seq.configure(timeout_ns=SHORT_TIMEOUT_NS)
    slave.sequence.enable_backpressure(channels=("aw", "w"), stall_cycles=STALL_CYCLES)
    started_ns = get_sim_time("ns")
    tres = await seq.write_result(addr, data ^ 0xFFFF_FFFF, allow_timeout=True)
    elapsed_ns = get_sim_time("ns") - started_ns
    checker.expect_timeout(
        CHK_OBSERVED, timed_out=tres.timed_out, timeout_ns=SHORT_TIMEOUT_NS, context=context
    )
    checker.expect_equal(f"{CHK_OBSERVED}-RESP", tres.resp, RESP_TIMEOUT, context=context)
    checker.expect_true(f"{CHK_OBSERVED}-NOT-OK", tres.ok is False, context=context)
    checker.expect_true(
        CHK_BOUND,
        elapsed_ns <= SHORT_TIMEOUT_NS + 2 * CLK_PERIOD_NS,
        context=f"{context} elapsed_ns={elapsed_ns} bound_ns={SHORT_TIMEOUT_NS}",
    )

    slave.sequence.enable_backpressure(channels=("ar",), stall_cycles=STALL_CYCLES)
    raised = False
    try:
        await seq.read_result(addr)
    except AssertionError as exc:
        raised = "timed out" in str(exc)
        log.info("%s: raised as required: %s", side, exc)
    checker.expect_true(CHK_RAISES, raised, context=context)

    slave.sequence.disable_backpressure()
    await ClockCycles(dut.clk, DRAIN_CYCLES)
    seq.configure(timeout_ns=default_timeout_ns())
    rres = await seq.read_result(addr)
    checker.expect_true(
        CHK_RECOVERS,
        rres.ok and rres.data == (data ^ 0xFFFF_FFFF),
        context=f"{context} rresp={rres.resp} data=0x{rres.data:08x}",
    )


@cocotb.test()
async def ocah_axi_timeout_test(dut: Any) -> None:
    """Default bound, observed timeout, raising timeout, and recovery on both stacks."""
    await start_clock_reset(dut)
    rng = scenario_rng("timeout")
    checker = OcahChecker(
        name="ocah_axi_timeout",
        fail_fast=False,
        logger=log,
        required_ids=(
            CHK_DEFAULT,
            CHK_COMPLETES,
            CHK_OBSERVED,
            CHK_BOUND,
            CHK_RAISES,
            CHK_RECOVERS,
        ),
    )
    log.info("=" * 70)
    log.info(
        "AXI master timeout policy: default=%d ns, shortened bound=%d ns, stall=%d cycles",
        default_timeout_ns(),
        SHORT_TIMEOUT_NS,
        STALL_CYCLES,
    )
    log.info("=" * 70)

    full_master, full_slave = build_full_stack(dut, timeout_ns=None)
    await full_master.start()
    await check_stack(dut, checker, side="axi4", master=full_master, slave=full_slave, rng=rng)

    lite_master, lite_slave = build_lite_stack(dut, timeout_ns=None)
    await lite_master.start()
    await check_stack(dut, checker, side="axi4_lite", master=lite_master, slave=lite_slave, rng=rng)

    checker.finalize()
