# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The target ROM must JUMP to an address given at run time, not a fixed one.

Each run stages a payload at a random address in the target's OCCP window and publishes it in
the target's scratch 4 and 5; the controller image reads both over OCCP and then issues JUMP.
"""

from __future__ import annotations

import logging
import random
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
    CTRL_TARGET_READY_PAD,
    OCCP_SRAM_BASE,
    OCCP_SRAM_UPPER,
    SCRATCH_JUMP_BASE,
    SCRATCH_JUMP_ENTRY_OFFSET,
    SCRATCH_PASS_FAIL,
    SCRATCH_POST_CODE,
    TEST_FAIL,
    TEST_PASS,
    bus_activity,
    describe_post_code,
    format_activity,
    payload_entry_offset,
    required_plusarg,
)

POLL_CYCLES = 2000
DEFAULT_POLL_ITERS = 4000
PROGRESS_EVERY = 200
REQUIRED_EVIDENCE = ("CHK-OCCP-RANDOM-JUMP",)


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


@dual_test(REQUIRED_EVIDENCE)
async def smc_occp_random_jump_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    required_plusarg("rom_bin64", "smc_occp_random_jump_test")
    controller_image = required_plusarg("bfm_rom_hex", "smc_occp_random_jump_test")
    payload_bin = required_plusarg("occp_payload_bin", "smc_occp_random_jump_test")
    payload_sym = required_plusarg("occp_payload_sym", "smc_occp_random_jump_test")
    poll_iters, poll_source = _poll_iterations()

    seed = random_seed()
    rng = random.Random(seed)

    payload_bytes = Path(payload_bin).read_bytes()
    assert payload_bytes, f"{payload_bin} is empty; there would be nothing to jump into"
    entry_offset = payload_entry_offset(payload_sym)

    highest = OCCP_SRAM_UPPER - len(payload_bytes)
    assert highest > OCCP_SRAM_BASE, (
        f"payload of {len(payload_bytes)} bytes does not fit in the OCCP window "
        f"[{OCCP_SRAM_BASE:#010x}, {OCCP_SRAM_UPPER:#010x})"
    )
    payload_addr = rng.randrange(OCCP_SRAM_BASE, highest) & ~0x7

    cocotb.log.info(
        "smc_occp_random_jump_test (RANDOM_SEED=%d): controller = %s, payload = %s "
        "(%d bytes) at %#010x, entry offset %#x -> JUMP %#010x; %s",
        seed,
        controller_image,
        Path(payload_bin).name,
        len(payload_bytes),
        payload_addr,
        entry_offset,
        payload_addr + entry_offset,
        poll_source,
    )

    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)

    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    # Hold the controller at its target-ready wait until the payload and jump target are staged.
    harness.set_gpio_override("bfm", CTRL_TARGET_READY_PAD, 0)

    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    await dut_csr.write_bytes("PAYLOAD_STAGE", payload_addr, payload_bytes)
    staged = await dut_csr.read_bytes("PAYLOAD_VERIFY", payload_addr, len(payload_bytes))
    if staged != payload_bytes:
        first_bad = next(i for i, (a, b) in enumerate(zip(staged, payload_bytes)) if a != b)
        raise AssertionError(
            f"payload readback differs at byte {first_bad}: staged {staged[first_bad]:#04x}, "
            f"expected {payload_bytes[first_bad]:#04x}. The ROM would jump into a bad image."
        )

    # Offset before base: the controller waits for scratch 4 non-zero, then reads scratch 5.
    await dut_csr.write("JUMP_ENTRY_OFFSET", SCRATCH_JUMP_ENTRY_OFFSET, entry_offset, length=8)
    await dut_csr.write("JUMP_BASE", SCRATCH_JUMP_BASE, payload_addr, length=8)
    cocotb.log.info(
        "published jump target to the target's scratch: base %#010x, entry offset %#x",
        payload_addr,
        entry_offset,
    )

    harness.set_gpio_override("bfm", CTRL_TARGET_READY_PAD, None)

    baseline_activity = bus_activity(dut)

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
                f"smc_occp_random_jump_test reported failure.\n"
                f"  payload at          = {payload_addr:#010x} (+{entry_offset:#x})\n"
                f"  target scratch0     = {target_scratch0:#010x}\n"
                f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
                f"  target POST         = {describe_post_code(post)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )
        if target_scratch0 == TEST_PASS:
            break

        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "random-jump in flight (poll %d/%d): target=%#010x ctrl=%#010x, bus [%s], "
                "target wb_pc0=%#x",
                iteration,
                poll_iters,
                target_scratch0,
                ctrl_scratch0,
                format_activity(bus_activity(dut)),
                int(dut.dut_wb_pc0.value),
            )
    else:
        bfm_console.flush()
        dut_console.flush()
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        raise AssertionError(
            f"target never reported the jumped payload's pass within "
            f"{poll_iters}x{POLL_CYCLES} clk_smc_i ({poll_source}).\n"
            f"  payload at          = {payload_addr:#010x} (+{entry_offset:#x})\n"
            f"  target scratch0     = {target_scratch0:#010x} (expected {TEST_PASS:#010x})\n"
            f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
            f"  target POST         = {describe_post_code(post)}\n"
            f"  target wb_pc0={int(dut.dut_wb_pc0.value):#x}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"controller firmware trace (last lines):\n{bfm_console.tail()}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    bfm_console.flush()
    dut_console.flush()
    harness.dump_cpu_trace(logging.INFO)
    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)

    activity = bus_activity(dut)
    moved = [
        (ch, falls - base_falls)
        for (ch, falls, _), (_, base_falls, _) in zip(activity, baseline_activity)
        if falls > base_falls
    ]
    assert moved, (
        "no I3C channel saw an SCL fall, so the JUMP was never carried over the wire; "
        "the target's pass cannot have come from this test"
    )

    cocotb.log.info(
        "CHK-OCCP-RANDOM-JUMP: target ran the payload staged at %#010x (+%#x); "
        "target scratch0=%#010x. Final target POST %s",
        payload_addr,
        entry_offset,
        target_scratch0,
        describe_post_code(post),
    )
    cocotb.log.info("smc_occp_random_jump_test PASS")
