# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The target ROM parks hart 0 between OCCP commands when the SEP asks.

The controller (occp_park_test) checks that the live target answers a probe with a short
timeout, then writes one block into target SRAM as its last command and reports. The block
must still be partly missing from the SRAM array at that point, held dirty in hart 0's
D-cache. The testbench then acts as the SEP and writes the park request to target scratch 3.
The ROM must set HART0_PARKED and stay in its park loop, the block must now be in the SRAM
array (the ROM wrote back its D-cache before setting the bit), and the same probe sent
afterwards must go unanswered.

Plusargs:
    +rom_bin64=<image>        target production ROM               (required)
    +bfm_rom_hex=<image>      controller occp_park_test image     (required)
    +rom_test_timeout=<ns>    completion bound in ns              (default: DEFAULT_POLL_ITERS)
"""

from __future__ import annotations

import logging

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_virt_console import VirtConsole
from smc_dual_base_test import DualCsr, SmcDualHarness, dual_test, random_seed
from smc_occp_dual_defs import (
    CPU_RESET_VECTOR_ROM,
    SCRATCH_BOOTCODE_ADDR,
    SCRATCH_BOOTCODE_SIZE,
    SCRATCH_PASS_FAIL,
    SCRATCH_TARGET_ADDR,
    TEST_FAIL,
    required_plusarg,
)
from smc_rom_park_defs import (
    PARK_REQ_VALUE,
    POLL_CYCLES,
    SCRATCH_PARK_REQ,
    expect_parked,
    peek_target_sram,
    poll_iterations,
)

# Controller scratch handshake; must match fw/tests/occp_park_test/main.c.
CTRL_RESULT = SCRATCH_BOOTCODE_ADDR  # scratch 5
CTRL_PHASE = SCRATCH_BOOTCODE_SIZE  # scratch 6
CTRL_GO = SCRATCH_TARGET_ADDR  # scratch 7
PHASE_WRITTEN = 0x5041_5231
PHASE_ANSWERED = 0x5041_5232
PHASE_UNANSWERED = 0x5041_5233
PHASE_FAILED = 0x5041_523F
GO = 0x474F_2121
WRITE_ADDR = 0xC008_0000
WRITE_LEN = 256

REQUIRED_EVIDENCE = ("CHK-ROM-PARK-REQUEST",)


def _written_words() -> list[tuple[int, int]]:
    """(address, expected 64-bit word) for each word of the block the controller writes."""
    block = bytes((0x11 + i * 0x5B) & 0xFF for i in range(WRITE_LEN))
    return [
        (WRITE_ADDR + off, int.from_bytes(block[off : off + 8], "little"))
        for off in range(0, WRITE_LEN, 8)
    ]


async def _await_ctrl_phase(dut, bfm_csr, want: tuple[int, ...], poll_iters: int, what: str):
    phase = 0
    for _ in range(poll_iters):
        await ClockCycles(dut.clk_smc_i, POLL_CYCLES)
        phase = await bfm_csr.read("CTRL_PHASE", CTRL_PHASE)
        if phase in want:
            return phase
        ctrl_scratch0 = await bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL)
        if phase == PHASE_FAILED or ctrl_scratch0 == TEST_FAIL:
            raise AssertionError(f"controller failed while waiting for {what}")
    raise AssertionError(f"controller never reached {what}; phase = {phase:#010x}")


@dual_test(REQUIRED_EVIDENCE)
async def smc_rom_park_request_test(harness: SmcDualHarness) -> None:
    dut = harness.dut
    case = "smc_rom_park_request_test"
    required_plusarg("rom_bin64", case)
    required_plusarg("bfm_rom_hex", case)
    poll_iters, poll_source = poll_iterations()
    cocotb.log.info("%s (RANDOM_SEED=%d): %s", case, random_seed(), poll_source)

    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)
    await harness.release_cpu(dut_csr, "dut", CPU_RESET_VECTOR_ROM)
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    try:
        await _await_ctrl_phase(dut, bfm_csr, (PHASE_WRITTEN,), poll_iters, "the SRAM write")

        words = _written_words()
        stale = [addr for addr, want in words if await peek_target_sram(dut, addr) != want]
        if not stale:
            raise AssertionError(
                f"the {WRITE_LEN} written bytes reached the SRAM array before the park, so this "
                "run cannot show that parking writes back the D-cache"
            )

        await dut_csr.write("PARK_REQ", SCRATCH_PARK_REQ, PARK_REQ_VALUE, length=8)
        scratch_9 = await expect_parked(dut, harness, dut_csr, case)

        for addr, want in words:
            got = await peek_target_sram(dut, addr)
            if got != want:
                raise AssertionError(
                    f"SRAM array at {addr:#010x} holds {got:#018x}, expected {want:#018x}: "
                    "the ROM reported parked without writing back the OCCP write"
                )

        await bfm_csr.write("CTRL_GO", CTRL_GO, GO, length=8)
        phase = await _await_ctrl_phase(
            dut, bfm_csr, (PHASE_ANSWERED, PHASE_UNANSWERED), poll_iters, "the probe result"
        )
        probe_rc = await bfm_csr.read("CTRL_RESULT", CTRL_RESULT)
        if phase != PHASE_UNANSWERED:
            raise AssertionError("the parked target answered an OCCP command")
        cocotb.log.info("probe after the park returned OCCP code %#x", probe_rc)
        await expect_parked(dut, harness, dut_csr, case)
    finally:
        dut_console.flush()

    harness.dump_cpu_trace(logging.INFO)
    cocotb.log.info(
        "CHK-ROM-PARK-REQUEST: parked on request (scratch 9 %#010x); %d of %d written words "
        "were dirty before the park and all are in the SRAM array after it; the probe the live "
        "target answered went unanswered after the park (code %#x)",
        scratch_9,
        len(stale),
        len(words),
        probe_rc,
    )
    cocotb.log.info("%s PASS", case)
