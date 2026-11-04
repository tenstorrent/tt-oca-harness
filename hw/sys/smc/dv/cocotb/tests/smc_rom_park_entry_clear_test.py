# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The target ROM discards a park request left over from before its reset.

The testbench leaves the park request value in target scratch 3 when it releases the target
from reset. The ROM must clear it on entry and keep servicing OCCP: the occp_sanity
controller's GET_VERSION and its write of TEST_PASS into target scratch 0 must both complete,
and HART0_PARKED must stay clear.

Plusargs:
    +rom_bin64=<image>        target production ROM               (required)
    +bfm_rom_hex=<image>      controller occp_sanity image        (required)
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
    SCRATCH_PASS_FAIL,
    SCRATCH_STATUS_TO_SEP,
    TEST_FAIL,
    TEST_PASS,
    required_plusarg,
)
from smc_rom_park_defs import (
    HART0_PARKED,
    PARK_REQ_VALUE,
    POLL_CYCLES,
    SCRATCH_PARK_REQ,
    park_loop_pcs,
    poll_iterations,
)

REQUIRED_EVIDENCE = ("CHK-ROM-PARK-ENTRY-CLEAR",)


@dual_test(REQUIRED_EVIDENCE)
async def smc_rom_park_entry_clear_test(harness: SmcDualHarness) -> None:
    dut = harness.dut
    case = "smc_rom_park_entry_clear_test"
    required_plusarg("rom_bin64", case)
    required_plusarg("bfm_rom_hex", case)
    poll_iters, poll_source = poll_iterations()
    cocotb.log.info("%s (RANDOM_SEED=%d): %s", case, random_seed(), poll_source)

    await harness.bring_up(hold_dut_boot=True, hold_bfm_boot=True)
    dut_console = VirtConsole(dut.dut_scratch2, "target-fw")
    cocotb.start_soon(dut_console.run())

    dut_csr = DualCsr("s_axi", dut.dut_rst_primary_smc_clk_no)
    bfm_csr = DualCsr("bfm_axi", dut.bfm_rst_primary_smc_clk_no)
    await harness.release_cpu(
        dut_csr, "dut", CPU_RESET_VECTOR_ROM, preload=((SCRATCH_PARK_REQ, PARK_REQ_VALUE),)
    )
    await harness.release_cpu(bfm_csr, "bfm", CPU_RESET_VECTOR_ROM)

    try:
        for _ in range(poll_iters):
            await ClockCycles(dut.clk_smc_i, POLL_CYCLES)
            target_scratch0 = await dut_csr.read("TARGET_PASS", SCRATCH_PASS_FAIL)
            ctrl_scratch0 = await bfm_csr.read("CTRL_PASS", SCRATCH_PASS_FAIL)
            if TEST_FAIL in (target_scratch0, ctrl_scratch0):
                raise AssertionError("the OCCP exchange failed after reset")
            if target_scratch0 == TEST_PASS:
                break
        else:
            raise AssertionError(
                "the target never serviced the controller's OCCP write; it may have parked "
                "on the stale request"
            )

        park_req = await dut_csr.read("PARK_REQ", SCRATCH_PARK_REQ)
        scratch_9 = await dut_csr.read("TARGET_SEP_STATUS", SCRATCH_STATUS_TO_SEP)
        if park_req != 0:
            raise AssertionError(f"scratch 3 still holds {park_req:#010x}; the ROM must clear it")
        if scratch_9 & HART0_PARKED:
            raise AssertionError(
                f"HART0_PARKED set (scratch 9 {scratch_9:#010x}) without a request"
            )
        pc = int(dut.dut_wb_pc0.value)
        if pc in park_loop_pcs():
            raise AssertionError(f"hart 0 is in smc_park_hart0 (retired {pc:#x})")
    finally:
        dut_console.flush()

    harness.dump_cpu_trace(logging.INFO)
    cocotb.log.info(
        "CHK-ROM-PARK-ENTRY-CLEAR: stale request cleared, OCCP serviced, scratch 9 %#010x",
        scratch_9,
    )
    cocotb.log.info("%s PASS", case)
