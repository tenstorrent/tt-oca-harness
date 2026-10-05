# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DATA hang-detector stall via DMA + tb_output_axi_resp_hold. Not irq_test, SEP, or SYS."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge

from ._hang_status import check_hang_status
from .smc_addr_map import (
    DMA_CONFIG_ENABLED_ND,
    DMA_CTRL_CONFIG,
    DMA_CTRL_DONE_0,
    DMA_CTRL_DST_ADDRESS_HI,
    DMA_CTRL_DST_ADDRESS_LO,
    DMA_CTRL_DST_STRIDE_HI,
    DMA_CTRL_DST_STRIDE_LO,
    DMA_CTRL_LENGTH_HI,
    DMA_CTRL_LENGTH_LO,
    DMA_CTRL_NEXT_ID_0,
    DMA_CTRL_NUM_REPETITIONS_HI,
    DMA_CTRL_NUM_REPETITIONS_LO,
    DMA_CTRL_SRC_ADDRESS_HI,
    DMA_CTRL_SRC_ADDRESS_LO,
    DMA_CTRL_SRC_STRIDE_HI,
    DMA_CTRL_SRC_STRIDE_LO,
    DMA_CTRL_STATUS_0,
    HANG_DET_ARMED,
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_DATA_ACCEL_TIMEOUT,
    HANG_DET_FIRE,
    HANG_DET_IRQ_TEST,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_THR_VALUE,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

INBOUND0_FILTER_CONFIG = smc_indexed_addr(
    "SMC_TOP_SMC_INBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0
)
INBOUND0_START = smc_indexed_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0)
INBOUND0_END = smc_indexed_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0)
OUTBOUND0_FILTER_CONFIG = smc_indexed_addr(
    "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", 0
)
OUTBOUND0_START = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_START_ADDR_BASE_ADDR", 0)
OUTBOUND0_END = smc_indexed_addr("SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR", 0)
PASS_ALL_CONFIG = 0x0100_3013

DMA_SRC_ADDR = 0x0200_0000
DMA_DST_ADDR = 0x0200_0008
DMA_LENGTH = 8

_THR = 0x10
_ACCEPT_BOUND = 4096
_IRQ_BOUND = _THR + 64
_DISABLE_BOUND = _THR + 64
_DONE_POLLS = 50


