# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SW RESET_CTRL.core0. No Force. Does not claim drain withhold or isolate_req_o."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import cpu_ctrl_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
CORE0_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__CORE0_RESET_N_N0_SCAN_bm")
APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
_CSR_BOUND = 64


class smc_cpu_reset_source_test_seq(SmcCsrSeq):
    """SW core0 level reset sets/clears RESET_TIMEOUT.reset_applied."""

    def __init__(self, name: str = "smc_cpu_reset_source_test_seq") -> None:
        super().__init__(name)
        self.idle_ok = False
        self.assert_ok = False
        self.release_ok = False

    async def _await_applied(self, want: int, label: str) -> int:
        last = None
        for _ in range(_CSR_BOUND):
            last = await self.csr_read(f"{label}_TMO", RESET_TIMEOUT, length=8)
            got = 1 if (last & APPLIED) else 0
            if got == want:
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(
            f"{label}: RESET_TIMEOUT last=0x{last:x} applied want={want} after {_CSR_BOUND} polls"
        )

    async def body(self) -> None:
        await self.wait_fuse_sense_done()

        ctrl0 = await self.csr_read("RESET_CTRL_IDLE", RESET_CTRL)
        assert (ctrl0 & CORE0_N) != 0, f"core0_reset_n already 0: RESET_CTRL=0x{ctrl0:x}"
        tmo0 = await self._await_applied(0, "IDLE")
        self.idle_ok = True
        cocotb.log.info(
            "CHK-CPU-RST-IDLE: RESET_CTRL=0x%x RESET_TIMEOUT=0x%x applied=0",
            ctrl0,
            tmo0,
        )

        await self.csr_write("RESET_CTRL_CORE0_LO", RESET_CTRL, ctrl0 & ~CORE0_N)
        tmo1 = await self._await_applied(1, "ASSERT")
        ctrl1 = await self.csr_read("RESET_CTRL_ASSERTED", RESET_CTRL)
        assert (ctrl1 & CORE0_N) == 0, f"core0_reset_n did not stick: RESET_CTRL=0x{ctrl1:x}"
        self.assert_ok = True
        cocotb.log.info(
            "CHK-CPU-RST-SW: core0_reset_n=0 RESET_TIMEOUT=0x%x applied=1",
            tmo1,
        )

        await self.csr_write("RESET_CTRL_CORE0_HI", RESET_CTRL, ctrl1 | CORE0_N)
        tmo2 = await self._await_applied(0, "RELEASE")
        ctrl2 = await self.csr_read("RESET_CTRL_RELEASED", RESET_CTRL)
        assert (ctrl2 & CORE0_N) != 0, f"core0_reset_n did not release: RESET_CTRL=0x{ctrl2:x}"
        self.release_ok = True
        cocotb.log.info(
            "CHK-CPU-RST-REL: core0_reset_n=1 RESET_TIMEOUT=0x%x applied=0",
            tmo2,
        )
        cocotb.log.info(
            "CHK-CPU-RST-BASIC: idle=%s assert=%s release=%s",
            self.idle_ok,
            self.assert_ok,
            self.release_ok,
        )
