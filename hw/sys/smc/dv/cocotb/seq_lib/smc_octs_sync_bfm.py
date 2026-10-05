# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS dual-chiplet sync helpers for the SMC testbench.

Implements the OCTS PRIMARY/SECONDARY pad protocol on pads 55/56:
  * PRIMARY: DUT drives tb_octs_sync_load_from_dut / tb_octs_cnt_credit_from_dut
  * SECONDARY: TB injects tb_octs_sync_load_ext / tb_octs_cnt_credit_ext

Credit must never precede sync_load (RTL ExpectedCountValid_A).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge


async def count_rising_edges(signal, clk, max_cycles: int) -> int:
    """Count rising edges on ``signal`` over ``max_cycles`` of ``clk``."""
    edges = 0
    prev = int(signal.value) if signal.value.is_resolvable else 0
    for _ in range(max_cycles):
        await RisingEdge(clk)
        if not signal.value.is_resolvable:
            continue
        cur = int(signal.value)
        if prev == 0 and cur == 1:
            edges += 1
        prev = cur
    return edges


async def pulse_high(signal, clk, width_cycles: int, idle_cycles: int = 2) -> None:
    """Drive ``signal`` idle-low, then high for ``width_cycles``, then low."""
    signal.value = 0
    await ClockCycles(clk, idle_cycles)
    signal.value = 1
    await ClockCycles(clk, width_cycles)
    signal.value = 0
    await ClockCycles(clk, idle_cycles)


async def drive_secondary_sync_then_credits(
    dut,
    clk,
    *,
    pulse_width: int = 4,
    num_credits: int = 2,
    credit_gap_cycles: int = 20,
) -> None:
    """Ordered secondary inject: sync_load first, then credit pulses."""
    assert hasattr(dut, "tb_octs_sync_load_ext"), "tb_octs_sync_load_ext missing"
    assert hasattr(dut, "tb_octs_cnt_credit_ext"), "tb_octs_cnt_credit_ext missing"

    dut.tb_octs_cnt_credit_ext.value = 0
    await pulse_high(dut.tb_octs_sync_load_ext, clk, pulse_width)

    for _ in range(num_credits):
        await ClockCycles(clk, credit_gap_cycles)
        await pulse_high(dut.tb_octs_cnt_credit_ext, clk, pulse_width)

    dut.tb_octs_sync_load_ext.value = 0
    dut.tb_octs_cnt_credit_ext.value = 0
    cocotb.log.info(
        "OCTS secondary inject done: sync + %d credits (pulse_width=%d)",
        num_credits,
        pulse_width,
    )
