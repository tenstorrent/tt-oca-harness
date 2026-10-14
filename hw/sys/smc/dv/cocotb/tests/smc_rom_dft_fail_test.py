# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The target ROM must stop, and say why, when BISR or MBIST reports a bad result.

Three failure modes share this module, selected by +dft_scenario:

    mem_repair_fail   repair completes but reports no success  -> scratch 15 0xBADC0FFE
    mbist_fail        MBIST completes but does not pass        -> scratch 15 0xDEADBEEF
    mbist_timeout     MBIST aborts without passing             -> scratch 15 0xDEADC0DE

Two things have to hold, and the second is what makes this more than a register check: the
ROM must record the right code in scratch 15, and it must then stay halted. A ROM that
recorded the failure and carried on booting would pass a scratch-15-only test while being
exactly the defect this is looking for.

The controller instance boots normally and is not gated on.

Halt is checked on the target's retired PC. A WFI loop is either one instruction or the
two-instruction `wfi; j` pair, so both a static PC and a two-PC cycle are accepted; a third
distinct PC means execution continued.

Plusargs:
    +rom_bin64=<image>        target production ROM               (required)
    +bfm_rom_hex=<image>      controller rom-mode image           (required)
    +dft_scenario=<name>      failure mode, see above             (required)
    +rom_test_timeout=<ns>    bound on reaching the status write  (default: DEFAULT_POLL_ITERS)
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_dft_status_driver import EXPECTED_STATUS, SmcDftStatusDriver
from env.smc_virt_console import VirtConsole
from smc_dual_base_test import (
    SMC_CLK_PERIOD_NS,
    DualCsr,
    SmcDualHarness,
    dual_test,
    random_seed,
)
from smc_occp_dual_defs import (
    CPU_RESET_VECTOR_ROM,
    SCRATCH_MBIST_STATUS,
    SCRATCH_POST_CODE,
    describe_post_code,
    required_plusarg,
)

POLL_CYCLES = 2000
DEFAULT_POLL_ITERS = 4000

# The register the ROM's early check reads (DFX_CTRL_STATUS_SMU_REG_ADDR in smc_rom_defs.h).
# Fields: mem_repair_done[0], mem_repair_success[1], mbist_done[4], mbist_pass[8],
# mbist_abort[12].
DFX_CTRL_STATUS_SMU = 0xC000_B800

# Halt observation. The settle lets the ROM reach WFI after writing scratch 15; the window
# is long enough that a boot that merely paused would be seen resuming.
HALT_SETTLE_CYCLES = 2000
HALT_WINDOW_CYCLES = 20_000
HALT_SAMPLE_CYCLES = 20
REQUIRED_EVIDENCE = ("CHK-ROM-DFT-FAIL",)


