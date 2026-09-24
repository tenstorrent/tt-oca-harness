# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Negative control: the converter's SVA are compiled into this build and fire.

The test stalls a cfg A read in its AHB address phase (HREADY low), then, in
the middle of a stalled cycle, deposits a different address into the
converter's latched request (``u_dut_a.req_addr_q``). HADDR changes inside the
stalled address phase, which ``AddrPhaseHeld_A`` in axi_lite_to_ahb.sv
forbids.

The testlist marks the leaf ``expect_fail``: it grades PASS only when the leaf
fails, and nothing on the Python side can fail it. The slave model tolerates
the one address change, the scoreboard is not consulted, every wait is bounded
and gives up with a warning, and a disturbance that could not be applied or
did not take effect is only logged. The only failure left is the assertion's
own report, so a build with the SVA compiled out, or a deposit the simulator
ignored, lets the leaf pass and grade FAIL.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import cocotb
from a2h_base_test import Bench
from cocotb.triggers import FallingEdge, RisingEdge
from models.ahb_lite_slave import HTRANS_NONSEQ, sample

READ_ADDR = 0x0000_5000
DEPOSIT_ADDR = 0x0000_5010
STALL_WAIT_CYCLES = 50
DONE_WAIT_CYCLES = 100


async def _within(dut: Any, pred: Callable[[], bool], max_cycles: int) -> bool:
    """True once ``pred()`` holds after a rising edge, False after ``max_cycles`` edges."""
    for _ in range(max_cycles):
        await RisingEdge(dut.clk)
        if pred():
            return True
    return False


@cocotb.test()
async def a2h_sva_live_test(dut: Any) -> None:
    tb = await Bench.create(dut, axi="port")
    env = tb.a
    env.model.allow_addr_change = True
    env.model.hold_hready_low(12)
    op = env.port.issue_read(READ_ADDR)

    def stalled() -> bool:
        return bool(
            sample(env.pin("ahb_htrans")) == HTRANS_NONSEQ
            and sample(env.pin("ahb_hready")) == 0
            and sample(env.pin("ahb_haddr")) == READ_ADDR
        )

    if not await _within(dut, stalled, STALL_WAIT_CYCLES):
        tb.log.warning(
            "negative control NOT applied (the read did not stall in its AHB address phase "
            "within %d cycles): the leaf passes and grades FAIL",
            STALL_WAIT_CYCLES,
        )
        return
    await FallingEdge(dut.clk)
    try:
        dut.u_dut_a.req_addr_q.value = DEPOSIT_ADDR
    except Exception as exc:
        tb.log.warning(
            "negative control NOT applied (deposit into u_dut_a.req_addr_q refused: %s): the "
            "leaf passes and grades FAIL",
            exc,
        )
        return
    tb.log.info(
        "deposited req_addr_q=%#010x mid-cycle inside the stalled address phase at "
        "HADDR=%#010x; AddrPhaseHeld_A must report on the next edge",
        DEPOSIT_ADDR,
        READ_ADDR,
    )
    if not await _within(dut, op.done.is_set, DONE_WAIT_CYCLES):
        tb.log.warning("the disturbed read did not complete within %d cycles", DONE_WAIT_CYCLES)
        return
    await tb.cycles(5)
    moved = env.model.addr_change_seen
    accepted = env.model.transfers[-1].haddr if env.model.transfers else None
    if moved and accepted == DEPOSIT_ADDR:
        tb.log.info(
            "negative control applied: HADDR moved %d time(s) inside the stalled address phase "
            "and the transfer was accepted at %#010x",
            moved,
            accepted,
        )
    else:
        tb.log.warning(
            "negative control NOT applied (HADDR moves seen=%d, accepted HADDR=%s): the leaf "
            "passes and grades FAIL",
            moved,
            None if accepted is None else f"{accepted:#010x}",
        )
