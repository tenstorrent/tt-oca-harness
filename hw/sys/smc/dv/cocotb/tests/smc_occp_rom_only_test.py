# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared driver for the rom-only OCCP family: controller firmware drives, target ROM answers.

    u_dut  the OCCP *target*     -- the real production boot ROM
    u_bfm  the OCCP *controller* -- one rom-mode image from fw/tests, named by +bfm_rom_hex

Tests in this family differ only in the controller image and the plusargs, so they share
this module and are separated by their testlist entry (`name` may differ from `module`).
This is the OSS equivalent of the reference environment's `smc_rom_only_test` driver.

Nothing is transferred and nothing JUMPs, which is what separates this family from
smc_occp_dual_unsecure_boot_test. A retired-PC range check and a staged-payload readback
therefore do not apply here: they would assert against state that does not exist.

Gating follows the reference `monitor_test()`: poll both instances' scratch 0, fail on
TEST_FAIL from either, pass on TEST_PASS from either. Which side reports depends on the
image -- occp_sanity only OCCP-writes the target's scratch 0, while occp_random_test and
most others also call test_pass()/test_fail() on themselves. The firmware consoles, the
I3C bus counters and the POST code are diagnostic and gate nothing, as in the reference.

Plusargs:
    +rom_bin64=<image>        target production ROM               (required)
    +bfm_rom_hex=<image>      controller rom-mode image           (required)
    +occp_case=<name>         label for log and assertion text    (default: image stem)
    +rom_test_timeout=<ns>    completion bound in ns              (default: DEFAULT_POLL_ITERS)
    +lc_state=<n>             target lifecycle value              (default: TEST_DEV)
