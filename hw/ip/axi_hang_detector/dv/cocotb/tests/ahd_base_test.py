# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared bench helpers for the AXI Hang Detector IP-level cocotb tests.

The IP has no CSR block of its own (config lives in cpu_ctrl at the SMC level),
so configuration is driven directly as wires on ``axi_hang_detector_tb_top``:
``enable_i``, ``irq_en_i``, ``irq_test_i``, ``threshold_i``. These helpers
provide clock/reset bring-up, an idle-init routine, the config drivers, and the
snoop stimulus that drives the monitored-bus probes the detector watches.

Expected behaviour is taken from ``hw/ip/axi_hang_detector/README.md``.
"""

from __future__ import annotations

import cocotb
from cocotb.clock import Clock
from cocotb.triggers import ClockCycles, RisingEdge

CLK_PERIOD_NS = 10


async def start_dut_clk(dut, clock_period_ns: int = CLK_PERIOD_NS) -> None:
    cocotb.start_soon(Clock(dut.clk, clock_period_ns, "ns").start())


async def reset_dut(dut) -> None:
    dut.rst_n.value = 0
    await ClockCycles(dut.clk, 10)
    dut.rst_n.value = 1
    await ClockCycles(dut.clk, 10)


def idle_snoop(dut) -> None:
    """Hold the monitored bus idle so no transaction is outstanding."""
    dut.snoop_aw_valid_i.value = 0
    dut.snoop_aw_ready_i.value = 0
    dut.snoop_w_valid_i.value = 0
    dut.snoop_b_valid_i.value = 0
    dut.snoop_b_ready_i.value = 0
    dut.snoop_ar_valid_i.value = 0
    dut.snoop_ar_ready_i.value = 0
    dut.snoop_r_valid_i.value = 0
    dut.snoop_r_ready_i.value = 0
    dut.snoop_r_last_i.value = 0


def init_dut(dut) -> None:
    """Drive all DUT inputs to a known idle state (call before starting clock)."""
    dut.clk.value = 0
    dut.rst_n.value = 0

    # Config wires idle (detector disabled)
    dut.enable_i.value = 0
    dut.irq_en_i.value = 0
    dut.irq_test_i.value = 0
    dut.threshold_i.value = 0

    idle_snoop(dut)


async def setup_dut(dut) -> None:
    """Convenience: init -> start clock -> reset."""
    init_dut(dut)
    await start_dut_clk(dut)
    await reset_dut(dut)


async def wait_for_irq(dut, max_cycles: int):
    """Advance up to max_cycles; return the cycle irq_o first asserts, else None."""
    for i in range(1, max_cycles + 1):
        await RisingEdge(dut.clk)
        if int(dut.irq_o.value) == 1:
            return i
    return None


# ---------------------------------------------------------------------------
# Configuration drivers (wire-driven; mirror the cpu_ctrl register fields)
# ---------------------------------------------------------------------------
async def configure(dut, threshold: int, enable: bool = True, irq_en: bool = True) -> None:
    """Set the timeout threshold and enable/irq_en. Takes effect on the next edge."""
    dut.threshold_i.value = threshold
    dut.enable_i.value = 1 if enable else 0
    dut.irq_en_i.value = 1 if irq_en else 0
    await RisingEdge(dut.clk)


async def set_threshold(dut, threshold: int) -> None:
    """Reprogram just the threshold (for live-reconfig tests)."""
    dut.threshold_i.value = threshold
    await RisingEdge(dut.clk)


async def set_irq_test(dut, value: int) -> None:
    """Drive CTRL.irq_test (forces irq high when enable & irq_en are set)."""
    dut.irq_test_i.value = value
    await RisingEdge(dut.clk)


# ---------------------------------------------------------------------------
# Snoop stimulus (drives the monitored-bus probes the detector watches).
# The snoop counts a transaction outstanding on the *rising edge* of
# aw_valid/ar_valid (ready not required); it is completed by a b handshake
# (writes) or an r handshake with r_last (reads).
# ---------------------------------------------------------------------------
async def issue_read(dut) -> None:
    """One outstanding read: a single rising edge on ar_valid (no ready needed)."""
    dut.snoop_ar_valid_i.value = 1
    await RisingEdge(dut.clk)
    dut.snoop_ar_valid_i.value = 0


async def complete_read(dut) -> None:
    """Complete one read: r_valid & r_ready & r_last for one cycle."""
    dut.snoop_r_valid_i.value = 1
    dut.snoop_r_ready_i.value = 1
    dut.snoop_r_last_i.value = 1
    await RisingEdge(dut.clk)
    dut.snoop_r_valid_i.value = 0
    dut.snoop_r_ready_i.value = 0
    dut.snoop_r_last_i.value = 0


async def issue_write(dut) -> None:
    """One outstanding write: a single rising edge on aw_valid (no ready needed)."""
    dut.snoop_aw_valid_i.value = 1
    await RisingEdge(dut.clk)
    dut.snoop_aw_valid_i.value = 0


async def complete_write(dut) -> None:
    """Complete one write: b_valid & b_ready for one cycle."""
    dut.snoop_b_valid_i.value = 1
    dut.snoop_b_ready_i.value = 1
    await RisingEdge(dut.clk)
    dut.snoop_b_valid_i.value = 0
    dut.snoop_b_ready_i.value = 0
