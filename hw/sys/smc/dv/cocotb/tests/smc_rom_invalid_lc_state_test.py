# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The target ROM must refuse to boot on an illegal lifecycle encoding.

The lifecycle enum the ROM understands runs 0x0..0x8. This test drives one of the
values above that range into the target before cold reset -- a well-formed
{diff_n, diff_p} pair, so the wrapper's lc_sigint_err_o stays clear and the ROM sees a
structurally valid but semantically illegal state -- and requires the ROM to reach its
POST error state rather than continue booting.

Pass criterion, from the reference monitor's _check_invalid_lc_flow(): POST code boot
phase ERROR with error INVALID_SEC_MODE. Reaching TEST_PASS instead is a failure: it
would mean the ROM booted on a lifecycle it cannot classify.

The controller is not part of this: it runs its own image and is not gated on. Only the
target's POST code decides the outcome.

Plusargs:
    +rom_bin64=<image>        target production ROM               (required)
    +bfm_rom_hex=<image>      controller rom-mode image           (required)
    +lc_state=<n>             illegal lifecycle value             (default: random 0x9..0xF)
    +rom_test_timeout=<ns>    completion bound in ns              (default: DEFAULT_POLL_ITERS)
"""

from __future__ import annotations

import logging
import random

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
    TEST_PASS,
    describe_post_code,
    post_code_boot_phase,
    post_code_error,
    required_plusarg,
)

POLL_CYCLES = 2000
DEFAULT_POLL_ITERS = 4000
PROGRESS_EVERY = 200

# smc_rom_defs.h: the ROM's lifecycle enum ends at 0x8, so 0x9..0xF are illegal but still
# encodable as a complementary pair.
ILLEGAL_LC_VALUES = (0x9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF)

# POST code fields the ROM must land on, from the names in smc_occp_dual_defs.
POST_PHASE_ERROR = 0x7
POST_ERROR_INVALID_SEC_MODE = 0x5
REQUIRED_EVIDENCE = ("CHK-ROM-INVALID-LC",)


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


def _illegal_lc_value(rng: random.Random) -> tuple[int, str]:
    named = cocotb.plusargs.get("lc_state")
    if named is None:
        value = rng.choice(ILLEGAL_LC_VALUES)
        return value, f"randomised to {value:#x}"
    value = int(str(named), 0)
    if value not in ILLEGAL_LC_VALUES:
        raise AssertionError(
            f"+lc_state={value:#x} is a legal lifecycle value; this test needs one of "
            f"{', '.join(hex(v) for v in ILLEGAL_LC_VALUES)}"
        )
    return value, f"+lc_state={value:#x}"


@dual_test(REQUIRED_EVIDENCE)
async def smc_rom_invalid_lc_state_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    required_plusarg("rom_bin64", "smc_rom_invalid_lc_state_test")
    required_plusarg("bfm_rom_hex", "smc_rom_invalid_lc_state_test")
    poll_iters, poll_source = _poll_iterations()

    seed = random_seed()
    lc_value, lc_source = _illegal_lc_value(random.Random(seed))

    cocotb.log.info(
        "smc_rom_invalid_lc_state_test (RANDOM_SEED=%d): target lifecycle %#x (%s); %s",
        seed,
        lc_value,
        lc_source,
        poll_source,
    )

    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True, dut_lc_state=lc_value)

    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    post = 0
    scratch0 = 0
    for iteration in range(poll_iters):
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)

        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        scratch0 = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)

        if scratch0 == TEST_PASS:
            dut_console.flush()
            raise AssertionError(
                f"target reported TEST_PASS on illegal lifecycle {lc_value:#x}: the ROM "
                f"booted on a state it cannot classify.\n"
                f"  target POST = {describe_post_code(post)}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )

        if (
            post_code_boot_phase(post) == POST_PHASE_ERROR
            and post_code_error(post) == POST_ERROR_INVALID_SEC_MODE
        ):
            break

        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "invalid-LC in flight (poll %d/%d): POST %s, scratch0=%#010x",
                iteration,
                poll_iters,
                describe_post_code(post),
                scratch0,
            )
    else:
        dut_console.flush()
        raise AssertionError(
            f"target ROM never reported an illegal lifecycle within "
            f"{poll_iters}x{POLL_CYCLES} clk_smc_i ({poll_source}).\n"
            f"  lifecycle driven  = {lc_value:#x} ({lc_source})\n"
            f"  target POST       = {describe_post_code(post)}\n"
            f"  expected phase {POST_PHASE_ERROR:#x} (ERROR) "
            f"error {POST_ERROR_INVALID_SEC_MODE:#x} (INVALID_SEC_MODE)\n"
            f"  target scratch0   = {scratch0:#010x}\n"
            f"  target rom_reads={int(dut.dut_rom_read_count.value)} "
            f"wb_pc0={int(dut.dut_wb_pc0.value):#x}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    dut_console.flush()
    harness.dump_cpu_trace(logging.INFO)
    cocotb.log.info(
        "CHK-ROM-INVALID-LC: lifecycle %#x rejected; target POST %s",
        lc_value,
        describe_post_code(post),
    )
    cocotb.log.info("smc_rom_invalid_lc_state_test PASS")
