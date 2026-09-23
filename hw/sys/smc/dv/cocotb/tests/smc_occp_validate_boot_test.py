# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""VALIDATE_AND_BOOT must hand the manifest address on to SEP, then stop.

The ROM must echo the address the controller recorded in its own scratch 8, set the
manifest-ready bit, and halt: a ROM that kept booting would pass a scratch-only check.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import ClockCycles
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
    SCRATCH_MANIFEST_ADDR,
    SCRATCH_PASS_FAIL,
    SCRATCH_POST_CODE,
    SCRATCH_STATUS_TO_SEP,
    SEP_STATUS_MANIFEST_READY_BIT,
    SMC_SRAM_BASE,
    TEST_FAIL,
    TEST_PASS,
    bus_activity,
    describe_post_code,
    format_activity,
    required_plusarg,
)

POLL_CYCLES = 2000
DEFAULT_POLL_ITERS = 4000
PROGRESS_EVERY = 200

HALT_SETTLE_CYCLES = 2000
HALT_WINDOW_CYCLES = 20_000
HALT_SAMPLE_CYCLES = 20
REQUIRED_EVIDENCE = ("CHK-OCCP-VALIDATE-BOOT",)


def _poll_iterations() -> tuple[int, str]:
    budget = cocotb.plusargs.get("rom_test_timeout")
    if budget is None:
        return DEFAULT_POLL_ITERS, f"default bound {DEFAULT_POLL_ITERS} polls"
    budget_ns = int(str(budget), 0)
    if budget_ns <= 0:
        raise AssertionError(f"+rom_test_timeout must be a positive ns value, got {budget!r}")
    interval = POLL_CYCLES * SMC_CLK_PERIOD_NS
    iters = max(1, -(-budget_ns // interval))
    return iters, f"+rom_test_timeout={budget_ns} ns / {interval} ns -> {iters} polls"


async def _expect_halted(dut, harness) -> set[int]:
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
            f"target ROM kept executing after publishing the manifest: retired PC left "
            f"{{{seen}}} for {current:#x} within {HALT_WINDOW_CYCLES} clk_smc_i. "
            f"VALIDATE_AND_BOOT hands the part to SEP; the ROM should not boot it.\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )
    return allowed


@dual_test(REQUIRED_EVIDENCE)
async def smc_occp_validate_boot_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    required_plusarg("rom_bin64", "smc_occp_validate_boot_test")
    controller_image = required_plusarg("bfm_rom_hex", "smc_occp_validate_boot_test")
    poll_iters, poll_source = _poll_iterations()

    seed = random_seed()
    cocotb.log.info(
        "smc_occp_validate_boot_test (RANDOM_SEED=%d): controller = %s; %s",
        seed,
        controller_image,
        poll_source,
    )

    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)

    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    baseline_activity = bus_activity(dut)

    # The controller reports first: it finishes once VALIDATE_AND_BOOT is acknowledged.
    ctrl_scratch0 = 0
    for iteration in range(poll_iters):
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)

        ctrl_scratch0 = await bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL)
        target_scratch0 = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)

        if ctrl_scratch0 == TEST_FAIL or target_scratch0 == TEST_FAIL:
            bfm_console.flush()
            dut_console.flush()
            post = await dut_csr.read("TARGET_POST_CODE_FAIL", SCRATCH_POST_CODE)
            raise AssertionError(
                f"smc_occp_validate_boot_test reported failure.\n"
                f"  target scratch0     = {target_scratch0:#010x}\n"
                f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
                f"  target POST         = {describe_post_code(post)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )
        if ctrl_scratch0 == TEST_PASS or target_scratch0 == TEST_PASS:
            break

        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "validate-boot in flight (poll %d/%d): ctrl=%#010x, bus [%s]",
                iteration,
                poll_iters,
                ctrl_scratch0,
                format_activity(bus_activity(dut)),
            )
    else:
        bfm_console.flush()
        dut_console.flush()
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        raise AssertionError(
            f"VALIDATE_AND_BOOT never completed within {poll_iters}x{POLL_CYCLES} "
            f"clk_smc_i ({poll_source}).\n"
            f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
            f"  target POST         = {describe_post_code(post)}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"controller firmware trace (last lines):\n{bfm_console.tail()}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    # Scratch 8 is valid only once the manifest-ready bit is set.
    ready_mask = 1 << SEP_STATUS_MANIFEST_READY_BIT
    scratch_9 = 0
    for _ in range(poll_iters):
        scratch_9 = await dut_csr.read("TARGET_SEP_STATUS", SCRATCH_STATUS_TO_SEP)
        if scratch_9 & ready_mask:
            break
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)
    else:
        dut_console.flush()
        raise AssertionError(
            f"target ROM never raised the manifest-ready bit after VALIDATE_AND_BOOT.\n"
            f"  scratch 9 = {scratch_9:#010x}, need bit {SEP_STATUS_MANIFEST_READY_BIT}\n"
            f"target firmware trace:\n{dut_console.tail()}"
        )

    manifest_offset = await dut_csr.read("TARGET_MANIFEST", SCRATCH_MANIFEST_ADDR)
    manifest_addr = manifest_offset + SMC_SRAM_BASE
    expected_addr = await bfm_csr.read("CTRL_MANIFEST", SCRATCH_MANIFEST_ADDR)

    if manifest_addr != expected_addr:
        bfm_console.flush()
        dut_console.flush()
        raise AssertionError(
            f"target published the wrong manifest address.\n"
            f"  target scratch 8    = {manifest_offset:#010x} (offset) "
            f"-> {manifest_addr:#010x} absolute\n"
            f"  controller sent     = {expected_addr:#010x}\n"
            f"  SMC_SRAM_BASE       = {SMC_SRAM_BASE:#010x}\n"
            f"controller firmware trace:\n{bfm_console.tail()}\n"
            f"target firmware trace:\n{dut_console.tail()}"
        )

    halted_pcs = await _expect_halted(dut, harness)

    bfm_console.flush()
    dut_console.flush()
    harness.dump_cpu_trace(logging.INFO)
    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)

    activity = bus_activity(dut)
    assert any(
        falls > base_falls for (_, falls, _), (_, base_falls, _) in zip(activity, baseline_activity)
    ), "no I3C channel saw an SCL fall, so VALIDATE_AND_BOOT never reached the target"

    cocotb.log.info(
        "CHK-OCCP-VALIDATE-BOOT: manifest %#010x echoed and ready bit set; ROM halted at %s. "
        "Final target POST %s",
        manifest_addr,
        ", ".join(f"{pc:#x}" for pc in sorted(halted_pcs)),
        describe_post_code(post),
    )
    cocotb.log.info("smc_occp_validate_boot_test PASS")
