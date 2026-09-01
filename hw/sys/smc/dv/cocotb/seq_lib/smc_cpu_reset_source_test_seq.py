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
        # Measured DUT words, published for the testcase-level gate. `None`
        # means "never sampled" and fails that gate; nothing here is ever
        # pre-seeded with the value it is later compared against.
        self.ctrl_idle = None
        self.ctrl_asserted = None
        self.ctrl_released = None
        self.tmo_idle = None
        self.tmo_asserted = None
        self.tmo_hold = None
        self.tmo_released = None

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
        self.ctrl_idle = ctrl0
        self.tmo_idle = tmo0
        cocotb.log.info(
            "CHK-CPU-RST-IDLE: RESET_CTRL=0x%x RESET_TIMEOUT=0x%x applied=0",
            ctrl0,
            tmo0,
        )

        await self.csr_write("RESET_CTRL_CORE0_LO", RESET_CTRL, ctrl0 & ~CORE0_N)
        tmo1 = await self._await_applied(1, "ASSERT")
        ctrl1 = await self.csr_read("RESET_CTRL_ASSERTED", RESET_CTRL)
        assert (ctrl1 & CORE0_N) == 0, f"core0_reset_n did not stick: RESET_CTRL=0x{ctrl1:x}"
        self.ctrl_asserted = ctrl1
        self.tmo_asserted = tmo1
        cocotb.log.info(
            "CHK-CPU-RST-SW: core0_reset_n=0 RESET_TIMEOUT=0x%x applied=1",
            tmo1,
        )

        # Hold check ([EXACT-EXPECTATION]): re-sample RESET_TIMEOUT immediately
        # before the release write, so the subsequent applied->0 is attributable
        # to the release and not to a self-clearing pulse that had already
        # dropped during the RESET_CTRL read above.
        hold = await self.csr_read("RESET_TIMEOUT_HOLD", RESET_TIMEOUT, length=8)
        assert (hold & APPLIED) != 0, (
            f"RESET_TIMEOUT.reset_applied dropped to 0 before the release write "
            f"was issued (RESET_TIMEOUT=0x{hold:x}): the later applied=0 sample "
            f"cannot be attributed to releasing core0_reset_n"
        )
        self.tmo_hold = hold

        await self.csr_write("RESET_CTRL_CORE0_HI", RESET_CTRL, ctrl1 | CORE0_N)
        tmo2 = await self._await_applied(0, "RELEASE")
        ctrl2 = await self.csr_read("RESET_CTRL_RELEASED", RESET_CTRL)
        assert (ctrl2 & CORE0_N) != 0, f"core0_reset_n did not release: RESET_CTRL=0x{ctrl2:x}"
        self.ctrl_released = ctrl2
        self.tmo_released = tmo2
        cocotb.log.info(
            "CHK-CPU-RST-REL: core0_reset_n=1 RESET_TIMEOUT_HOLD=0x%x "
            "(applied still 1 at the release write) RESET_TIMEOUT=0x%x applied=0",
            hold,
            tmo2,
        )

        # Loop integrity + scoreboard cross-check: every access above must have
        # reached the checker ([NO-ZERO-ACTIVITY-PASS]). The poll helper makes
        # the total variable, so the floor is asserted directly rather than
        # through `assert_all_reachable`'s exact-count leg.
        sb = self.env.scoreboard
        assert sb.sys_axi_checks_seen >= self.accesses, (
            f"CPU reset source: the scoreboard checked only "
            f"{sb.sys_axi_checks_seen} SYS AXI item(s) but this sequence issued "
            f"{self.accesses} access(es) -- the traffic never reached the "
            f"scoreboard, so none of it is checked evidence"
        )
        cocotb.log.info(
            "CHK-CPU-RST-BASIC: RESET_CTRL idle=0x%x asserted=0x%x released=0x%x "
            "| RESET_TIMEOUT idle=0x%x asserted=0x%x hold=0x%x released=0x%x "
            "| core0_reset_n mask=0x%x applied mask=0x%x "
            "| %d access(es), scoreboard checked %d",
            self.ctrl_idle,
            self.ctrl_asserted,
            self.ctrl_released,
            self.tmo_idle,
            self.tmo_asserted,
            self.tmo_hold,
            self.tmo_released,
            CORE0_N,
            APPLIED,
            self.accesses,
            sb.sys_axi_checks_seen,
        )