def _poll_iterations() -> tuple[int, str]:
    budget = cocotb.plusargs.get("rom_test_timeout")
    if budget is None:
        return DEFAULT_POLL_ITERS, f"default bound {DEFAULT_POLL_ITERS} polls"
    budget_ns = int(str(budget), 0)
    if budget_ns <= 0:
        raise AssertionError(f"+rom_test_timeout must be a positive ns value, got {budget!r}")
    interval = POLL_CYCLES * SMC_CLK_PERIOD_NS
    iters = max(1, int(-(-budget_ns // interval)))
    return iters, f"+rom_test_timeout={budget_ns} ns / {interval} ns -> {iters} polls"


async def _expect_halted(dut, harness, case: str) -> set[int]:
    """Require the target's retired PC to stay inside a one- or two-PC loop."""
    await ClockCycles(dut.clk_smc_i, HALT_SETTLE_CYCLES)

    allowed: set[int] = {int(dut.dut_wb_pc0.value)}
    elapsed = 0
    while elapsed < HALT_WINDOW_CYCLES:
        await ClockCycles(dut.clk_smc_i, HALT_SAMPLE_CYCLES)
        elapsed += HALT_SAMPLE_CYCLES
        current = int(dut.dut_wb_pc0.value)
        if current in allowed:
            continue
        if len(allowed) < 2:
            allowed.add(current)
            continue
        seen = ", ".join(f"{pc:#x}" for pc in sorted(allowed))
        raise AssertionError(
            f"{case}: target ROM did not stay halted after recording the failure. "
            f"Retired PC left {{{seen}}} for {current:#x} within {HALT_WINDOW_CYCLES} "
            f"clk_smc_i.\nCPU state:\n{harness.cpu_trace_report()}"
        )
    return allowed


@dual_test(REQUIRED_EVIDENCE)
async def smc_rom_dft_fail_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    required_plusarg("rom_bin64", "smc_rom_dft_fail_test")
    controller_image = required_plusarg("bfm_rom_hex", "smc_rom_dft_fail_test")
    scenario = required_plusarg("dft_scenario", "smc_rom_dft_fail_test")
    if scenario not in EXPECTED_STATUS:
        raise AssertionError(
            f"+dft_scenario={scenario!r} is not one of {', '.join(sorted(EXPECTED_STATUS))}"
        )
    poll_iters, poll_source = _poll_iterations()

    cocotb.log.info(
        "smc_rom_dft_fail_test (RANDOM_SEED=%d): scenario %s, expecting scratch 15 = %#010x; "
        "controller = %s; %s",
        random_seed(),
        scenario,
        EXPECTED_STATUS[scenario],
        controller_image,
        poll_source,
    )

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)
    driver = SmcDftStatusDriver(harness, "dut", dut_csr, dut.clk_smc_i)

    # dft_low keeps the target's six DFT lines at 0 across cold reset. The
    # DFX_CTRL_STATUS.STATUS_SMU fields are stickybits, so letting the idle passing posture
    # reach the register once would latch success/pass at 1 for the rest of the run.
    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True, dft_low=("dut",))

    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(dut_console.run())

    # Before the target's cores fetch. The ROM reads DFX_CTRL_STATUS early in boot and
    # treats an absent `done` as "check not required", so a result reported after
    # release_cpu() arrives too late to be seen at all.
    driver.report(scenario)

    # The ROM branches on this register, not on the pins, so record what it will actually
    # read. A value that does not match the reported scenario means the pins never reached
    # DFX_CTRL_STATUS and the scratch-15 result below would be meaningless.
    dfx = await dut_csr.read("DFX_CTRL_STATUS_SMU", DFX_CTRL_STATUS_SMU)
    cocotb.log.info(
        "DFX_CTRL_STATUS_SMU=%#010x (mem_repair done=%d success=%d, mbist done=%d pass=%d "
        "abort=%d)",
        dfx,
        (dfx >> 0) & 1,
        (dfx >> 1) & 1,
        (dfx >> 4) & 1,
        (dfx >> 8) & 1,
        (dfx >> 12) & 1,
    )

    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    try:
        status = await driver.wait_for_status(
            scenario, SCRATCH_MBIST_STATUS, poll_iters, POLL_CYCLES
        )
    except AssertionError as exc:
        dut_console.flush()
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        raise AssertionError(
            f"{scenario}: {exc}\n"
            f"  target POST = {describe_post_code(post)}\n"
            f"  target wb_pc0 = {int(dut.dut_wb_pc0.value):#x}\n"
            f"target firmware trace:\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        ) from exc

    halted_pcs = await _expect_halted(dut, harness, scenario)

    dut_console.flush()
    harness.dump_cpu_trace(logging.INFO)
    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)

    cocotb.log.info(
        "CHK-ROM-DFT-FAIL: %s recorded scratch 15 = %#010x and halted at %s. Final POST %s",
        scenario,
        status,
        ", ".join(f"{pc:#x}" for pc in sorted(halted_pcs)),
        describe_post_code(post),
    )
    cocotb.log.info("smc_rom_dft_fail_test (%s) PASS", scenario)
