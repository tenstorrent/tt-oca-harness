# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ext_interrupts_i[0] after prim_sync3. Does not claim PLIC or bits 1..255."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")

_SYNC_BOUND = 64


class smc_ext_interrupts_pin_test_seq(SmcCsrSeq):
    """Pulse ext_interrupts_i[0]; synced observe must follow 0→1→0."""

    def __init__(self, name: str = "smc_ext_interrupts_pin_test_seq") -> None:
        super().__init__(name)
        self.idle_ok = False
        self.rise_ok = False
        self.fall_ok = False

    def _sync(self, dut) -> int:
        pin = dut.tb_ext_interrupt_0_sync
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on tb_ext_interrupt_0_sync: {pin.value}")
        return int(pin.value) & 1

    async def _await_sync(self, dut, want: int, label: str) -> None:
        last = -1
        for _ in range(_SYNC_BOUND):
            await RisingEdge(dut.clk_smc_i)
            last = self._sync(dut)
            if last == want:
                return
        raise AssertionError(f"{label}: sync stuck {last} want {want}")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_ext_interrupt_0_i"), "tb_ext_interrupt_0_i missing"
        assert hasattr(dut, "tb_ext_interrupt_0_sync"), "tb_ext_interrupt_0_sync missing"
        dut.tb_ext_interrupt_0_i.value = 0
        await self._await_sync(dut, 0, "IDLE")
        self.idle_ok = True
        cocotb.log.info("CHK-EXT-IRQ0-IDLE: sync=0 pin=0")

        dut.tb_ext_interrupt_0_i.value = 1
        await self._await_sync(dut, 1, "RISE")
        self.rise_ok = True
        cocotb.log.info("CHK-EXT-IRQ0-RISE: sync=1 pin=1")

        dut.tb_ext_interrupt_0_i.value = 0
        await self._await_sync(dut, 0, "FALL")
        self.fall_ok = True
        cocotb.log.info("CHK-EXT-IRQ0-FALL: sync=0 pin=0")
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info("CHK-EXT-IRQ0-WARM: SCRATCH_COLD_WARM_0=0x%x", got)
        cocotb.log.info(
            "CHK-EXT-IRQ0-BASIC: idle=%s rise=%s fall=%s",
            self.idle_ok,
            self.rise_ok,
            self.fall_ok,
        )
