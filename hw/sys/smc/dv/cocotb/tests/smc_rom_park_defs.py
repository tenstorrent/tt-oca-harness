# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared definitions and checks for the SMC ROM hart 0 park interlock tests.

The SEP asks the target ROM to park hart 0 by writing PARK_REQ_VALUE to scratch 3. The ROM
parks between OCCP commands, and on every halt and trap: it writes back its L1 D-cache, sets
HART0_PARKED in scratch 9 and loops on wfi at smc_park_hart0_wfi.
"""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_cpu_trace_monitor import symbol_file_for_image
from smc_dual_base_test import SMC_CLK_PERIOD_NS
from smc_occp_dual_defs import SCRATCH_STATUS_TO_SEP, SMC_SRAM_BASE, peek_target_scratch
from smc_reg import SMC_CPU_CTRL_SCRATCH_3__REG_ADDR

# Must match SMC_SCRATCH_PARK_REQ / SMC_PARK_REQ_VALUE / SMC_SEP_STATUS_HART0_PARKED in
# smc_rom_defs.h.
SCRATCH_PARK_REQ = SMC_CPU_CTRL_SCRATCH_3__REG_ADDR
PARK_REQ_VALUE = 0x5052_4B31
HART0_PARKED = 1 << 4

# The park loop is `wfi` (4 bytes) then a jump back to it, so a parked hart retires only
# these two addresses.
PARK_LOOP_SYMBOL = "smc_park_hart0_wfi"
PARK_LOOP_BYTES = 4

# Parking follows a halt, AuthenticateImage or a request within a few hundred cycles.
PARK_WAIT_CYCLES = 50_000
HALT_SETTLE_CYCLES = 200
HALT_WINDOW_CYCLES = 4000
HALT_SAMPLE_CYCLES = 50

POLL_CYCLES = 2000
DEFAULT_POLL_ITERS = 4000


def poll_iterations() -> tuple[int, str]:
    budget = cocotb.plusargs.get("rom_test_timeout")
    if budget is None:
        return DEFAULT_POLL_ITERS, f"default bound {DEFAULT_POLL_ITERS} polls"
    budget_ns = int(str(budget), 0)
    if budget_ns <= 0:
        raise AssertionError(f"+rom_test_timeout must be a positive ns value, got {budget!r}")
    interval = POLL_CYCLES * SMC_CLK_PERIOD_NS
    iters = max(1, int(-(-budget_ns // interval)))
    return iters, f"+rom_test_timeout={budget_ns} ns / {interval} ns -> {iters} polls"


async def peek_target_sram(dut, addr: int) -> int:
    """Backdoor read of the 64-bit target SRAM word at `addr`; bypasses the CPU D-cache."""
    data, _ = await peek_target_scratch(dut, addr - SMC_SRAM_BASE)
    return data


def park_loop_pcs() -> frozenset[int]:
    """The two addresses a parked hart 0 retires, from the staged production ROM symbols."""
    rom = cocotb.plusargs.get("rom_bin64")
    sym = symbol_file_for_image("rom_bin64", str(rom)) if rom is not None else None
    if sym is None or not Path(sym).exists():
        raise AssertionError(
            f"no symbol file for +rom_bin64={rom!r}; cannot locate {PARK_LOOP_SYMBOL}"
        )
    # `nm -B -n` lines: "<addr> <type> <name>".
    for line in Path(sym).read_text().splitlines():
        parts = line.split()
        if len(parts) >= 3 and parts[2] == PARK_LOOP_SYMBOL:
            loop = int(parts[0], 16)
            return frozenset((loop, loop + PARK_LOOP_BYTES))
    raise AssertionError(f"{sym} has no {PARK_LOOP_SYMBOL}; the target ROM has no park interlock")


async def expect_parked(dut, harness, dut_csr, case: str) -> int:
    """Wait for HART0_PARKED, then require hart 0 to stay in the park loop."""
    scratch_9 = 0
    for _ in range(PARK_WAIT_CYCLES // HALT_SAMPLE_CYCLES):
        scratch_9 = await dut_csr.read("TARGET_SEP_STATUS", SCRATCH_STATUS_TO_SEP)
        if scratch_9 & HART0_PARKED:
            break
        await ClockCycles(dut.clk_smc_i, HALT_SAMPLE_CYCLES)
    else:
        raise AssertionError(
            f"{case}: HART0_PARKED not set within {PARK_WAIT_CYCLES} cycles; "
            f"scratch 9 = {scratch_9:#010x}, "
            f"wb_pc0 = {int(dut.dut_wb_pc0.value):#x}\nCPU state:\n{harness.cpu_trace_report()}"
        )

    loop_pcs = park_loop_pcs()
    await ClockCycles(dut.clk_smc_i, HALT_SETTLE_CYCLES)
    elapsed = 0
    while elapsed < HALT_WINDOW_CYCLES:
        pc = int(dut.dut_wb_pc0.value)
        if pc not in loop_pcs:
            raise AssertionError(
                f"{case}: HART0_PARKED is set but hart 0 retired {pc:#x}, not the park loop "
                f"{sorted(hex(p) for p in loop_pcs)}\nCPU state:\n{harness.cpu_trace_report()}"
            )
        await ClockCycles(dut.clk_smc_i, HALT_SAMPLE_CYCLES)
        elapsed += HALT_SAMPLE_CYCLES
    return scratch_9
