# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A cold reset in the middle of a production-ROM boot must give a clean second boot.

clk_rst.adoc: a cold-reset pulse that passes the 32-cycle de-glitcher resets the primary
domain, and fuse sensing restarts; rom.adoc: the core restarts at the cold-reset vector
0xC0040000. The ROM has no reset handler; a second boot is just a boot from the top.

    1. Release only the target; the controller stays in boot_stall.
    2. Once the target POST reports IFACE_CONFIG, write a seeded non-default value to
       RESET_VECTOR_0, pull rst_cold_ni low until the primary reset asserts, re-hold
       boot_stall, release, and wait for strap capture and fuse sense.
    3. Require RESET_VECTOR_0 back at its reset value, then release the target and the
       occp_sanity controller as in a first boot.
    4. Require the controller's GetVersion and WriteData (TEST_PASS in target scratch 0),
       hart 0's first retirement at the reset vector, and the second boot's status entries in
       the SMC status ring in order.

Scratch 15 is not required to clear: the ROM preserves it across resets by design.

Plusargs:
    +rom_bin64=<image>        target production ROM               (required)
    +bfm_rom_hex=<image>      occp_sanity controller image        (required)
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.smc_sep_ring_buffer_driver import (
    RB_ENTRIES_OFFSET,
    RB_HEAD_OFFSET,
    RB_TAIL_OFFSET,
    RING_BUFFER_SIZE,
)
from env.smc_virt_console import VirtConsole
from smc_dual_base_test import DualCsr, SmcDualHarness, dual_test, random_seed
from smc_occp_dual_defs import (
    CPU_CTRL_RESET_VECTOR,
    CPU_RESET_VECTOR_ROM,
    POST_CODE_BOOT_PHASE_IFACE_CONFIG,
    POST_CODE_BOOT_PHASE_NAMES,
    POST_CODE_BOOT_PHASE_OCCP_PROC,
    SCRATCH_POST_CODE,
    SCRATCH_STATUS_BUFFER_ADDR,
    SCRATCH_STATUS_TO_SEP,
    SMC_SRAM_BASE,
    STRAP_BITS,
    STRAP_PRIMARY_CHIPLET,
    TEST_PASS,
    describe_post_code,
    expected_boot_statuses,
    post_code_boot_phase,
    required_plusarg,
)
from smc_occp_rom_only_test import await_occp_verdict
from smc_reg import CPU_CTRL_RESET_VECTOR_REG_DEFAULT

CASE = "smc_prod_rom_mid_boot_cold_reset_test"

PC_MASK = (1 << 32) - 1

# Fine enough to see IFACE_CONFIG before OCCP init finishes.
PHASE_POLL_CYCLES = 100
PHASE_POLL_ITERS = 200_000
# Ceilings, never the measured quantity: the de-glitcher needs 32 clk_ref_i samples.
RESET_ASSERT_BOUND_REF = 400
RESET_HOLD_REF = 32
RESET_RELEASE_BOUND_REF = 4000
SENSE_BOUND_CYCLES = 200_000

# scratch 9 bit 2: scratch 11 holds the SEP ring offset.
STATUS_BUFFER_READY = 1 << 2
# smc_status.h places the SMC ring directly below the SEP ring.
RING_BYTES = RB_ENTRIES_OFFSET + RING_BUFFER_SIZE * 4

REQUIRED_EVIDENCE = (
    "CHK-OCCP-SANITY",
    "CHK-ROM-COLD-RESET-INTERRUPT",
    "CHK-ROM-COLD-RESET-RESENSE",
    "CHK-ROM-COLD-RESET-RESTART",
    "CHK-ROM-COLD-RESET-STATUS",
    "CHK-ROM-COLD-RESET-OCCP",
)


async def _wait_level(clk, signal, level: int, bound: int, what: str) -> int:
    for cycle in range(bound + 1):
        if int(signal.value) == level:
            return cycle
        await RisingEdge(clk)
    raise AssertionError(f"{what}: the signal never reached {level} within {bound} cycles")


async def _wait_for_phase(dut, dut_csr: DualCsr, phase: int) -> tuple[int, list[int]]:
    trace: list[int] = []
    code = 0
    for _ in range(PHASE_POLL_ITERS):
        await ClockCycles(dut.clk_smc_i, PHASE_POLL_CYCLES)
        code = await dut_csr.read("TARGET_POST_CODE", SCRATCH_POST_CODE)
        seen = post_code_boot_phase(code)
        if not trace or trace[-1] != seen:
            trace.append(seen)
        if seen == phase:
            return code, trace
        if seen >= POST_CODE_BOOT_PHASE_OCCP_PROC:
            break
    raise AssertionError(
        f"first boot never showed POST {POST_CODE_BOOT_PHASE_NAMES[phase]} before OCCP_PROC: "
        f"last {describe_post_code(code)}, phases {[hex(p) for p in trace]}"
    )


