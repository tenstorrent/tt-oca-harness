# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smu_smc_boundary_io_test. SEP=0, no Force.

Every SMC-facing boundary signal exercised here is paired with the SMC CSR
that the port_table.adoc row says owns it, so the compare is against a
register the DUT produced rather than against the value the bench drove:

* ``smc_ndmreset_request_i``  -> ``NDM_RESET.NDMRESET_REQUEST`` (read-only
  mirror of the pin), with ``NDMRESET_CLUSTER_COUNT`` read first so a dead
  window cannot pass the mirror compare.
* ``NDM_RESET.NDMRESET_PROCESS`` -> ``smc_ndmreset_process_o``. The register is
  32 bits and only ``CPU_CLUSTER_COUNT`` of them leave the block, so the
  all-ones write is also the port-width check.
* ``smc_ext_interrupts_i``    -> ``smc_base``'s synchronized ``cpu_interrupts_o``
  vector, lane for lane over the driven slice. port_table.adoc calls these
  active-high level inputs, so the release leg requires the vector to follow
  the pins back down rather than latch. PLIC delivery is not claimed here.
* ``RESET_UNIT.SS_CONFIG`` / ``SYNC_REG`` / ``ISOLATE_REQ_REG`` ->
  ``ss_config_o`` / ``sync_irq_o`` / ``isolate_req_o``.
* ``mem_repair_abort_i`` / ``mbist_abort_i`` -> ``DFX_CTRL.STATUS_SMU``. Those
  fields are sticky, so the bit is sampled again after the pin has dropped:
  a pure wire would follow the pin back to zero.
* ``cfg_flr_pf_active_i``     -> ``ISOLATE_REQ_SMC_REG``, ``isolate_req_o`` via
  ``ISOLATE_REQ_SMCEN_REG`` and ``skip_mem_repair_o``. The latch is set by
  hardware and cleared by software, which is what the clear leg checks.

The FLR leg runs last: it leaves an isolation request asserted until the
sequence clears it, and ``ISOLATE_REQ_FLR_RESET_COUNTER_VALUE`` is left at its
reset value of zero so the cool-reset FSM never starts.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_boundary_regs import dfx_ctrl_status_u32
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    axi64_pack32,
    axi64_unpack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smu_scope

NDMRESET_REQUEST = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_REQUEST_BASE_ADDR")
NDMRESET_PROCESS = smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_PROCESS_BASE_ADDR")
NDMRESET_CLUSTER_COUNT = smc_addr(
    "SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR"
)
SS_CONFIG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_BASE_ADDR")
SS_CONFIG_LOCK = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_CONFIG_LOCK_BASE_ADDR")
SYNC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_SYNC_REG_BASE_ADDR")
ISOLATE_REQ_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_REG_BASE_ADDR")
ISOLATE_REQ_SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
ISOLATE_REQ_SMCEN_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMCEN_REG_BASE_ADDR")
ISOLATE_REQ_FLR_RESET_COUNTER = smc_addr(
    "SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR"
)
DFX_STATUS_SMU = smc_addr("SMC_TOP_DFX_CTRL_STATUS_SMU_BASE_ADDR")
SMC_BASE_PATH = "u_smc.u_smc_base"

MEM_REPAIR_ABORT_BM = dfx_ctrl_status_u32("DFX_CTRL_STATUS__STATUS__MEM_REPAIR_ABORT_bm")
MBIST_ABORT_BM = dfx_ctrl_status_u32("DFX_CTRL_STATUS__STATUS__MBIST_ABORT_bm")
MEM_REPAIR_DONE_BM = dfx_ctrl_status_u32("DFX_CTRL_STATUS__STATUS__MEM_REPAIR_DONE_bm")
MBIST_DONE_BM = dfx_ctrl_status_u32("DFX_CTRL_STATUS__STATUS__MBIST_DONE_bm")

# smc_config_pkg::CPU_CLUSTER_COUNT, the elaborated width of the NDM pair.
CPU_CLUSTER_COUNT = 4
CLUSTER_MASK = (1 << CPU_CLUSTER_COUNT) - 1
# smc_base.sv synchronizes smc_ext_interrupts_i with a prim_sync3 and the PLIC
# gateway adds its own stage; the pin is held well past both.
SYNC_CYCLES = 32
EXT_IRQ_LANE = 0
EXT_IRQ_PATTERN = 0xA5A5_5A5A
SS_CONFIG_PATTERN = 0xA5A5_5A5A
ISOLATE_SW_BIT = 0
ISOLATE_FLR_BIT = 1


