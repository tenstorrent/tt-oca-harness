# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_cool_reset_pin_test. No Force.

``rst_cool_n_from_pin_i`` is the cool reset a primary chiplet sends a
secondary one. ``hw/sys/smu/doc/port_table.adoc`` routes the pin to the
SMC reset unit and does not state a deglitch width. The bench observes
the SMC primary reset on ``obs_smc_rst_n_o`` and proves both halves of
the pin contract: a ``FILTERED_PULSE_REF_CYCLES`` pulse leaves the SMC
running, a hold that lasts past that pulse asserts the reset, and the
SMC boots again when the pin releases.

The primary reset also clears ``DFX_CTRL.STATUS_SMU``, whose done and pass
fields are set-only mirrors of ``mem_repair_done_i``, ``mem_repair_success_i``,
``mbist_done_i`` and ``mbist_pass_i``. The bench asserts those straps at
bring-up, so the fields read set before anything else runs; holding the
straps low across the pin reset is the only way to read the fields clear,
which is what pairs each strap with its register bit.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_boundary_regs import dfx_ctrl_status_u32
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_unpack32,
    jtag2axi_single_read,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)

DFX_STATUS_SMU = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
MEM_REPAIR_DONE_BM = dfx_ctrl_status_u32("DFX_CTRL_STATUS__STATUS__MEM_REPAIR_DONE_bm")
MEM_REPAIR_SUCCESS_BM = dfx_ctrl_status_u32("DFX_CTRL_STATUS__STATUS__MEM_REPAIR_SUCCESS_bm")
MBIST_DONE_BM = dfx_ctrl_status_u32("DFX_CTRL_STATUS__STATUS__MBIST_DONE_bm")
MBIST_PASS_BM = dfx_ctrl_status_u32("DFX_CTRL_STATUS__STATUS__MBIST_PASS_bm")
DFT_DONE_BM = MEM_REPAIR_DONE_BM | MEM_REPAIR_SUCCESS_BM | MBIST_DONE_BM | MBIST_PASS_BM

# Pulse length this leaf proves is filtered. The hold side waits until
# the primary reset is observed and refuses an assertion earlier than this.
FILTERED_PULSE_REF_CYCLES = 28
HOLD_AFTER_ASSERT_REF_CYCLES = 32
ASSERT_BOUND_REF_CYCLES = 4 * HOLD_AFTER_ASSERT_REF_CYCLES
RELEASE_BOUND_REF_CYCLES = 8192
SYNC_CYCLES = 32
EVIDENCE_DEGLITCH = "CHK-SMU-COOL-PIN-DEGLITCH"
EVIDENCE_RESET = "CHK-SMU-COOL-PIN-RESET"
EVIDENCE_DFT = "CHK-SMU-DFT-DONE-STATUS"


