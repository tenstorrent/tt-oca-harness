# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCCP unsecure boot between two real SMCs: controller DV firmware, target production ROM.

Stages a payload in the controller's SRAM, then passes when the target executes it via OCCP.
Requires +rom_bin64, +bfm_rom_hex, +occp_payload_bin and +occp_payload_sym.
"""

from __future__ import annotations

import logging
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_virt_console import VirtConsole
from smc_dual_base_test import DualCsr, SmcDualHarness, dual_test, random_seed
from smc_occp_dual_defs import (
    CPU_RESET_VECTOR_ROM,
    CTRL_TARGET_READY_PAD,
    POST_CODE_BOOT_PHASE_ERROR,
    POST_CODE_BOOT_PHASE_OCCP_PROC,
    SCRATCH_BOOTCODE_ADDR,
    SCRATCH_BOOTCODE_SIZE,
    SCRATCH_ENTRY_OFFSET,
    SCRATCH_PASS_FAIL,
    SCRATCH_POST_CODE,
    SCRATCH_TARGET_ADDR,
    SMC_SRAM_BASE,
    TEST_FAIL,
    TEST_PASS,
    bus_activity,
    describe_post_code,
    format_activity,
    payload_entry_offset,
    pick_payload_addresses,
    post_code_boot_phase,
    post_code_error,
    required_plusarg,
)

ROM_POLL_ITERS = 2000
ROM_POLL_CYCLES = 200

# Each 1 KB OCCP chunk takes ~3.2 ms of sim time; scale this bound with the payload size.
OCCP_POLL_ITERS = 40_000
OCCP_POLL_CYCLES = 2_000

# The controller validates the JUMP response after the payload writes TEST_PASS; keep polling.
CTRL_VERDICT_GRACE_ITERS = 60
PROGRESS_EVERY = 100
REQUIRED_EVIDENCE = (
    "CHK-OCCP-TARGET-READY",
    "CHK-OCCP-PRECONDITION",
    "CHK-OCCP-PAYLOAD-STAGED",
    "CHK-OCCP-HOST-PROTOCOL",
    "CHK-OCCP-TRANSFER-LANDED",
    "CHK-OCCP-CONTROLLER-NO-FAIL",
    "CHK-OCCP-BUS-ACTIVITY",
    "CHK-OCCP-JUMP-EXECUTED",
    "CHK-OCCP-PAYLOAD-EXECUTED",
)


async def _peek_target_scratch(dut, offset: int) -> tuple[int, int]:
    # Backdoor array read: bypasses the CPU D-cache but works while the cluster is isolated.
    dut.tb_dut_scratch_peek_offset.value = offset
    # One delta plus a clock edge so the comb mux settles before sampling.
    await ClockCycles(dut.clk_smc_i, 2)
    return (
        int(dut.tb_dut_scratch_peek_data.value),
        int(dut.tb_dut_scratch_peek_ecc.value),
    )


def _payload_words(payload_bin: str) -> list[int]:
    data = Path(payload_bin).read_bytes()
    return [int.from_bytes(data[i : i + 8], "little") for i in range(0, len(data), 8)]


async def _describe_landing(dut, target_offset: int, expect_words) -> str:
    lines = []
    mismatches = 0
    for idx, expected in enumerate(expect_words):
        got, ecc = await _peek_target_scratch(dut, target_offset + idx * 8)
        ok = got == expected
        if not ok:
            mismatches += 1
        if idx < 4 or not ok:
            lines.append(
                f"    [{idx:3d}] @{target_offset + idx * 8:#07x} "
                f"got={got:#018x} ecc={ecc:#04x} "
                f"exp={expected:#018x} {'ok' if ok else 'MISMATCH'}"
            )
    head = (
        f"  target SRAM vs payload image: {len(expect_words) - mismatches}"
        f"/{len(expect_words)} words match"
    )
    return "\n".join([head, *lines])


async def _scan_for_payload(dut, signature: int, limit: int = 0x10_0000) -> str:
    hits = []
    for offset in range(0, limit, 8):
        word, _ = await _peek_target_scratch(dut, offset)
        if word == signature:
            hits.append(offset)
            if len(hits) >= 8:
                break
    if not hits:
        return (
            f"  scan: payload signature {signature:#018x} found NOWHERE in the "
            f"target's {limit // 1024} KB scratch SRAM"
        )
    return "  scan: payload signature found at offsets " + ", ".join(
        f"{h:#07x} (addr {SMC_SRAM_BASE + h:#010x})" for h in hits
    )


def _tx_snoop(dut) -> str:
    count = int(dut.tb_bfm_i3c_tx_count.value)
    # Flat scalars: cocotb reads every unpacked-array element as element 0.
    words = [int(getattr(dut, f"tb_bfm_i3c_tx_word_{i}").value) for i in range(8)]
    return (
        f"  controller I3C TX-port writes = {count} DWORD(s)\n"
        "  first words (LE bytes on the wire): " + ", ".join(f"{w:#010x}" for w in words)
    )


@dual_test(REQUIRED_EVIDENCE)
async def smc_occp_dual_unsecure_boot_test(harness: SmcDualHarness) -> None:
    dut = harness.dut

    payload_bin = required_plusarg("occp_payload_bin", "smc_occp_dual_unsecure_boot_test")
    payload_sym = required_plusarg("occp_payload_sym", "smc_occp_dual_unsecure_boot_test")
    payload_bytes = Path(payload_bin).read_bytes()
    payload_size = len(payload_bytes)
    entry_offset = payload_entry_offset(payload_sym)
    payload_addr, target_addr = pick_payload_addresses(random_seed(), payload_size)
    expect_words = _payload_words(payload_bin)
    target_offset = target_addr - SMC_SRAM_BASE
    required_plusarg("rom_bin64", "smc_occp_dual_unsecure_boot_test")
    required_plusarg("bfm_rom_hex", "smc_occp_dual_unsecure_boot_test")

    assert payload_size > 0, f"payload image {payload_bin} is empty"
    # The controller firmware reads a non-8-byte tail unaligned, which wedges it mid-transfer.
    assert payload_size % 8 == 0, (
        f"payload image {payload_bin} is {payload_size} bytes, which is not a "
        "multiple of 8. The OCCP controller firmware cannot read a non-8-aligned "
        "tail without issuing unaligned accesses that stall the transfer."
    )

    cocotb.log.info(
        "OCCP dual boot (RANDOM_SEED=%d): payload %d bytes staged at controller "
        "%#010x -> target %#010x, entry offset %#x. Both addresses drawn from "
        "the OCCP window; re-run with the same RANDOM_SEED to reproduce.",
        random_seed(),
        payload_size,
        payload_addr,
        target_addr,
        entry_offset,
    )

    # Both cores held at boot_stall from t=0 so their reset vectors can be set.
    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)

    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    # Release the target first: it must be servicing OCCP before the controller issues ENTDAA.
    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)

    phase_trace: list[int] = []
    post = 0
    for _ in range(ROM_POLL_ITERS):
        await ClockCycles(dut.clk_smc_i, ROM_POLL_CYCLES)
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        phase = post_code_boot_phase(post)
        if not phase_trace or phase_trace[-1] != phase:
            phase_trace.append(phase)
        if phase == POST_CODE_BOOT_PHASE_ERROR:
            raise AssertionError(
                f"target ROM entered its ERROR phase before any OCCP traffic: "
                f"{describe_post_code(post)} trace={[hex(p) for p in phase_trace]}"
            )
        if phase == POST_CODE_BOOT_PHASE_OCCP_PROC:
            break
    else:
        raise AssertionError(
            f"target ROM never reached its OCCP command loop within "
            f"{ROM_POLL_ITERS}x{ROM_POLL_CYCLES} clk_smc_i: "
            f"{describe_post_code(post)} trace={[hex(p) for p in phase_trace]} "
            f"rom_reads={int(dut.dut_rom_read_count.value)}"
        )
    cocotb.log.info(
        "CHK-OCCP-TARGET-READY: target ROM in its OCCP command loop, POST %s (trace=%s)",
        describe_post_code(post),
        [hex(p) for p in phase_trace],
    )

    pre_pass = await dut_csr.read("TARGET_PASS_PRE", SCRATCH_PASS_FAIL)
    assert pre_pass != TEST_PASS, (
        f"target scratch 0 already holds TEST_PASS {TEST_PASS:#010x} before the "
        "transfer; the pass check would be vacuous"
    )
    cocotb.log.info(
        "CHK-OCCP-PRECONDITION: target scratch0=%#010x, not the pass value",
        pre_pass,
    )

    baseline_activity = bus_activity(dut)

    # Hold the target-ready pad low so staging completes before firmware reads scratch 5-8.
    harness.set_gpio_override("bfm", CTRL_TARGET_READY_PAD, 0)

    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    await bfm_csr.write_bytes("PAYLOAD_STAGE", payload_addr, payload_bytes)

    staged = await bfm_csr.read_bytes("PAYLOAD_RDBK", payload_addr, payload_size)
    if staged != payload_bytes:
        first_bad = next(i for i, (a, b) in enumerate(zip(staged, payload_bytes)) if a != b)
        raise AssertionError(
            f"payload staged into the controller's SRAM at {payload_addr:#010x} "
            f"does not read back: first mismatch at byte {first_bad} "
            f"(+{first_bad:#x}), got {staged[first_bad]:#04x} expected "
            f"{payload_bytes[first_bad]:#04x}. The controller would stream "
            "garbage to the target."
        )
    cocotb.log.info(
        "CHK-OCCP-PAYLOAD-STAGED: %d bytes read back from the controller's SRAM "
        "at %#010x byte-for-byte",
        payload_size,
        payload_addr,
    )

    await bfm_csr.write("BOOTCODE_ADDR", SCRATCH_BOOTCODE_ADDR, payload_addr, length=8)
    await bfm_csr.write("BOOTCODE_SIZE", SCRATCH_BOOTCODE_SIZE, payload_size, length=8)
    await bfm_csr.write("TARGET_ADDR", SCRATCH_TARGET_ADDR, target_addr, length=8)
    await bfm_csr.write("ENTRY_OFFSET", SCRATCH_ENTRY_OFFSET, entry_offset, length=8)

    for name, addr, expected in (
        ("BOOTCODE_ADDR", SCRATCH_BOOTCODE_ADDR, payload_addr),
        ("BOOTCODE_SIZE", SCRATCH_BOOTCODE_SIZE, payload_size),
        ("TARGET_ADDR", SCRATCH_TARGET_ADDR, target_addr),
        ("ENTRY_OFFSET", SCRATCH_ENTRY_OFFSET, entry_offset),
    ):
        got = await bfm_csr.read(f"{name}_RDBK", addr, length=8)
        assert got == expected, f"controller scratch readback {name}: {got:#x} != {expected:#x}"
    cocotb.log.info(
        "CHK-OCCP-HOST-PROTOCOL: controller scratch 5-8 seeded and read back "
        "(addr=%#010x size=%d target=%#010x entry_offset=%#x)",
        payload_addr,
        payload_size,
        target_addr,
        entry_offset,
    )

    harness.set_gpio_override("bfm", CTRL_TARGET_READY_PAD, None)
    cocotb.log.info(
        "released the controller's GPIO %d target-ready handshake",
        CTRL_TARGET_READY_PAD,
    )

    transfer_landed = False

    async def _fail_on_ctrl_verdict(when: str) -> None:
        ctrl = await bfm_csr.read("CTRL_VERDICT", SCRATCH_PASS_FAIL)
        # The controller writes scratch 0 only to report TEST_FAIL; success leaves it untouched.
        if ctrl != TEST_FAIL:
            return
        bfm_console.flush()
        dut_console.flush()
        raise AssertionError(
            f"the OCCP controller reported TEST_FAIL ({TEST_FAIL:#010x}) in its "
            f"own scratch 0, {when}.\n"
            "  It rejected something the target sent -- an OCCP response whose "
            "header CRC or status code failed its check, or a transfer it could "
            "not complete. The target's own result does not override this: the "
            "payload can be running while the protocol that delivered it was "
            "broken.\n"
            f"  target scratch0 = {passv:#010x}\n"
            f"  transfer landed  = {transfer_landed}\n"
            f"{_tx_snoop(dut)}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"  controller wb_pc0={int(dut.bfm_wb_pc0.value):#x} "
            f"rom_reads={int(dut.bfm_rom_read_count.value)}\n"
            f"controller firmware trace:\n{bfm_console.tail()}\n"
            f"target firmware trace:\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    passv = 0
    pc_in_payload = False
    for iteration in range(OCCP_POLL_ITERS):
        await ClockCycles(dut.clk_smc_i, OCCP_POLL_CYCLES)

        await _fail_on_ctrl_verdict(f"at poll {iteration}/{OCCP_POLL_ITERS}")

        # The ROM clears the POST error field on the next good command, so sample it every poll.
        live_post = await dut_csr.read("TARGET_POST_LIVE", SCRATCH_POST_CODE)
        if post_code_error(live_post) != 0:
            bfm_console.flush()
            dut_console.flush()
            raise AssertionError(
                f"target latched a POST error during the transfer at poll "
                f"{iteration}/{OCCP_POLL_ITERS}: {describe_post_code(live_post)}\n"
                "  Caught live because the ROM clears this field on the next "
                "successful command, so an end-of-test sample would have missed "
                "it.\n"
                f"  transfer landed = {transfer_landed}\n"
                f"{_tx_snoop(dut)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )

        if not transfer_landed:
            first, first_ecc = await _peek_target_scratch(dut, target_offset)
            last, _ = await _peek_target_scratch(dut, target_offset + (len(expect_words) - 1) * 8)
            if first == expect_words[0] and last == expect_words[-1]:
                transfer_landed = True
                cocotb.log.info(
                    "CHK-OCCP-TRANSFER-LANDED: target SRAM at %#010x holds the "
                    "payload (first word %#018x ecc=%#04x, last word %#018x); "
                    "the OCCP WRITE stream reached the right address",
                    target_addr,
                    first,
                    first_ecc,
                    last,
                )

        passv = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)
        if passv == TEST_FAIL:
            post = await dut_csr.read("TARGET_POST_CODE_FAIL", SCRATCH_POST_CODE)
            landed_report = await _describe_landing(dut, target_offset, expect_words)
            scan_report = await _scan_for_payload(dut, expect_words[0])
            bfm_console.flush()
            dut_console.flush()
            raise AssertionError(
                f"target reported TEST_FAIL ({TEST_FAIL:#010x}) in scratch 0.\n"
                f"  transfer landed = {transfer_landed}\n"
                f"{landed_report}\n"
                f"{scan_report}\n"
                f"{_tx_snoop(dut)}\n"
                f"  target POST     = {describe_post_code(post)}\n"
                f"  target wb_pc0={int(dut.dut_wb_pc0.value):#x} "
                f"scratch_reads={int(dut.dut_scratch_read_count.value)} "
                f"scratch_writes={int(dut.dut_scratch_write_count.value)} "
                f"rom_reads={int(dut.dut_rom_read_count.value)}\n"
                f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
                f"controller firmware trace:\n{bfm_console.tail()}\n"
                f"target firmware trace:\n{dut_console.tail()}\n"
                f"CPU state:\n{harness.cpu_trace_report()}"
            )
        if passv == TEST_PASS:
            break
        pc_now = int(dut.dut_wb_pc0.value)
        if target_addr <= pc_now < target_addr + payload_size:
            pc_in_payload = True
        if iteration and iteration % PROGRESS_EVERY == 0:
            cocotb.log.info(
                "OCCP in flight (poll %d/%d): target pass=%#010x, bus [%s], ctrl wb_pc0=%#x",
                iteration,
                OCCP_POLL_ITERS,
                passv,
                format_activity(bus_activity(dut)),
                int(dut.bfm_wb_pc0.value),
            )
    else:
        post = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        bfm_post = await bfm_csr.read("CTRL_SCRATCH0", SCRATCH_PASS_FAIL)
        landed_report = await _describe_landing(dut, target_offset, expect_words)
        bfm_console.flush()
        dut_console.flush()
        raise AssertionError(
            "OCCP unsecure boot did not complete within "
            f"{OCCP_POLL_ITERS}x{OCCP_POLL_CYCLES} clk_smc_i.\n"
            f"  target scratch0 (pass magic)    = {passv:#010x} "
            f"(expected {TEST_PASS:#010x})\n"
            f"  target POST                     = {describe_post_code(post)}\n"
            f"  transfer landed                 = {transfer_landed}\n"
            f"{landed_report}\n"
            f"{_tx_snoop(dut)}\n"
            f"  controller scratch0             = {bfm_post:#010x}\n"
            f"  target rom_reads={int(dut.dut_rom_read_count.value)} "
            f"scratch_writes={int(dut.dut_scratch_write_count.value)} "
            f"wb_pc0={int(dut.dut_wb_pc0.value):#x}\n"
            f"  controller rom_reads={int(dut.bfm_rom_read_count.value)} "
            f"wb_pc0={int(dut.bfm_wb_pc0.value):#x}\n"
            f"  I3C bus [{format_activity(bus_activity(dut))}]\n"
            f"controller firmware trace (last lines):\n{bfm_console.tail()}\n"
            f"target firmware trace (last lines):\n{dut_console.tail()}\n"
            f"CPU state:\n{harness.cpu_trace_report()}"
        )

    for grace in range(CTRL_VERDICT_GRACE_ITERS):
        await ClockCycles(dut.clk_smc_i, OCCP_POLL_CYCLES)
        await _fail_on_ctrl_verdict(
            f"{grace + 1}/{CTRL_VERDICT_GRACE_ITERS} poll intervals after the target reported PASS"
        )
    ctrl_scratch0 = await bfm_csr.read("CTRL_VERDICT_FINAL", SCRATCH_PASS_FAIL)
    cocotb.log.info(
        "CHK-OCCP-CONTROLLER-NO-FAIL: controller scratch0=%#010x (not TEST_FAIL "
        "%#010x) throughout the transfer and for %d poll intervals after the "
        "target passed; it rejected no OCCP response",
        ctrl_scratch0,
        TEST_FAIL,
        CTRL_VERDICT_GRACE_ITERS,
    )
    # The controller never signals success, so this proves only the absence of a rejection.
    # bfm_console.lines is the full history; tail() is only the last 40.
    if any("Done, waiting for ROM" in line for line in bfm_console.lines):
        cocotb.log.info("controller also reached its own terminal state (console)")
    else:
        cocotb.log.info(
            "NOTE: controller had not printed its terminal line when the test "
            "ended; the grace window bounds how long the test waits for a "
            "rejection, not for completion."
        )

    activity = bus_activity(dut)
    # Require a START delta too: SCL alone can move without any framed transfer.
    moved = [
        (ch, falls - base_falls, starts - base_starts)
        for (ch, falls, starts), (_, base_falls, base_starts) in zip(activity, baseline_activity)
        if falls > base_falls and starts > base_starts
    ]
    assert moved, (
        "target reported the pass magic, but no I3C channel saw both an SCL "
        f"fall and a START condition during the transfer: "
        f"[{format_activity(activity)}]. "
        "The pass cannot have come from an OCCP transfer."
    )
    used = ", ".join(
        f"I3C{ch} (+{falls} scl_falls, +{starts} starts)" for ch, falls, starts in moved
    )
    cocotb.log.info("CHK-OCCP-BUS-ACTIVITY: transfer seen on %s", used)

    assert transfer_landed, (
        f"CHK-OCCP-TRANSFER-LANDED: the target reported the pass magic, but its "
        f"SRAM never held the payload's first and last word at {target_addr:#010x}. "
        f"The backdoor decode is measured against AXI by "
        f"smc_dual_axi_sram_probe_test, so this is the OCCP WRITE stream landing "
        f"somewhere other than the address the ROM was given, not a wrong "
        f"instrument.\n"
        f"target firmware trace:\n{dut_console.tail()}"
    )
    cocotb.log.info(
        "target SRAM peek agrees with the payload image at %#010x",
        target_addr,
    )

    post = await dut_csr.read("TARGET_POST_CODE_FINAL", SCRATCH_POST_CODE)
    assert post_code_error(post) == 0, (
        f"target ROM latched a POST error during the transfer: {describe_post_code(post)}"
    )

    # The payload parks in a loop, so after the JUMP the retired PC stays inside the image.
    final_pc = int(dut.dut_wb_pc0.value)
    harness.dump_cpu_trace(logging.INFO)
    pc_parked_in_payload = target_addr <= final_pc < target_addr + payload_size
    assert pc_in_payload or pc_parked_in_payload, (
        f"target scratch shows the payload's results, but its retired PC "
        f"({final_pc:#x}) was never observed inside the transferred image "
        f"[{target_addr:#x}, {target_addr + payload_size:#x}). "
        "Control transfer to the payload is not demonstrated."
    )
    cocotb.log.info(
        "CHK-OCCP-JUMP-EXECUTED: target retired PC %#x is inside the "
        "transferred image [%#x, %#x) -- the OCCP JUMP transferred control and "
        "the core is parked in the payload",
        final_pc,
        target_addr,
        target_addr + payload_size,
    )

    bfm_console.flush()
    dut_console.flush()
    cocotb.log.info(
        "CHK-OCCP-PAYLOAD-EXECUTED: target scratch0=%#010x (TEST_PASS); the "
        "transferred image ran on the target. Final target POST %s",
        passv,
        describe_post_code(post),
    )
    cocotb.log.info("smc_occp_dual_unsecure_boot_test PASS")
