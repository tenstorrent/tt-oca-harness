# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP hang-detector stall via tb_sep_axi_r_hold. Not irq_test. SYS/DATA stay disarmed."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import (
    HANG_DET_ARMED,
    HANG_DET_DATA_ACCEL_CTRL,
    HANG_DET_IRQ_TEST,
    HANG_DET_SEP_AXI_CTRL,
    HANG_DET_SEP_AXI_TIMEOUT,
    HANG_DET_SYS_AXI_CTRL,
    HANG_DET_THR_VALUE,
    smc_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")

# Small non-zero threshold so irq fires well before the VIP AXI timeout.
_THR = 0x10
_AR_BOUND = 256
_IRQ_BOUND = _THR + 64
_DISABLE_BOUND = _THR + 64


class smc_hang_detector_timeout_test_seq(SmcCsrSeq):
    """SEP outstanding stall → timeout irq; threshold 0 stays quiet."""

    def __init__(self, name: str = "smc_hang_detector_timeout_test_seq") -> None:
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

    async def _await_ar_accept(self, dut, bound: int, label: str) -> None:
        last_v = last_r = -1
        for _ in range(bound):
            await RisingEdge(dut.clk_smc_i)
            last_v = self._bit(dut.s_axi_arvalid, "s_axi_arvalid")
            last_r = self._bit(dut.s_axi_arready, "s_axi_arready")
            if last_v == 1 and last_r == 1:
                return
        raise AssertionError(
            f"{label}: AR handshake never completed last valid={last_v} ready={last_r}"
        )

    async def _stalled_read(self, name: str) -> int:
        return await self.csr_read(name, SCRATCH_COLD_WARM_0)

    async def _hold_read_until(self, dut, name: str, after_ar) -> int:
        """Start a SEP_IN read under r_hold; always drop the hold before return."""
        dut.tb_sep_axi_r_hold.value = 1
        task = cocotb.start_soon(self._stalled_read(name))
        try:
            await self._await_ar_accept(dut, _AR_BOUND, f"{name}_AR")
            await after_ar()
        finally:
            dut.tb_sep_axi_r_hold.value = 0
        return await task

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_sep_axi_r_hold"), "tb_sep_axi_r_hold missing"
        dut.tb_sep_axi_r_hold.value = 0

        await self.csr_write("HANG_SYS_OFF", HANG_DET_SYS_AXI_CTRL, 0)
        await self.csr_write("HANG_DATA_OFF", HANG_DET_DATA_ACCEL_CTRL, 0)
        await self.csr_write("HANG_SEP_THR", HANG_DET_SEP_AXI_TIMEOUT, _THR)
        thr = await self.csr_read("HANG_SEP_THR_RB", HANG_DET_SEP_AXI_TIMEOUT, expected=_THR)
        assert (thr & HANG_DET_THR_VALUE) == _THR, (
            f"SEP threshold readback 0x{thr:x} want 0x{_THR:x}"
        )
        await self.csr_write("HANG_SEP_ARM", HANG_DET_SEP_AXI_CTRL, HANG_DET_ARMED)
        ctrl = await self.csr_read(
            "HANG_SEP_ARM_RB", HANG_DET_SEP_AXI_CTRL, expected=HANG_DET_ARMED
        )
        assert (ctrl & HANG_DET_IRQ_TEST) == 0, (
            f"irq_test set on armed CTRL 0x{ctrl:x}; would alias sanity"
        )
        assert self._bit(dut.tb_axi_hang_irq_sep, "tb_axi_hang_irq_sep") == 0
        assert self._bit(dut.tb_axi_hang_irq_sys, "tb_axi_hang_irq_sys") == 0
        assert self._bit(dut.tb_axi_hang_irq_data, "tb_axi_hang_irq_data") == 0
        cocotb.log.info(
            "CHK-HANG-TIMEOUT-ARM: thr=0x%x ctrl=0x%x irq_test=0 idle irqs=0",
            thr,
            ctrl,
        )

        async def _expect_fire() -> None:
            cocotb.log.info("CHK-HANG-TIMEOUT-AR: SEP_IN AR accepted under r_hold")
            await self._await_irq(dut, "tb_axi_hang_irq_sep", 1, _IRQ_BOUND, "SEP_TIMEOUT_FIRE")
            assert self._bit(dut.tb_axi_hang_irq, "tb_axi_hang_irq") == 1
            assert self._bit(dut.tb_axi_hang_irq_sys, "tb_axi_hang_irq_sys") == 0
            assert self._bit(dut.tb_axi_hang_irq_data, "tb_axi_hang_irq_data") == 0
            self.fire_ok = True
            cocotb.log.info(
                "CHK-HANG-TIMEOUT-FIRE: sep=1 OR=1 sys=0 data=0 after outstanding stall"
            )

        await self._hold_read_until(dut, "STALL_RD", _expect_fire)
        await self._await_irq(dut, "tb_axi_hang_irq_sep", 0, _IRQ_BOUND, "SEP_TIMEOUT_DROP")
        assert self._bit(dut.tb_axi_hang_irq, "tb_axi_hang_irq") == 0
        self.drop_ok = True
        cocotb.log.info("CHK-HANG-TIMEOUT-DROP: sep=0 OR=0 after R completion")

        await self.csr_write("HANG_SEP_THR0", HANG_DET_SEP_AXI_TIMEOUT, 0)
        await self.csr_read("HANG_SEP_THR0_RB", HANG_DET_SEP_AXI_TIMEOUT, expected=0)
        await self.csr_write("HANG_SEP_ARM0", HANG_DET_SEP_AXI_CTRL, HANG_DET_ARMED)

        async def _expect_quiet() -> None:
            last = 0
            for cycle in range(_DISABLE_BOUND):
                await RisingEdge(dut.clk_smc_i)
                last = self._bit(dut.tb_axi_hang_irq_sep, "tb_axi_hang_irq_sep")
                if last != 0:
                    raise AssertionError(
                        f"SEP irq rose at cycle {cycle} with threshold=0 (last={last})"
                    )
            self.disable_ok = True
            cocotb.log.info(
                "CHK-HANG-TIMEOUT-DISABLED: sep stayed 0 for %d clocks thr=0",
                _DISABLE_BOUND,
            )

        await self._hold_read_until(dut, "STALL_RD_THR0", _expect_quiet)
        await self.csr_write("HANG_SEP_OFF", HANG_DET_SEP_AXI_CTRL, 0)
        cocotb.log.info(
            "CHK-HANG-TIMEOUT-BASIC: fire=%s drop=%s disable=%s",
            self.fire_ok,
            self.drop_ok,
            self.disable_ok,
        )