class smu_smc_boundary_io_seq:
    """SMC boundary inputs and outputs against the CSRs that own them."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.log = test.logger
        self.sb = test.env.scoreboard

    def _sample(self, name: str) -> int:
        pin = getattr(self.dut, name, None)
        if pin is None:
            raise AssertionError(f"{name} unobservable on this TB top")
        val = pin.value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val)

    async def _rd32(self, addr: int, what: str) -> int:
        """One 32-bit CSR read, taken from the lane its address selects."""
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

    async def _wr32(self, addr: int, data: int, what: str) -> None:
        """One 32-bit CSR write, strobed onto the lane its address selects."""
        wstrb, beat = axi64_pack32(addr, data)
        status, _ = await jtag2axi_single_write(
            self.jtag,
            addr,
            beat,
            wstrb=wstrb,
            size=SMC_DBG_AXSIZE_4B,
            require_complete=True,
        )
        require_jtag_tdo_resolved(f"{what} WR @0x{addr:08x}")
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"{what} write @0x{addr:08x} status={status}")

    async def run(self) -> None:
        dut = self.dut
        await self.cfg.reset_done.wait()

        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._sample("tb_smc_jtag2axi_security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI still gated; no CSR leg can run")

        await self._ndmreset_request()
        await self._ndmreset_process()
        await self._ext_interrupt()
        await self._reset_unit_outputs()
        await self._dft_abort_status()
        await self._flr_isolate()

    # ------------------------------------------------------------------
    # S1: the NDM reset request pin as the SMC register mirrors it.
    # ------------------------------------------------------------------
    async def _ndmreset_request(self) -> None:
        dut = self.dut
        count = await self._rd32(NDMRESET_CLUSTER_COUNT, "NDMRESET_CLUSTER_COUNT")
        self.sb.expect_eq(
            "NDMRESET_CLUSTER_COUNT reads the elaborated cluster count",
            count & 0xFF,
            CPU_CLUSTER_COUNT,
            evidence="CHK-SMU-NDMRESET-REQ",
        )
        idle = await self._rd32(NDMRESET_REQUEST, "NDMRESET_REQUEST")
        self.sb.expect_eq(
            "NDMRESET_REQUEST clear while the pin is idle",
            idle & CLUSTER_MASK,
            0,
            evidence="CHK-SMU-NDMRESET-REQ",
        )
        for pattern in (0x5, 0xA):
            dut.tb_smc_ndmreset_request.value = pattern
            await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
            mirrored = await self._rd32(NDMRESET_REQUEST, "NDMRESET_REQUEST")
            self.sb.expect_eq(
                f"NDMRESET_REQUEST mirrors smc_ndmreset_request_i=0x{pattern:x}",
                mirrored & CLUSTER_MASK,
                pattern,
                evidence="CHK-SMU-NDMRESET-REQ",
            )
        dut.tb_smc_ndmreset_request.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        released = await self._rd32(NDMRESET_REQUEST, "NDMRESET_REQUEST")
        self.sb.expect_eq(
            "NDMRESET_REQUEST follows the pin back to zero",
            released & CLUSTER_MASK,
            0,
            evidence="CHK-SMU-NDMRESET-REQ",
        )

    # ------------------------------------------------------------------
    # S2: the NDM reset process register as the boundary presents it.
    # ------------------------------------------------------------------
    async def _ndmreset_process(self) -> None:
        dut = self.dut
        self.sb.expect_eq(
            "smc_ndmreset_process_o clear at its register reset value",
            self._sample("tb_smc_ndmreset_process"),
            0,
            evidence="CHK-SMU-NDMRESET-PROC",
        )
        for written in (0x5, 0xA, 0xFFFF_FFFF, 0x0):
            await self._wr32(NDMRESET_PROCESS, written, "NDMRESET_PROCESS")
            await ClockCycles(dut.clk_smu_i, 4)
            readback = await self._rd32(NDMRESET_PROCESS, "NDMRESET_PROCESS")
            self.sb.expect_eq(
                f"NDMRESET_PROCESS holds 0x{written:08x}",
                readback,
                written,
                evidence="CHK-SMU-NDMRESET-PROC",
            )
            self.sb.expect_eq(
                f"smc_ndmreset_process_o carries NDMRESET_PROCESS[{CPU_CLUSTER_COUNT - 1}:0] "
                f"of 0x{written:08x}",
                self._sample("tb_smc_ndmreset_process"),
                written & CLUSTER_MASK,
                evidence="CHK-SMU-NDMRESET-PROC",
            )

    # ------------------------------------------------------------------
    # S3: an external interrupt lane where the SMC receives it.
    # ------------------------------------------------------------------
    async def _ext_interrupt(self) -> None:
        dut = self.dut
        smu = smu_scope(dut)
        received = hier(smu, f"{SMC_BASE_PATH}.cpu_interrupts_o")
        self.sb.expect_eq(
            "no external interrupt lane set at the SMC while the pins are idle",
            sample(received, "cpu_interrupts_o") & 0xFFFF_FFFF,
            0,
            evidence="CHK-SMU-EXT-IRQ",
        )
        for pattern in (1 << EXT_IRQ_LANE, 1 << 31, EXT_IRQ_PATTERN):
            dut.tb_smc_ext_interrupts.value = pattern
            await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
            self.sb.expect_eq(
                f"smc_ext_interrupts_i=0x{pattern:08x} reaches the SMC on the same lanes",
                sample(received, "cpu_interrupts_o") & 0xFFFF_FFFF,
                pattern,
                evidence="CHK-SMU-EXT-IRQ",
            )
        # port_table.adoc calls these active-high level inputs, so the SMC-side
        # vector has to follow the pins back down and not latch.
        dut.tb_smc_ext_interrupts.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.sb.expect_eq(
            "the level inputs release at the SMC with the pins",
            sample(received, "cpu_interrupts_o") & 0xFFFF_FFFF,
            0,
            evidence="CHK-SMU-EXT-IRQ",
        )

    # ------------------------------------------------------------------
    # S4: the reset-unit registers that terminate on wrapper outputs.
    # ------------------------------------------------------------------
    async def _reset_unit_outputs(self) -> None:
        dut = self.dut
        lock = await self._rd32(SS_CONFIG_LOCK, "SS_CONFIG_LOCK")
        self.sb.expect_eq(
            "SS_CONFIG_LOCK open at reset, so the whole word is writable",
            lock,
            0,
            evidence="CHK-SMU-SS-CONFIG",
        )
        await self._wr32(SS_CONFIG, SS_CONFIG_PATTERN, "SS_CONFIG")
        await ClockCycles(dut.clk_smu_i, 4)
        self.sb.expect_eq(
            "ss_config_o carries SS_CONFIG",
            self._sample("tb_ss_config"),
            SS_CONFIG_PATTERN,
            evidence="CHK-SMU-SS-CONFIG",
        )
        readback = await self._rd32(SS_CONFIG, "SS_CONFIG")
        self.sb.expect_eq(
            "SS_CONFIG reads back what the port presents",
            readback,
            SS_CONFIG_PATTERN,
            evidence="CHK-SMU-SS-CONFIG",
        )
        await self._wr32(SS_CONFIG, 0, "SS_CONFIG")
        await ClockCycles(dut.clk_smu_i, 4)
        self.sb.expect_eq(
            "ss_config_o clears with the register",
            self._sample("tb_ss_config"),
            0,
            evidence="CHK-SMU-SS-CONFIG",
        )

        self.sb.expect_eq(
            "sync_irq_o clear at the SYNC_REG reset value",
            self._sample("tb_sync_irq"),
            0,
            evidence="CHK-SMU-SYNC-IRQ",
        )
        await self._wr32(SYNC_REG, 1, "SYNC_REG")
        await ClockCycles(dut.clk_smu_i, 4)
        self.sb.expect_eq(
            "sync_irq_o is SYNC_REG.sync",
            self._sample("tb_sync_irq"),
            1,
            evidence="CHK-SMU-SYNC-IRQ",
        )
        await self._wr32(SYNC_REG, 0, "SYNC_REG")
        await ClockCycles(dut.clk_smu_i, 4)
        self.sb.expect_eq(
            "sync_irq_o clears with SYNC_REG.sync",
            self._sample("tb_sync_irq"),
            0,
            evidence="CHK-SMU-SYNC-IRQ",
        )

        sw_bit = 1 << ISOLATE_SW_BIT
        await self._wr32(ISOLATE_REQ_REG, sw_bit, "ISOLATE_REQ_REG")
        await ClockCycles(dut.clk_smu_i, 4)
        self.sb.expect_eq(
            "isolate_req_o carries the software isolation term",
            self._sample("tb_isolate_req"),
            sw_bit,
            evidence="CHK-SMU-ISOLATE-REQ",
        )
        await self._wr32(ISOLATE_REQ_REG, 0, "ISOLATE_REQ_REG")
        await ClockCycles(dut.clk_smu_i, 4)
        self.sb.expect_eq(
            "isolate_req_o clears with the software term",
            self._sample("tb_isolate_req"),
            0,
            evidence="CHK-SMU-ISOLATE-REQ",
        )

    # ------------------------------------------------------------------
    # S5: the DFT abort pins as the sticky DFX status latches them.
    # ------------------------------------------------------------------
    async def _dft_abort_status(self) -> None:
        dut = self.dut
        before = await self._rd32(DFX_STATUS_SMU, "DFX STATUS_SMU")
        self.sb.expect_eq(
            "DFX STATUS_SMU already carries the asserted done pins",
            before & (MEM_REPAIR_DONE_BM | MBIST_DONE_BM),
            MEM_REPAIR_DONE_BM | MBIST_DONE_BM,
            evidence="CHK-SMU-DFT-ABORT",
        )
        self.sb.expect_eq(
            "neither abort latched before the pins are driven",
            before & (MEM_REPAIR_ABORT_BM | MBIST_ABORT_BM),
            0,
            evidence="CHK-SMU-DFT-ABORT",
        )
        dut.tb_mem_repair_abort.value = 1
        dut.tb_mbist_abort.value = 1
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        driven = await self._rd32(DFX_STATUS_SMU, "DFX STATUS_SMU")
        self.sb.expect_eq(
            "both abort pins reach DFX STATUS_SMU",
            driven & (MEM_REPAIR_ABORT_BM | MBIST_ABORT_BM),
            MEM_REPAIR_ABORT_BM | MBIST_ABORT_BM,
            evidence="CHK-SMU-DFT-ABORT",
        )
        dut.tb_mem_repair_abort.value = 0
        dut.tb_mbist_abort.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        after = await self._rd32(DFX_STATUS_SMU, "DFX STATUS_SMU")
        self.sb.expect_eq(
            "the abort fields are sticky: they hold with both pins released",
            after & (MEM_REPAIR_ABORT_BM | MBIST_ABORT_BM),
            MEM_REPAIR_ABORT_BM | MBIST_ABORT_BM,
            evidence="CHK-SMU-DFT-ABORT",
        )

    # ------------------------------------------------------------------
    # S6: the FLR isolation path. Runs last -- it leaves an isolation request
    # asserted until this leg clears it.
    # ------------------------------------------------------------------
    async def _flr_isolate(self) -> None:
        dut = self.dut
        flr_bit = 1 << ISOLATE_FLR_BIT
        counter = await self._rd32(
            ISOLATE_REQ_FLR_RESET_COUNTER, "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE"
        )
        self.sb.expect_eq(
            "the FLR reset counter is left at zero, so no cool reset is launched",
            counter,
            0,
            evidence="CHK-SMU-FLR-ISOLATE",
        )
        await self._wr32(ISOLATE_REQ_SMCEN_REG, flr_bit, "ISOLATE_REQ_SMCEN_REG")
        await ClockCycles(dut.clk_smu_i, 4)
        self.sb.expect_eq(
            "enabling the FLR term alone does not raise isolate_req_o",
            self._sample("tb_isolate_req"),
            0,
            evidence="CHK-SMU-FLR-ISOLATE",
        )
        self.sb.expect_eq(
            "skip_mem_repair_o clear before the FLR request",
            self._sample("tb_skip_mem_repair"),
            0,
            evidence="CHK-SMU-FLR-ISOLATE",
        )

        dut.tb_cfg_flr_pf_active.value = 1
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        latched = await self._rd32(ISOLATE_REQ_SMC_REG, "ISOLATE_REQ_SMC_REG")
        self.sb.expect_eq(
            "a cfg_flr_pf_active_i rising edge sets the SMC isolation latch",
            latched & 1,
            1,
            evidence="CHK-SMU-FLR-ISOLATE",
        )
        self.sb.expect_eq(
            "the latch reaches isolate_req_o through ISOLATE_REQ_SMCEN_REG",
            self._sample("tb_isolate_req"),
            flr_bit,
            evidence="CHK-SMU-FLR-ISOLATE",
        )
        self.sb.expect_eq(
            "skip_mem_repair_o follows the isolation request",
            self._sample("tb_skip_mem_repair"),
            1,
            evidence="CHK-SMU-FLR-ISOLATE",
        )

        # Hardware sets the latch, software clears it: dropping the pin is not
        # enough, which is what the two samples either side of the write show.
        dut.tb_cfg_flr_pf_active.value = 0
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.sb.expect_eq(
            "the latch holds when cfg_flr_pf_active_i drops",
            self._sample("tb_skip_mem_repair"),
            1,
            evidence="CHK-SMU-FLR-ISOLATE",
        )
        await self._wr32(ISOLATE_REQ_SMC_REG, 0, "ISOLATE_REQ_SMC_REG")
        await ClockCycles(dut.clk_smu_i, SYNC_CYCLES)
        self.sb.expect_eq(
            "a software write clears the latch and releases isolate_req_o",
            self._sample("tb_isolate_req"),
            0,
            evidence="CHK-SMU-FLR-ISOLATE",
        )
        self.sb.expect_eq(
            "skip_mem_repair_o releases with the latch",
            self._sample("tb_skip_mem_repair"),
            0,
            evidence="CHK-SMU-FLR-ISOLATE",
        )
        await self._wr32(ISOLATE_REQ_SMCEN_REG, 0, "ISOLATE_REQ_SMCEN_REG")
