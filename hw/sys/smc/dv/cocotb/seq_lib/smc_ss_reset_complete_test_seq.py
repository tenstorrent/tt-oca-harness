# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ss_reset_complete_i to CSR bits 0/31; SW SS_WARM_RESET_N to ss_reset_ctrl_o[0]."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SS_COMPLETE = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_RESET_COMPLETE_BASE_ADDR")
SS_WARM = smc_addr("SMC_TOP_SMC_RESET_UNIT_SS_WARM_RESET_N_BASE_ADDR")
SCRATCH_COLD_WARM_0 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR")

_ALL_ONE = 0xFFFFFFFF
_DROP_0_31 = 0x7FFFFFFE
_CSR_BOUND = 64
_PIN_BOUND = 64


class smc_ss_reset_complete_test_seq(SmcCsrSeq):
    """Pin 1→drop bits 0/31→1 on CSR; SW warm bit 0 1→0→1 on SS0 pin."""

    def __init__(self, name: str = "smc_ss_reset_complete_test_seq") -> None:
        super().__init__(name)
        self.idle_ok = False
        self.drop_ok = False
        self.restore_ok = False
        self.warm_ok = False

    async def _await_csr(self, want: int, label: str) -> int:
        last = None
        for _ in range(_CSR_BOUND):
            last = await self.csr_read(f"{label}_COMPLETE", SS_COMPLETE)
            if last == want:
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: SS_RESET_COMPLETE last=0x{last:x} want=0x{want:x} after {_CSR_BOUND} polls"
        )

    def _warm_pin(self, dut) -> int:
        pin = dut.tb_ss0_warm_reset_n
        if not pin.value.is_resolvable:
            raise AssertionError(f"X/Z on tb_ss0_warm_reset_n: {pin.value}")
        return int(pin.value) & 1

    async def _await_warm_pin(self, dut, want: int, label: str) -> None:
        last = -1
        for _ in range(_PIN_BOUND):
            await RisingEdge(dut.clk_smc_i)
            last = self._warm_pin(dut)
            if last == want:
                return
        raise AssertionError(f"{label}: ss0 warm_reset_n stuck {last} want {want}")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_ss_reset_complete"), "tb_ss_reset_complete missing"
        assert hasattr(dut, "tb_ss0_warm_reset_n"), "tb_ss0_warm_reset_n missing"

        dut.tb_ss_reset_complete.value = _ALL_ONE
        got0 = await self._await_csr(_ALL_ONE, "IDLE")
        self.idle_ok = True
        cocotb.log.info("CHK-SS-COMPLETE-IDLE: CSR=0x%x pin=all-1", got0)

        dut.tb_ss_reset_complete.value = _DROP_0_31
        got1 = await self._await_csr(_DROP_0_31, "DROP")
        self.drop_ok = True
        cocotb.log.info(
            "CHK-SS-COMPLETE-DROP: CSR=0x%x pin=0x%x bits 0 and 31 low",
            got1,
            _DROP_0_31,
        )

        dut.tb_ss_reset_complete.value = _ALL_ONE
        got2 = await self._await_csr(_ALL_ONE, "RESTORE")
        self.restore_ok = True
        cocotb.log.info("CHK-SS-COMPLETE-RESTORE: CSR=0x%x pin=all-1", got2)

        warm0 = await self.csr_read("SS_WARM_IDLE", SS_WARM)
        assert warm0 == _ALL_ONE, f"SS_WARM_RESET_N idle 0x{warm0:x} want all-1"
        await self._await_warm_pin(dut, 1, "WARM_IDLE")
        await self.csr_write("SS_WARM_SS0_LO", SS_WARM, _ALL_ONE & ~0x1)
        await self._await_warm_pin(dut, 0, "WARM_ASSERT")
        warm1 = await self.csr_read("SS_WARM_ASSERTED", SS_WARM)
        assert (warm1 & 0x1) == 0, f"SS_WARM bit0 stuck 1: 0x{warm1:x}"
        await self.csr_write("SS_WARM_SS0_HI", SS_WARM, _ALL_ONE)
        await self._await_warm_pin(dut, 1, "WARM_RELEASE")
        warm2 = await self.csr_read("SS_WARM_RELEASED", SS_WARM)
        assert (warm2 & 0x1) == 1, f"SS_WARM bit0 stuck 0: 0x{warm2:x}"
        self.warm_ok = True
        cocotb.log.info(
            "CHK-SS-WARM-SS0: pin 1→0→1 CSR=0x%x→0x%x→0x%x",
            warm0,
            warm1,
            warm2,
        )
        got = await self.csr_read("SCRATCH_COLD_WARM_0", SCRATCH_COLD_WARM_0, expected=0)
        cocotb.log.info("CHK-SS-COMPLETE-WARM-SCRATCH: SCRATCH_COLD_WARM_0=0x%x", got)
        cocotb.log.info(
            "CHK-SS-COMPLETE-BASIC: idle=%s drop=%s restore=%s warm=%s",
            self.idle_ok,
            self.drop_ok,
            self.restore_ok,
            self.warm_ok,
        )
