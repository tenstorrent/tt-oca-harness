# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Temp interrupt via ext_interrupts_i[1] to ext_interrupts_smc_clk after CDC. Analog PVT not claimed."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")

# prim_sync3 into clk_smc. Fail-closed poll ceiling.
_IRQ_BOUND = 64


class smc_temp_interrupt_test_seq(SmcCsrSeq):
    """Pulse temp bit on ext_interrupts_i; synced observe must follow 0→1→0."""

    def __init__(self, name: str = "smc_temp_interrupt_test_seq") -> None:
        super().__init__(name)
        self.idle_ok = False
        self.rise_ok = False
        self.fall_ok = False

    def _irq(self, dut) -> int:
        pin = dut.tb_temp_interrupt_irq
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on tb_temp_interrupt_irq: {pin.value}")
        return int(pin.value) & 1

    async def _await_irq(self, dut, want: int, label: str) -> None:
        last = -1
        for _ in range(_IRQ_BOUND):
            await RisingEdge(dut.clk_smc_i)
            last = self._irq(dut)
            if last == want:
                return
        raise AssertionError(f"{label}: irq stuck {last} want {want}")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_temp_interrupt_i"), "tb_temp_interrupt_i missing"
        assert hasattr(dut, "tb_temp_interrupt_irq"), "tb_temp_interrupt_irq missing"
        dut.tb_temp_interrupt_i.value = 0
        await self._await_irq(dut, 0, "IDLE")
        self.idle_ok = True
        cocotb.log.info("CHK-TEMP-IRQ-IDLE: irq=0 pin=0")

        dut.tb_temp_interrupt_i.value = 1
        await self._await_irq(dut, 1, "RISE")
        self.rise_ok = True
        cocotb.log.info("CHK-TEMP-IRQ-RISE: irq=1 pin=1")

        dut.tb_temp_interrupt_i.value = 0
        await self._await_irq(dut, 0, "FALL")
        self.fall_ok = True
        cocotb.log.info("CHK-TEMP-IRQ-FALL: irq=0 pin=0")
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info("CHK-TEMP-IRQ-WARM: SCRATCH_COLD_WARM_0=0x%x", got)
        cocotb.log.info(
            "CHK-TEMP-IRQ-BASIC: idle=%s rise=%s fall=%s",
            self.idle_ok,
            self.rise_ok,
            self.fall_ok,
        )