class smc_hang_detector_data_timeout_test_seq(SmcCsrSeq):
    """DATA_ACCEL outstanding stall → timeout irq; threshold 0 stays quiet."""

    def __init__(self, name: str = "smc_hang_detector_data_timeout_test_seq") -> None:
        super().__init__(name)
        self.fire_ok = False
        self.drop_ok = False
        self.disable_ok = False

    def _bit(self, sig, name: str) -> int:
        if not sig.value.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {sig.value}")
        return int(sig.value) & 1

    async def _await_irq(self, dut, pin: str, want: int, bound: int, label: str) -> None:
        last = -1
        for _ in range(bound):
            await RisingEdge(dut.clk_smc_i)
            last = self._bit(getattr(dut, pin), pin)
            if last == want:
                return
        raise AssertionError(f"{label}: {pin} stuck {last} want {want}")

    async def _await_output_accept(self, dut, bound: int, label: str) -> None:
        last_arv = last_arr = last_awv = last_awr = -1
        for _ in range(bound):
            await RisingEdge(dut.clk_smc_i)
            last_arv = self._bit(dut.tb_output_axi_arvalid, "tb_output_axi_arvalid")
            last_arr = self._bit(dut.tb_output_axi_arready, "tb_output_axi_arready")
            last_awv = self._bit(dut.tb_output_axi_awvalid, "tb_output_axi_awvalid")
            last_awr = self._bit(dut.tb_output_axi_awready, "tb_output_axi_awready")
            if (last_arv == 1 and last_arr == 1) or (last_awv == 1 and last_awr == 1):
                return
        raise AssertionError(
            f"{label}: SYS_OUT AR/AW handshake never completed "
            f"last ar={last_arv}/{last_arr} aw={last_awv}/{last_awr}"
        )

    async def _program_output_fabric_pass_all(self) -> None:
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0x0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8)
        await self.csr_write(
            "INBOUND0_FILTER_CONFIG_PASS_ALL",
            INBOUND0_FILTER_CONFIG,
            PASS_ALL_CONFIG,
            length=8,
        )
        await self.csr_write("OUTBOUND0_START_PASS_ALL", OUTBOUND0_START, 0x0, length=8)
        await self.csr_write(
            "OUTBOUND0_END_PASS_ALL", OUTBOUND0_END, 0x00FF_FFFF_FFFF_FFFF, length=8
        )
        await self.csr_write(
            "OUTBOUND0_FILTER_CONFIG_PASS_ALL",
            OUTBOUND0_FILTER_CONFIG,
            PASS_ALL_CONFIG,
            length=8,
        )

    async def _program_dma(self) -> int:
        await self.csr_write("DMA_CONFIG", DMA_CTRL_CONFIG, DMA_CONFIG_ENABLED_ND)
        await self.csr_write(
            "DMA_DST_ADDRESS_LO", DMA_CTRL_DST_ADDRESS_LO, DMA_DST_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write("DMA_DST_ADDRESS_HI", DMA_CTRL_DST_ADDRESS_HI, DMA_DST_ADDR >> 32)
        await self.csr_write(
            "DMA_SRC_ADDRESS_LO", DMA_CTRL_SRC_ADDRESS_LO, DMA_SRC_ADDR & 0xFFFF_FFFF
        )
        await self.csr_write("DMA_SRC_ADDRESS_HI", DMA_CTRL_SRC_ADDRESS_HI, DMA_SRC_ADDR >> 32)
        await self.csr_write("DMA_LENGTH_LO", DMA_CTRL_LENGTH_LO, DMA_LENGTH)
        await self.csr_write("DMA_LENGTH_HI", DMA_CTRL_LENGTH_HI, 0)
        await self.csr_write("DMA_DST_STRIDE_LO", DMA_CTRL_DST_STRIDE_LO, 0)
        await self.csr_write("DMA_DST_STRIDE_HI", DMA_CTRL_DST_STRIDE_HI, 0)
        await self.csr_write("DMA_SRC_STRIDE_LO", DMA_CTRL_SRC_STRIDE_LO, 0)
        await self.csr_write("DMA_SRC_STRIDE_HI", DMA_CTRL_SRC_STRIDE_HI, 0)
        await self.csr_write("DMA_NUM_REPETITIONS_LO", DMA_CTRL_NUM_REPETITIONS_LO, 1)
        await self.csr_write("DMA_NUM_REPETITIONS_HI", DMA_CTRL_NUM_REPETITIONS_HI, 0)
        start_id = await self.csr_read("DMA_NEXT_ID_0_START", DMA_CTRL_NEXT_ID_0)
        assert start_id != 0, "DMA command was not accepted"
        return start_id

    async def _wait_dma_done(self, baseline_done: int) -> int:
        for _ in range(_DONE_POLLS):
            done = await self.csr_read("DMA_DONE_0_POLL", DMA_CTRL_DONE_0)
            if done > baseline_done:
                return done
            await ClockCycles(cocotb.top.clk_smc_i, 20)
        status = await self.csr_read("DMA_STATUS_0_TIMEOUT", DMA_CTRL_STATUS_0)
        raise AssertionError(
            f"DMA did not complete: baseline_done={baseline_done} status=0x{status:x}"
        )

    async def _hold_dma_until(self, dut, name: str, after_accept) -> None:
        dut.tb_output_axi_resp_hold.value = 1
        try:
            await self._program_dma()
            await self._await_output_accept(dut, _ACCEPT_BOUND, f"{name}_ACCEPT")
            await after_accept()
        finally:
            dut.tb_output_axi_resp_hold.value = 0

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_output_axi_resp_hold"), "tb_output_axi_resp_hold missing"
        dut.tb_output_axi_resp_hold.value = 0
        dut.tb_sep_axi_r_hold.value = 0
        dut.tb_sys_axi_r_hold.value = 0

        await self._program_output_fabric_pass_all()
        # Positive control for the sep=0 / sys=0 legs below, which sample two
        # nets this sequence never drives. Pulsing the SEP detector's
        # observation path puts sep=1 in the run on the same net, so those
        # samples are a compare rather than a reading of a tied-off wire.
        await self.csr_write("HANG_SEP_CTRL_POS", HANG_DET_SEP_AXI_CTRL, HANG_DET_FIRE)
        await self._await_irq(dut, "tb_axi_hang_irq_sep", 1, _IRQ_BOUND, "SEP_IRQ_POS")
        cocotb.log.info(
            "CHK-HANG-DATA-TIMEOUT-SEP-POS: sep irq observation path drives 1 under "
            "irq_test, so the sep=0 samples below are a compare and not a dead net"
        )
        await self.csr_write("HANG_SEP_OFF", HANG_DET_SEP_AXI_CTRL, 0)
        await self._await_irq(dut, "tb_axi_hang_irq_sep", 0, _IRQ_BOUND, "SEP_IRQ_POS_CLR")

        await self.csr_write("HANG_SYS_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_DATA_THR", HANG_DET_DATA_ACCEL_TIMEOUT, _THR)
        thr = await self.csr_read("HANG_DATA_THR_RB", HANG_DET_DATA_ACCEL_TIMEOUT, expected=_THR)
        assert (thr & HANG_DET_THR_VALUE) == _THR, (
            f"DATA threshold readback 0x{thr:x} want 0x{_THR:x}"
        )
        await self.csr_write("HANG_DATA_ARM", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_ARMED)
        ctrl = await self.csr_read(
            "HANG_DATA_ARM_RB", HANG_DET_DATA_ACCEL_CTRL, expected=HANG_DET_ARMED
        )
        assert (ctrl & HANG_DET_IRQ_TEST) == 0, (
            f"irq_test set on armed CTRL 0x{ctrl:x}; would alias sanity"
        )
        assert self._bit(dut.tb_axi_hang_irq_sep, "tb_axi_hang_irq_sep") == 0
        assert self._bit(dut.tb_axi_hang_irq_sys, "tb_axi_hang_irq_sys") == 0
        assert self._bit(dut.tb_axi_hang_irq_data, "tb_axi_hang_irq_data") == 0
        cocotb.log.info(
            "CHK-HANG-DATA-TIMEOUT-ARM: thr=0x%x ctrl=0x%x irq_test=0 idle irqs=0",
            thr,
            ctrl,
        )

        baseline_done = await self.csr_read("DMA_DONE_0_BASELINE", DMA_CTRL_DONE_0)

        async def _expect_fire() -> None:
            cocotb.log.info("CHK-HANG-DATA-TIMEOUT-ACCEPT: SYS_OUT AR/AW accepted under resp_hold")
            await self._await_irq(dut, "tb_axi_hang_irq_data", 1, _IRQ_BOUND, "DATA_TIMEOUT_FIRE")
            assert self._bit(dut.tb_axi_hang_irq, "tb_axi_hang_irq") == 1
            assert self._bit(dut.tb_axi_hang_irq_sep, "tb_axi_hang_irq_sep") == 0
            assert self._bit(dut.tb_axi_hang_irq_sys, "tb_axi_hang_irq_sys") == 0
            self.fire_ok = True
            cocotb.log.info("CHK-HANG-DATA-TIMEOUT-FIRE: data=1 OR=1 sep=0 sys=0 after DMA stall")
            await check_hang_status(self.csr_read, "DATA_TIMEOUT_FIRE", {"DATA"})
            cocotb.log.info(
                "CHK-HANG-DATA-TIMEOUT-STATUS-FIRE: only HANG_DET_DATA_ACCEL_STATUS.irq read 1 "
                "during the stall"
            )

        await self._hold_dma_until(dut, "DATA_STALL_DMA", _expect_fire)
        await self._await_irq(dut, "tb_axi_hang_irq_data", 0, _IRQ_BOUND, "DATA_TIMEOUT_DROP")
        assert self._bit(dut.tb_axi_hang_irq, "tb_axi_hang_irq") == 0
        self.drop_ok = True
        cocotb.log.info("CHK-HANG-DATA-TIMEOUT-DROP: data=0 OR=0 after R/B completion")
        await check_hang_status(self.csr_read, "DATA_TIMEOUT_DROP", set())
        cocotb.log.info(
            "CHK-HANG-DATA-TIMEOUT-STATUS-DROP: every HANG_DET_*_STATUS.irq read 0 after R/B "
            "completion"
        )
        await self._wait_dma_done(baseline_done)

        await self.csr_write("HANG_DATA_THR0", HANG_DET_DATA_ACCEL_TIMEOUT, 0)
        await self.csr_read("HANG_DATA_THR0_RB", HANG_DET_DATA_ACCEL_TIMEOUT, expected=0)
        await self.csr_write("HANG_DATA_ARM0", HANG_DET_DATA_ACCEL_CTRL, HANG_DET_ARMED)

        async def _expect_quiet() -> None:
            last = 0
            for cycle in range(_DISABLE_BOUND):
                await RisingEdge(dut.clk_smc_i)
                last = self._bit(dut.tb_axi_hang_irq_data, "tb_axi_hang_irq_data")
                if last != 0:
                    raise AssertionError(
                        f"DATA irq rose at cycle {cycle} with threshold=0 (last={last})"
                    )
            self.disable_ok = True
            cocotb.log.info(
                "CHK-HANG-DATA-TIMEOUT-DISABLED: data stayed 0 for %d clocks thr=0",
                _DISABLE_BOUND,
            )

        await self._hold_dma_until(dut, "DATA_STALL_DMA_THR0", _expect_quiet)
        await self.csr_write("HANG_DATA_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        cocotb.log.info(
            "CHK-HANG-DATA-TIMEOUT-BASIC: fire=%s drop=%s disable=%s",
            self.fire_ok,
            self.drop_ok,
            self.disable_ok,
        )