class smu_smc_cool_reset_pin_seq:
    """The cool reset pin against the SMC primary reset it asserts."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _bit(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _rd32(self, addr: int, what: str) -> int:
        status, rdata = await jtag2axi_single_read(
            self.jtag,
            addr,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} RD @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} read @0x{addr:08x} status={status}")
        return axi64_unpack32(addr, rdata)

    async def _wait_smc_reset(self, level: int, bound: int, what: str) -> int:
        dut = self.dut
        for cycle in range(bound):
            if self._bit("obs_smc_rst_n_o") == level:
                return cycle
            await RisingEdge(dut.clk_ref_i)
        raise AssertionError(
            f"TIMEOUT {what}: obs_smc_rst_n_o never read {level} within {bound} clk_ref"
        )

    def _require_csr_path(self) -> None:
        if self._bit("tb_smc_jtag2axi_security_disable"):
            raise AssertionError("SMC JTAG2AXI gated; STATUS_SMU cannot be read")

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()

        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        self._require_csr_path()

        # S1: the straps asserted at bring-up have already set the fields.
        booted = await self._rd32(DFX_STATUS_SMU, "DFX STATUS_SMU")
        sb.expect_eq(
            "STATUS_SMU carries the four DFT done/pass straps after bring-up",
            booted & DFT_DONE_BM,
            DFT_DONE_BM,
            evidence=EVIDENCE_DFT,
        )
        sb.expect_eq(
            "the SMC is out of reset before the pin is driven",
            self._bit("obs_smc_rst_n_o"),
            1,
            evidence=EVIDENCE_RESET,
        )

        # S2: a pulse of FILTERED_PULSE_REF_CYCLES never reaches the primary reset.
        dut.tb_cool_reset_pin.value = 1
        low_samples = 0
        for _ in range(FILTERED_PULSE_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            low_samples += 1 - self._bit("obs_smc_rst_n_o")
        dut.tb_cool_reset_pin.value = 0
        for _ in range(ASSERT_BOUND_REF_CYCLES):
            await RisingEdge(dut.clk_ref_i)
            low_samples += 1 - self._bit("obs_smc_rst_n_o")
        sb.expect_eq(
            f"a {FILTERED_PULSE_REF_CYCLES}-clk_ref pulse on rst_cool_n_from_pin_i is "
            f"filtered: the SMC stays out of reset during the pulse and the next "
            f"{ASSERT_BOUND_REF_CYCLES} clk_ref",
            low_samples,
            0,
            evidence=EVIDENCE_DEGLITCH,
        )

        # S3: a hold past that pulse asserts the primary reset, with the DFT
        # straps taken low first so the reset value of STATUS_SMU is observable.
        dut.tb_mem_repair_hold.value = 1
        dut.tb_mbist_hold.value = 1
        await ClockCycles(dut.clk_ref_i, 2)
        dut.tb_cool_reset_pin.value = 1
        asserted_after = await self._wait_smc_reset(0, ASSERT_BOUND_REF_CYCLES, "cool reset assert")
        sb.expect_eq(
            f"the held pin asserts the SMC primary reset no earlier than the "
            f"{FILTERED_PULSE_REF_CYCLES}-clk_ref pulse that was filtered "
            f"({asserted_after} clk_ref)",
            asserted_after >= FILTERED_PULSE_REF_CYCLES,
            True,
            evidence=EVIDENCE_RESET,
        )
        await ClockCycles(dut.clk_ref_i, HOLD_AFTER_ASSERT_REF_CYCLES)
        sb.expect_eq(
            "the SMC stays in reset while the pin is held",
            self._bit("obs_smc_rst_n_o"),
            0,
            evidence=EVIDENCE_RESET,
        )

        # S4: releasing the pin releases the SMC.
        dut.tb_cool_reset_pin.value = 0
        released_after = await self._wait_smc_reset(
            1, RELEASE_BOUND_REF_CYCLES, "cool reset release"
        )
        self.log.info("SMC primary reset released %d clk_ref after the pin", released_after)
        sb.expect_eq(
            "the SMC leaves reset after rst_cool_n_from_pin_i releases",
            self._bit("obs_smc_rst_n_o"),
            1,
            evidence=EVIDENCE_RESET,
        )
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self._require_csr_path()

        # S5: STATUS_SMU came up clear, because the straps were low through the
        # reset, and each field sets only when its strap rises.
        cleared = await self._rd32(DFX_STATUS_SMU, "DFX STATUS_SMU")
        sb.expect_eq(
            "STATUS_SMU reads the done/pass fields clear after a reset with the straps low",
            cleared & DFT_DONE_BM,
            0,
            evidence=EVIDENCE_DFT,
        )
        dut.tb_mem_repair_hold.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        repair = await self._rd32(DFX_STATUS_SMU, "DFX STATUS_SMU")
        sb.expect_eq(
            "mem_repair_done_i and mem_repair_success_i set their fields; the MBIST pair stays clear",
            repair & DFT_DONE_BM,
            MEM_REPAIR_DONE_BM | MEM_REPAIR_SUCCESS_BM,
            evidence=EVIDENCE_DFT,
        )
        dut.tb_mbist_hold.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        mbist = await self._rd32(DFX_STATUS_SMU, "DFX STATUS_SMU")
        sb.expect_eq(
            "mbist_done_i and mbist_pass_i set their fields",
            mbist & DFT_DONE_BM,
            DFT_DONE_BM,
            evidence=EVIDENCE_DFT,
        )
        dut.tb_mem_repair_hold.value = 1
        dut.tb_mbist_hold.value = 1
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        sticky = await self._rd32(DFX_STATUS_SMU, "DFX STATUS_SMU")
        sb.expect_eq(
            "the four fields are sticky: they hold with the straps taken low again",
            sticky & DFT_DONE_BM,
            DFT_DONE_BM,
            evidence=EVIDENCE_DFT,
        )
        dut.tb_mem_repair_hold.value = 0
        dut.tb_mbist_hold.value = 0
