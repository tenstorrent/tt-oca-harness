# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Secure boot: the controller transfers a payload, the ROM validates it and stands aside.

On a secure lifecycle the ROM publishes a manifest instead of jumping. The testbench plays SEP:
it flushes the image to SRAM and restarts the target's cores at the manifest entry point.
"""

from __future__ import annotations

import logging
import random
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_virt_console import VirtConsole
from smc_dual_base_test import (
    LC_STATE_SECURE_VALUES,
    SMC_CLK_PERIOD_NS,
    DualCsr,
    SmcDualHarness,
    dual_test,
    random_seed,
)
from smc_occp_dual_defs import (
    BFM_STAGING_FLOOR,
    CPU_CTRL_RESET_CTRL,
    CPU_CTRL_RESET_VECTOR,
    CPU_RESET_CTRL_DEFAULT,
    CPU_RESET_CTRL_PULSE_CORES,
    CPU_RESET_VECTOR_ROM,
    CTRL_TARGET_READY_PAD,
    OCCP_SRAM_BASE,
    OCCP_SRAM_UPPER,
    SCRATCH_BOOTCODE_ADDR,
    SCRATCH_BOOTCODE_SIZE,
    SCRATCH_JUMP_BASE,
    SCRATCH_MANIFEST_ADDR,
    SCRATCH_PASS_FAIL,
    SCRATCH_POST_CODE,
    SCRATCH_STATUS_TO_SEP,
    SCRATCH_TARGET_ADDR,
    SEP_STATUS_MANIFEST_READY_BIT,
    SMC_SRAM_BASE,
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
REQUIRED_EVIDENCE = ("CHK-OCCP-SECURE-BOOT",)

SEP_PROCESSING_MIN_CYCLES = 1_000
SEP_PROCESSING_MAX_CYCLES = 20_000


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


def _secure_lc_value() -> int:
    named = cocotb.plusargs.get("lc_state")
    value = LC_STATE_SECURE_VALUES[0] if named is None else int(str(named), 0)
    if value not in LC_STATE_SECURE_VALUES:
        raise AssertionError(
            f"+lc_state={value:#x} is not a secure lifecycle; is_secure_mode() accepts "
            f"{', '.join(hex(v) for v in LC_STATE_SECURE_VALUES)}. Without a secure "
            "lifecycle the ROM would jump the payload instead of publishing a manifest, "
            "which is a different test."
        )
    return value


@dual_test(REQUIRED_EVIDENCE)
async def smc_occp_secure_boot_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    required_plusarg("rom_bin64", "smc_occp_secure_boot_test")
    controller_image = required_plusarg("bfm_rom_hex", "smc_occp_secure_boot_test")
    payload_bin = required_plusarg("occp_payload_bin", "smc_occp_secure_boot_test")
    payload_sym = required_plusarg("occp_payload_sym", "smc_occp_secure_boot_test")
    poll_iters, poll_source = _poll_iterations()

    seed = random_seed()
    rng = random.Random(seed)
    lc_value = _secure_lc_value()

    payload_bytes = Path(payload_bin).read_bytes()
    assert payload_bytes, f"{payload_bin} is empty; there would be nothing to boot"
    payload_size = len(payload_bytes)
    entry_offset = payload_entry_offset(payload_sym)

    staging_addr = rng.randrange(BFM_STAGING_FLOOR, OCCP_SRAM_UPPER - payload_size) & ~0x7
    target_addr = rng.randrange(OCCP_SRAM_BASE, OCCP_SRAM_UPPER - payload_size) & ~0x7

    cocotb.log.info(
        "smc_occp_secure_boot_test (RANDOM_SEED=%d): lifecycle %#x, controller = %s, "
        "payload = %s (%d bytes) staged %#010x -> target %#010x, entry offset %#x; %s",
        seed,
        lc_value,
        controller_image,
        Path(payload_bin).name,
        payload_size,
        staging_addr,
        target_addr,
        entry_offset,
        poll_source,
    )

    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True, dut_lc_state=lc_value)

    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    # Hold the controller at its target-ready wait so its SRAM and scratch can be staged.
    harness.set_gpio_override("bfm", CTRL_TARGET_READY_PAD, 0)

    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    await bfm_csr.write_bytes("PAYLOAD_STAGE", staging_addr, payload_bytes)
    staged = await bfm_csr.read_bytes("PAYLOAD_VERIFY", staging_addr, payload_size)
    if staged != payload_bytes:
        first_bad = next(i for i, (a, b) in enumerate(zip(staged, payload_bytes)) if a != b)
        raise AssertionError(
            f"payload readback differs at byte {first_bad}: staged {staged[first_bad]:#04x}, "
            f"expected {payload_bytes[first_bad]:#04x}. The controller would transfer a "
            "corrupt image and the manifest would be validated against nothing useful."
        )

    # SCRATCH_JUMP_BASE is scratch 4, which this flow uses for the entry offset.
    await bfm_csr.write("ENTRY_OFFSET", SCRATCH_JUMP_BASE, entry_offset, length=8)
    await bfm_csr.write("BOOTCODE_ADDR", SCRATCH_BOOTCODE_ADDR, staging_addr, length=8)
    await bfm_csr.write("BOOTCODE_SIZE", SCRATCH_BOOTCODE_SIZE, payload_size, length=8)
    await bfm_csr.write("TARGET_ADDR", SCRATCH_TARGET_ADDR, target_addr, length=8)

    harness.set_gpio_override("bfm", CTRL_TARGET_READY_PAD, None)

    baseline_activity = bus_activity(dut)

    ready_mask = 1 << SEP_STATUS_MANIFEST_READY_BIT
    scratch_9 = 0
    for iteration in range(poll_iters):
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)

        scratch_9 = await dut_csr.read("TARGET_SEP_STATUS", SCRATCH_STATUS_TO_SEP)
        if scratch_9 & ready_mask:
            break

        target_scratch0 = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)
        ctrl_scratch0 = await bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL)
        if target_scratch0 == TEST_FAIL or ctrl_scratch0 == TEST_FAIL:
            bfm_console.flush()
            dut_console.flush()
            post = await dut_csr.read("TARGET_POST_CODE_FAIL", SCRATCH_POST_CODE)
            raise AssertionError(
                f"secure boot reported failure before the manifest was published.\n"
                f"  target scratch0     = {target_scratch0:#010x}\n"
                f"  controller scratch0 = {ctrl_scratch0:#010x}\n"
                f"  target POST         = {describe_post_code(post)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )

        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "secure boot in flight (poll %d/%d): scratch9=%#010x, bus [%s]",
                iteration,
                poll_iters,
                scratch_9,
                format_activity(bus_activity(dut)),
            )
    else:
        bfm_console.flush()
        dut_console.flush()
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        raise AssertionError(
            f"target ROM never published a manifest within {poll_iters}x{POLL_CYCLES} "
            f"clk_smc_i ({poll_source}).\n"
            f"  lifecycle           = {lc_value:#x} (secure)\n"
            f"  scratch 9           = {scratch_9:#010x}, need bit "
            f"{SEP_STATUS_MANIFEST_READY_BIT}\n"
            f"  target POST         = {describe_post_code(post)}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"controller firmware trace (last lines):\n{bfm_console.tail()}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    # The controller sends the payload's entry point, not its base, as the manifest address.
    expected_manifest = target_addr + entry_offset
    manifest_offset = await dut_csr.read("TARGET_MANIFEST", SCRATCH_MANIFEST_ADDR)
    manifest_addr = manifest_offset + SMC_SRAM_BASE
    if manifest_addr != expected_manifest:
        raise AssertionError(
            f"ROM published manifest {manifest_addr:#010x}, but the controller sent "
            f"{expected_manifest:#010x} (target {target_addr:#010x} + entry offset "
            f"{entry_offset:#x}); the ROM did not echo the address it was given"
        )
    cocotb.log.info(
        "manifest published: scratch 8 offset %#010x -> %#010x", manifest_offset, manifest_addr
    )

    # Act as SEP: write the image back so the restarted cores fetch it from SRAM, not cache.
    manifest_data = await dut_csr.read_bytes("MANIFEST_READ", target_addr, payload_size)
    if manifest_data != payload_bytes:
        first_bad = next(i for i, (a, b) in enumerate(zip(manifest_data, payload_bytes)) if a != b)
        raise AssertionError(
            f"the transferred image differs from the payload at byte {first_bad}: "
            f"target has {manifest_data[first_bad]:#04x}, expected "
            f"{payload_bytes[first_bad]:#04x}. The OCCP transfer, not the boot, is at fault."
        )
    await dut_csr.write_bytes("MANIFEST_WRITEBACK", target_addr, manifest_data)

    await ClockCycles(
        dut.clk_smc_i, rng.randint(SEP_PROCESSING_MIN_CYCLES, SEP_PROCESSING_MAX_CYCLES)
    )

    # RESET_VECTOR is latched only on tile reset and boot_stall is already low, so pulse reset.
    boot_vector = manifest_addr
    cocotb.log.info("restarting the target's cores at %#010x", boot_vector)
    for idx, addr in enumerate(CPU_CTRL_RESET_VECTOR):
        await dut_csr.write(f"BOOT_VECTOR_{idx}", addr, boot_vector, length=8)
    await ClockCycles(dut.clk_smc_i, 16)
    await dut_csr.write(
        "CORE_RESET_PULSE",
        CPU_CTRL_RESET_CTRL,
        CPU_RESET_CTRL_DEFAULT | CPU_RESET_CTRL_PULSE_CORES,
        length=8,
    )
    await ClockCycles(dut.clk_smc_i, 256)

    target_scratch0 = 0
    for iteration in range(poll_iters):
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)

        target_scratch0 = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)
        if target_scratch0 == TEST_FAIL:
            bfm_console.flush()
            dut_console.flush()
            raise AssertionError(
                f"the booted payload reported failure.\n"
                f"  boot vector     = {boot_vector:#010x}\n"
                f"  target scratch0 = {target_scratch0:#010x}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )
        if target_scratch0 == TEST_PASS:
            break

        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "booted payload in flight (poll %d/%d): target=%#010x wb_pc0=%#x",
                iteration,
                poll_iters,
                target_scratch0,
                int(dut.dut_wb_pc0.value),
            )
    else:
        bfm_console.flush()
        dut_console.flush()
        raise AssertionError(
            f"the payload never reported after the cores were restarted at "
            f"{boot_vector:#010x}.\n"
            f"  target scratch0 = {target_scratch0:#010x} (expected {TEST_PASS:#010x})\n"
            f"  target wb_pc0   = {int(dut.dut_wb_pc0.value):#x}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    bfm_console.flush()
    dut_console.flush()
    harness.dump_cpu_trace(logging.INFO)
    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)

    activity = bus_activity(dut)
    assert any(
        falls > base_falls for (_, falls, _), (_, base_falls, _) in zip(activity, baseline_activity)
    ), "no I3C channel saw an SCL fall, so the payload never crossed to the target"

    cocotb.log.info(
        "CHK-OCCP-SECURE-BOOT: lifecycle %#x, manifest %#010x validated and booted at "
        "%#010x; target scratch0=%#010x. Final target POST %s",
        lc_value,
        manifest_addr,
        boot_vector,
        target_scratch0,
        describe_post_code(post),
    )
    cocotb.log.info("smc_occp_secure_boot_test PASS")