class _FirstRetirement:
    """Records hart 0's first retired PC after its core reset next releases."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.pc: int | None = None
        self.task = cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        dut = self.dut
        while int(dut.dut_cpu_core_reset_n.value):
            await RisingEdge(dut.clk_smc_i)
        while True:
            await RisingEdge(dut.clk_smc_i)
            if int(dut.dut_cpu_core_reset_n.value) and int(dut.dut_cpu_trace_valid.value):
                self.pc = int(dut.dut_cpu_trace_pc.value) & PC_MASK
                return


async def _read_smc_ring(dut_csr: DualCsr) -> tuple[int, int, int, list[int]]:
    ready = await dut_csr.read("SEP_STATUS", SCRATCH_STATUS_TO_SEP)
    offset = await dut_csr.read("SEP_BUF_OFFSET", SCRATCH_STATUS_BUFFER_ADDR)
    if not ready & STATUS_BUFFER_READY or offset in (0, 0xFFFF_FFFF):
        raise AssertionError(
            f"second boot published no SEP ring: scratch 9 = {ready:#010x}, "
            f"scratch 11 = {offset:#010x}"
        )
    base = SMC_SRAM_BASE + offset - RING_BYTES
    head = await dut_csr.read("SMC_RB_HEAD", base + RB_HEAD_OFFSET)
    tail = await dut_csr.read("SMC_RB_TAIL", base + RB_TAIL_OFFSET)
    if head >= RING_BUFFER_SIZE or tail >= RING_BUFFER_SIZE:
        raise AssertionError(f"SMC ring at {base:#010x} has head={head} tail={tail}")
    entries = []
    index = tail
    while index != head:
        entries.append(await dut_csr.read("SMC_RB_ENTRY", base + RB_ENTRIES_OFFSET + index * 4))
        index = (index + 1) % RING_BUFFER_SIZE
    return base, head, tail, entries


@dual_test(REQUIRED_EVIDENCE)
async def smc_prod_rom_mid_boot_cold_reset_test(harness: SmcDualHarness) -> None:
    dut = harness.dut
    required_plusarg("rom_bin64", CASE)
    required_plusarg("bfm_rom_hex", CASE)
    cocotb.log.info("%s (RANDOM_SEED=%d)", CASE, random_seed())

    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)
    bfm_console = VirtConsole(dut.bfm_scratch2, "ctrl-fw")
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(bfm_console.run())
    cocotb.start_soon(dut_console.run())
    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)

    # First boot: the target alone.
    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    post, first_trace = await _wait_for_phase(dut, dut_csr, POST_CODE_BOOT_PHASE_IFACE_CONFIG)
    first_reads = int(dut.dut_rom_read_count.value)
    ctrl_reads = int(dut.bfm_rom_read_count.value)
    sense_before = int(dut.dut_fuse_sense_done_o.value)
    if not first_reads or ctrl_reads or sense_before != 1:
        raise AssertionError(
            f"first boot at {describe_post_code(post)}: target rom_reads={first_reads}, "
            f"controller rom_reads={ctrl_reads}, target fuse_sense_done={sense_before}; the "
            "interrupt needs a running target, an idle controller and sensed fuses"
        )
    cocotb.log.info(
        "CHK-ROM-COLD-RESET-INTERRUPT: first boot interrupted at POST %s (phases %s) after %d "
        "target ROM reads; controller still in boot_stall with 0 ROM reads; fuse_sense_done=1",
        describe_post_code(post),
        [hex(p) for p in first_trace],
        first_reads,
    )

    # Hart 0 latched its vector at core reset release, so this value only shows whether the
    # cold reset restores the register. Bit 55 set keeps it off the reset value.
    sentinel = (1 << 55) | random.Random(f"{CASE}-{random_seed()}").getrandbits(54) << 1
    await dut_csr.write("RESET_VECTOR_0", CPU_CTRL_RESET_VECTOR[0], sentinel, length=8)
    planted = await dut_csr.read("RESET_VECTOR_0", CPU_CTRL_RESET_VECTOR[0], length=8)
    if planted != sentinel:
        raise AssertionError(
            f"RESET_VECTOR_0 reads {planted:#x} after writing {sentinel:#x} before the cold "
            "reset; the restore check needs a non-default value in the register"
        )

    # The real cold-reset pin; it resets both instances.
    dut.rst_cold_ni.value = 0
    asserted = await _wait_level(
        dut.clk_ref_i, dut.dut_rst_primary_smc_clk_no, 0, RESET_ASSERT_BOUND_REF, "cold assert"
    )
    if int(dut.dut_rst_cold_stable_ref_clk_no.value) != 0:
        raise AssertionError("primary reset asserted without the cold-stable reset")
    sense_low = await _wait_level(
        dut.clk_smc_i, dut.dut_fuse_sense_done_o, 0, SENSE_BOUND_CYCLES, "fuse sense clear"
    )
    # Held from here, so the reprogrammed vectors land before the cores fetch again.
    dut.dut_boot_stall_hold.value = 1
    for _ in range(RESET_HOLD_REF):
        await RisingEdge(dut.clk_ref_i)
        if int(dut.dut_rst_primary_smc_clk_no.value) != 0:
            raise AssertionError("primary reset released while rst_cold_ni was still low")
    dut.rst_cold_ni.value = 1
    await harness._await_strap_capture()
    released = await _wait_level(
        dut.clk_ref_i, dut.dut_rst_primary_smc_clk_no, 1, RESET_RELEASE_BOUND_REF, "release"
    )
    resensed = await _wait_level(
        dut.clk_smc_i, dut.dut_fuse_sense_done_o, 1, SENSE_BOUND_CYCLES, "fuse re-sense"
    )
    cocotb.log.info(
        "CHK-ROM-COLD-RESET-RESENSE: primary reset asserted %d clk_ref_i after rst_cold_ni fell, "
        "with rst_cold_stable low; fuse_sense_done 1->0 (%d clk_smc_i after assert) and 0->1 "
        "again %d clk_smc_i after strap capture; primary reset released after %d clk_ref_i",
        asserted,
        sense_low,
        resensed,
        released,
    )

    vector = await dut_csr.read("RESET_VECTOR_0", CPU_CTRL_RESET_VECTOR[0], length=8)
    if vector != CPU_CTRL_RESET_VECTOR_REG_DEFAULT:
        raise AssertionError(
            f"RESET_VECTOR_0 = {vector:#x} after the cold reset (written {sentinel:#x} before "
            f"it), not the reset value {CPU_CTRL_RESET_VECTOR_REG_DEFAULT:#x}"
        )
    reads_after_reset = int(dut.dut_rom_read_count.value)
    first_retire = _FirstRetirement(dut)

    # Second boot, as a first boot.
    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)
    result = await await_occp_verdict(
        harness, dut_csr, bfm_csr, case=CASE, consoles=(bfm_console, dut_console)
    )

    second_reads = int(dut.dut_rom_read_count.value)
    if first_retire.pc != CPU_RESET_VECTOR_ROM or second_reads <= reads_after_reset:
        raise AssertionError(
            f"second boot: first retired pc={first_retire.pc!r}, want {CPU_RESET_VECTOR_ROM:#x}; "
            f"target rom_reads {reads_after_reset}->{second_reads}"
        )
    cocotb.log.info(
        "CHK-ROM-COLD-RESET-RESTART: RESET_VECTOR_0 %#x before the cold reset, reset to %#x; "
        "hart 0 first retired %#x after the core reset released; target ROM reads %d->%d in "
        "the second boot",
        sentinel,
        vector,
        first_retire.pc,
        reads_after_reset,
        second_reads,
    )

    primary = bool(harness.straps["dut"] >> STRAP_PRIMARY_CHIPLET & 1)
    recovery = bool(harness.straps["dut"] >> STRAP_BITS["BOOT_RECOVERY"] & 1)
    expected = expected_boot_statuses(primary, recovery)
    base, head, tail, entries = await _read_smc_ring(dut_csr)
    if entries != expected:
        raise AssertionError(
            f"SMC ring at {base:#010x} (tail={tail} head={head}) after the second boot holds "
            f"{[hex(e) for e in entries]}, expected exactly {[hex(e) for e in expected]}"
        )
    cocotb.log.info(
        "CHK-ROM-COLD-RESET-STATUS: SMC ring at %#010x re-initialised (tail=%d head=%d) and holds "
        "only the second boot, in order: %s",
        base,
        tail,
        head,
        ", ".join(f"{e:#010x}" for e in entries),
    )

    if result.target_scratch0 != TEST_PASS:
        raise AssertionError(
            f"target scratch 0 = {result.target_scratch0:#010x}; only the controller's "
            f"serviced WriteData writes {TEST_PASS:#010x}"
        )
    if post_code_boot_phase(result.target_post_code) != POST_CODE_BOOT_PHASE_OCCP_PROC:
        raise AssertionError(f"target POST {describe_post_code(result.target_post_code)}")
    cocotb.log.info(
        "CHK-ROM-COLD-RESET-OCCP: after the second boot the controller's GetVersion and WriteData "
        "were serviced (target scratch0=%#010x), POST %s",
        result.target_scratch0,
        describe_post_code(result.target_post_code),
    )
    cocotb.log.info("%s PASS", CASE)
