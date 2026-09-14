# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCCP sanity: one real SMC drives OCCP status commands at another.

The OSS port of the reference `smc_occp_sanity_test`. Same two-instance
configuration as `smc_occp_dual_unsecure_boot_test`, but a far shorter
transaction:

    u_dut  the OCCP *target*     -- real production boot ROM
    u_bfm  the OCCP *controller* -- fw/tests/occp_sanity, a rom-mode DV image

The controller firmware (`fw/tests/occp_sanity/main.c`) does three things:
brings up the I3C interface (wait for the target-ready pad, ENTDAA, pick a
channel), issues `GET_VERSION` and checks the answer is `0x1`, then reports by
sending an OCCP WRITE of the pass/fail code into the **target's** scratch 0.

Two consequences shape the checking here, and they are the opposite of the
boot test's:

* Nothing executes on the target. The pass value arrives as an ordinary OCCP
  WRITE serviced by the ROM, so there is no transferred image and a
  retired-PC check would assert against a range that does not exist.
* The controller never writes its own scratch 0 -- `occp_sanity/main.c` has no
  `test_pass`, `test_fail` or `end_test` call anywhere. Watching it for
  `TEST_FAIL` would be a check that cannot fail.

So neither `CHK-OCCP-JUMP-EXECUTED` nor `CHK-OCCP-CONTROLLER-NO-FAIL` is
carried over from the boot test. Copying them would produce a green test that
proves nothing.

Gating follows the reference environment's `monitor_test()`: poll both
instances' scratch 0, fail on `TEST_FAIL` from either, pass on `TEST_PASS` from
either. Everything else this test prints -- the firmware consoles, the I3C bus
counters, the POST code -- is diagnostic only and gates nothing, which is also
how the reference treats it.
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_virt_console import VirtConsole
from smc_dual_base_test import DualCsr, SmcDualHarness, dual_test, random_seed
from smc_occp_dual_defs import (
    CPU_RESET_VECTOR_ROM,
    SCRATCH_PASS_FAIL,
    SCRATCH_POST_CODE,
    TEST_FAIL,
    TEST_PASS,
    bus_activity,
    describe_post_code,
    format_activity,
    required_plusarg,
)

REQUIRED_EVIDENCE = ("CHK-OCCP-SANITY",)

# The transaction is GET_VERSION plus one 4-byte WRITE, against the boot test's
# 15 chunks of 1024 B. The pass lands at roughly 939 us of sim time, about 235
# poll intervals; the bound below is ~17x that, which is headroom for a stalled
# exchange rather than a target.
SANITY_POLL_ITERS = 4000
SANITY_POLL_CYCLES = 2000
PROGRESS_EVERY = 200


@dual_test(REQUIRED_EVIDENCE)
async def smc_occp_sanity_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    required_plusarg("rom_bin64", "smc_occp_sanity_test")
    required_plusarg("bfm_rom_hex", "smc_occp_sanity_test")

    cocotb.log.info(
        "OCCP sanity (RANDOM_SEED=%d): u_dut = production ROM target, "
        "u_bfm = occp_sanity controller",
        random_seed(),
    )

    # Both cores held at boot_stall from t=0 so their reset vectors can be set
    # before either one fetches.
    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)

    # Decode both firmware virtual consoles. The controller's simputs() trace is
    # the only window into the OCCP exchange -- without it a stalled transfer is
    # an unexplained timeout. It is printed, not gated on.
    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    # Target first: the controller's initialize_interface() spins on the
    # target-ready pad forever, so releasing the target first is what lets the
    # controller past its own bring-up. Nothing has to be written into the
    # controller's SRAM before it runs, so the controller follows immediately
    # (the boot test stages a payload first).
    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    baseline_activity = bus_activity(dut)
    cocotb.log.info("both CPUs released; I3C baseline [%s]", format_activity(baseline_activity))

    target_scratch0 = 0
    ctrl_scratch0 = 0
    for iteration in range(SANITY_POLL_ITERS):
        await ClockCycles(dut.clk_smc_i, SANITY_POLL_CYCLES)

        target_scratch0 = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)
        ctrl_scratch0 = await bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL)

        if target_scratch0 == TEST_FAIL or ctrl_scratch0 == TEST_FAIL:
            bfm_console.flush()
            dut_console.flush()
            post = await dut_csr.read("TARGET_POST_CODE_FAIL", SCRATCH_POST_CODE)
            raise AssertionError(
                "OCCP sanity reported failure.\n"
                f"  target scratch0     = {target_scratch0:#010x}\n"
                f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
                f"  (TEST_FAIL is {TEST_FAIL:#010x})\n"
                f"  target POST         = {describe_post_code(post)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )
        if target_scratch0 == TEST_PASS or ctrl_scratch0 == TEST_PASS:
            break

        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "OCCP sanity in flight (poll %d/%d): target=%#010x ctrl=%#010x, "
                "bus [%s], ctrl wb_pc0=%#x",
                iteration,
                SANITY_POLL_ITERS,
                target_scratch0,
                ctrl_scratch0,
                format_activity(bus_activity(dut)),
                int(dut.bfm_wb_pc0.value),
            )
    else:
        bfm_console.flush()
        dut_console.flush()
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        raise AssertionError(
            "OCCP sanity did not complete within "
            f"{SANITY_POLL_ITERS}x{SANITY_POLL_CYCLES} clk_smc_i.\n"
            f"  target scratch0     = {target_scratch0:#010x} "
            f"(expected {TEST_PASS:#010x})\n"
            f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
            f"  target POST         = {describe_post_code(post)}\n"
            f"  target rom_reads={int(dut.dut_rom_read_count.value)} "
            f"wb_pc0={int(dut.dut_wb_pc0.value):#x}\n"
            f"  controller rom_reads={int(dut.bfm_rom_read_count.value)} "
            f"wb_pc0={int(dut.bfm_wb_pc0.value):#x}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"controller firmware trace (last lines):\n{bfm_console.tail()}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    bfm_console.flush()
    dut_console.flush()
    harness.dump_cpu_trace(logging.INFO)
    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)

    # Diagnostics, not gates. Recorded so a pass carries the same evidence the
    # reference environment logs, and so the run is auditable after the fact.
    activity = bus_activity(dut)
    moved = [
        (ch, falls - base_falls, starts - base_starts)
        for (ch, falls, starts), (_, base_falls, base_starts) in zip(activity, baseline_activity)
        if falls > base_falls
    ]
    if moved:
        cocotb.log.info(
            "OCCP sanity bus activity: %s",
            ", ".join(
                f"I3C{ch} (+{falls} scl_falls, +{starts} starts)" for ch, falls, starts in moved
            ),
        )
    else:
        cocotb.log.info(
            "NOTE: no I3C channel saw an SCL fall. The pass did not come from a "
            "transfer on the wire; this is informational here because the "
            "reference gate does not check it either."
        )

    cocotb.log.info(
        "CHK-OCCP-SANITY: target scratch0=%#010x, controller scratch0=%#010x; "
        "OCCP status exchange completed. Final target POST %s",
        target_scratch0,
        ctrl_scratch0,
        describe_post_code(post),
    )
    cocotb.log.info("smc_occp_sanity_test PASS")