"""

from __future__ import annotations

import logging
from pathlib import Path

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
    SCRATCH_PASS_FAIL,
    SCRATCH_POST_CODE,
    TEST_FAIL,
    TEST_PASS,
    bus_activity,
    describe_post_code,
    format_activity,
    i2c_bus_activity,
    required_plusarg,
)

# One poll interval, in clk_smc_i cycles. 2000 cycles at SMC_CLK_PERIOD_NS is 10 us of
# sim time, which is the granularity +rom_test_timeout is rounded up to.
POLL_CYCLES = 2000
# Bound applied when a test names no +rom_test_timeout: 40 ms of sim time. The shortest
# member of this family (occp_sanity: GET_VERSION plus one 4-byte WRITE) passes at
# roughly 0.94 ms, so this is headroom for a stalled exchange rather than a target.
DEFAULT_POLL_ITERS = 4000
PROGRESS_EVERY = 200
REQUIRED_EVIDENCE = ("CHK-OCCP-ROM-ONLY",)


def _poll_interval_ns() -> int:
    return POLL_CYCLES * SMC_CLK_PERIOD_NS


def _poll_iterations() -> tuple[int, str]:
    """Poll count for this run, and the text explaining where it came from."""
    budget = cocotb.plusargs.get("rom_test_timeout")
    if budget is None:
        return DEFAULT_POLL_ITERS, f"default bound {DEFAULT_POLL_ITERS} polls"
    budget_ns = int(str(budget), 0)
    if budget_ns <= 0:
        raise AssertionError(f"+rom_test_timeout must be a positive ns value, got {budget!r}")
    interval = _poll_interval_ns()
    iters = max(1, -(-budget_ns // interval))
    return iters, f"+rom_test_timeout={budget_ns} ns / {interval} ns -> {iters} polls"


def _case_name() -> str:
    """Label for this run. Falls back to the controller image stem when unnamed."""
    named = cocotb.plusargs.get("occp_case")
    if named is not None:
        return str(named)
    image = cocotb.plusargs.get("bfm_rom_hex")
    if image is not None:
        return Path(str(image)).name.removesuffix(".rom.hex")
    return "smc_occp_rom_only_test"


@dual_test(REQUIRED_EVIDENCE)
async def smc_occp_rom_only_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    required_plusarg("rom_bin64", "smc_occp_rom_only_test")
    controller_image = required_plusarg("bfm_rom_hex", "smc_occp_rom_only_test")
    case = _case_name()
    poll_iters, poll_source = _poll_iterations()

    cocotb.log.info(
        "%s (RANDOM_SEED=%d): u_dut = production ROM target, u_bfm = %s controller; %s",
        case,
        random_seed(),
        controller_image,
        poll_source,
    )

    # Both cores held at boot_stall from t=0 so their reset vectors can be set before
    # either one fetches. +lc_state selects the target's lifecycle, which has to be in
    # place before cold reset because the wrapper samples it into CHIP_CONFIG.LC_STATE.
    lc_named = cocotb.plusargs.get("lc_state")
    await harness.bring_up(
        hold_dut_boot=True,
        hold_bfm_boot=True,
        dut_lc_state=None if lc_named is None else int(str(lc_named), 0),
    )

    # Decode both firmware virtual consoles. The controller's simputs() trace is the only
    # window into the OCCP exchange -- without it a stalled transfer is an unexplained
    # timeout. Printed, not gated on.
    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    # Target first: the controller's initialize_interface() spins on the target-ready pad
    # forever, so releasing the target is what lets the controller past its own bring-up.
    # No staging window is needed -- nothing has to be written into the controller's SRAM
    # before it runs.
    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    baseline_activity = bus_activity(dut)
    baseline_i2c = i2c_bus_activity(dut)
    cocotb.log.info(
        "both CPUs released; bus baseline [%s]",
        format_activity(baseline_activity, baseline_i2c),
    )

    target_scratch0 = 0
    ctrl_scratch0 = 0
    for iteration in range(poll_iters):
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)

        target_scratch0 = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)
        ctrl_scratch0 = await bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL)

        if target_scratch0 == TEST_FAIL or ctrl_scratch0 == TEST_FAIL:
            bfm_console.flush()
            dut_console.flush()
            post = await dut_csr.read("TARGET_POST_CODE_FAIL", SCRATCH_POST_CODE)
            raise AssertionError(
                f"{case} reported failure.\n"
                f"  controller image    = {controller_image}\n"
                f"  target scratch0     = {target_scratch0:#010x}\n"
                f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
                f"  (TEST_FAIL is {TEST_FAIL:#010x})\n"
                f"  target POST         = {describe_post_code(post)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut), i2c_bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )
        if target_scratch0 == TEST_PASS or ctrl_scratch0 == TEST_PASS:
            break

        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "%s in flight (poll %d/%d): target=%#010x ctrl=%#010x, bus [%s], ctrl wb_pc0=%#x",
                case,
                iteration,
                poll_iters,
                target_scratch0,
                ctrl_scratch0,
                format_activity(bus_activity(dut), i2c_bus_activity(dut)),
                int(dut.bfm_wb_pc0.value),
            )
    else:
        bfm_console.flush()
        dut_console.flush()
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        raise AssertionError(
            f"{case} did not complete within {poll_iters}x{POLL_CYCLES} clk_smc_i "
            f"({poll_source}).\n"
            f"  controller image    = {controller_image}\n"
            f"  target scratch0     = {target_scratch0:#010x} "
            f"(expected {TEST_PASS:#010x})\n"
            f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
            f"  target POST         = {describe_post_code(post)}\n"
            f"  target rom_reads={int(dut.dut_rom_read_count.value)} "
            f"wb_pc0={int(dut.dut_wb_pc0.value):#x}\n"
            f"  controller rom_reads={int(dut.bfm_rom_read_count.value)} "
            f"wb_pc0={int(dut.bfm_wb_pc0.value):#x}\n"
            f"  I3C bus [{format_activity(bus_activity(dut), i2c_bus_activity(dut))}]\n"
            f"controller firmware trace (last lines):\n{bfm_console.tail()}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    bfm_console.flush()
    dut_console.flush()
    harness.dump_cpu_trace(logging.INFO)
    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)

    # Diagnostics, not gates. Recorded so a pass carries the same evidence the reference
    # environment logs, and so the run is auditable after the fact.
    activity = bus_activity(dut)
    moved = [
        f"I3C{ch} (+{falls - base_falls} scl_falls, +{starts - base_starts} starts)"
        for (ch, falls, starts), (_, base_falls, base_starts) in zip(activity, baseline_activity)
        if falls > base_falls
    ]
    moved += [
        f"I2C{ch} (+{falls - base_falls} scl_falls, +{starts - base_starts} starts)"
        for (ch, falls, starts), (_, base_falls, base_starts) in zip(
            i2c_bus_activity(dut), baseline_i2c
        )
        if falls > base_falls
    ]
    if moved:
        cocotb.log.info("%s bus activity: %s", case, ", ".join(moved))
    else:
        cocotb.log.info(
            "NOTE: no I3C or I2C bus saw an SCL fall. The pass did not come from a transfer "
            "on the wire; this is informational because the reference gate does not check "
            "it either."
        )

    cocotb.log.info(
        "CHK-OCCP-ROM-ONLY: target scratch0=%#010x, controller scratch0=%#010x; "
        "OCCP exchange completed. Final target POST %s",
        target_scratch0,
        ctrl_scratch0,
        describe_post_code(post),
    )
    cocotb.log.info("%s PASS", case)
