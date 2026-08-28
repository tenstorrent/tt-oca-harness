# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""mem_repair_abort_i / mbist_abort_i to STATUS_SMU sticky bits. Not DEBUG_CTRL reset reads."""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import (
    DFX_MBIST_ABORT,
    DFX_MEM_REPAIR_ABORT,
    DFX_STATUS_IDLE,
    DFX_STATUS_SMU,
)
from .smc_csr_seq_utils import SmcCsrSeq

_CSR_BOUND = 64


class smc_dfx_status_abort_test_seq(SmcCsrSeq):
    """STATUS_SMU idle, then mem-repair abort, then MBIST abort."""

    def __init__(self, name: str = "smc_dfx_status_abort_test_seq") -> None:
        super().__init__(name)
        self.idle_ok = False
        self.repair_ok = False
        self.mbist_ok = False

    def _bit(self, sig, name: str) -> int:
        if not sig.value.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {sig.value}")
        return int(sig.value) & 1

    async def _await_status(self, want: int, bound: int, label: str) -> int:
        last = 0
        for _ in range(bound):
            last = await self.csr_read(label, DFX_STATUS_SMU)
            if last == want:
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: STATUS_SMU=0x{last:x} want 0x{want:x}")

    async def body(self) -> None:
        dut = cocotb.top
        #: STATUS_SMU words observed at each stage, in order.
        self.status_progression: list[int] = []
        await self.wait_fuse_sense_done()
        assert hasattr(dut, "tb_mem_repair_abort"), "tb_mem_repair_abort missing"
        assert hasattr(dut, "tb_mbist_abort"), "tb_mbist_abort missing"
        dut.tb_mem_repair_abort.value = 0
        dut.tb_mbist_abort.value = 0

        idle = await self._await_status(DFX_STATUS_IDLE, _CSR_BOUND, "STATUS_IDLE")
        # TB DEPOSIT CONFIRMATION, not DUT evidence. These two reads read back
        # the value this sequence itself drove onto `tb_mem_repair_abort` /
        # `tb_mbist_abort` four lines above. The pins are real DUT inputs
        # (tb_top.sv:1316,1319 -> .mem_repair_abort_i / .mbist_abort_i), so the
        # deposit matters, but a readback of one's own drive cannot fail on
        # anything the DUT did ([NO-ALWAYS-PASS-CHECKER]). Kept because a
        # silently-refused deposit would make every leg below meaningless, and
        # labelled so the kept log does not read as an observation.
        assert self._bit(dut.tb_mem_repair_abort, "tb_mem_repair_abort") == 0
        assert self._bit(dut.tb_mbist_abort, "tb_mbist_abort") == 0
        self.idle_ok = True
        self.status_progression.append(idle)
        cocotb.log.info("CHK-DFX-ABORT-IDLE: STATUS_SMU=0x%x abort pins=0", idle)

        dut.tb_mem_repair_abort.value = 1
        repair = await self._await_status(
            DFX_STATUS_IDLE | DFX_MEM_REPAIR_ABORT, _CSR_BOUND, "STATUS_REPAIR_ABORT"
        )
        assert (repair & DFX_MBIST_ABORT) == 0, (
            f"mbist_abort set by mem_repair pulse: 0x{repair:x}"
        )
        dut.tb_mem_repair_abort.value = 0
        sticky = await self.csr_read(
            "STATUS_REPAIR_STICKY",
            DFX_STATUS_SMU,
            expected=DFX_STATUS_IDLE | DFX_MEM_REPAIR_ABORT,
        )
        self.repair_ok = True
        self.status_progression.append(sticky)
        cocotb.log.info(
            "CHK-DFX-ABORT-REPAIR: STATUS_SMU=0x%x after pin 1→0 (sticky)", sticky
        )

        dut.tb_mbist_abort.value = 1
        both = await self._await_status(
            DFX_STATUS_IDLE | DFX_MEM_REPAIR_ABORT | DFX_MBIST_ABORT,
            _CSR_BOUND,
            "STATUS_MBIST_ABORT",
        )
        dut.tb_mbist_abort.value = 0
        both_sticky = await self.csr_read(
            "STATUS_MBIST_STICKY",
            DFX_STATUS_SMU,
            expected=DFX_STATUS_IDLE | DFX_MEM_REPAIR_ABORT | DFX_MBIST_ABORT,
        )
        self.mbist_ok = True
        self.status_progression.append(both_sticky)
        cocotb.log.info(
            "CHK-DFX-ABORT-MBIST: STATUS_SMU=0x%x both abort sticky", both_sticky
        )
        cocotb.log.info(
            "CHK-DFX-ABORT-BASIC: idle=%s repair=%s mbist=%s (live=0x%x)",
            self.idle_ok,
            self.repair_ok,
            self.mbist_ok,
            both,
        )
