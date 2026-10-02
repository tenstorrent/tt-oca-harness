# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Writes to ISOLATE_REQ_SMC_REG that must leave the FLR-latched request set.

`reset_unit.rdl` (lines 130-135) makes `isolate_req_smc_reg` a single `sw = rw`
field at bit 0: hardware sets it when `cfg_flr_pf_active` rises and software
de-asserts it. A write that does not select the field's byte lane cannot
change it, and a write of 1 to it keeps it at 1.

`smc_cool_reset_wrap.sv` (lines 272-276) clears the request on any write whose
byte enables are non-zero anywhere in the register, whatever the data. So a
one-byte write of 0 at byte 1 clears it, and so does a write of 1 at byte 0.
This leaf holds the RTL to the RDL contract and is expected to fail until the
clear is qualified by bit 0's enable and a written 0.

The request is raised through FLR with the FLR counters at their reset value
of 0, which latches it without starting the cool-reset sequence.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

from .smc_addr_map import reset_unit_u32, smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
SMC_BIT = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")
_BOUND = 64


class smc_isolate_req_smc_lane_test_seq(SmcCsrSeq):
    """Raise the request through FLR, then write lane 1 with 0 and lane 0 with 1."""

    async def _await_bit(self, want: int, label: str) -> int:
        last = 0
        for _ in range(_BOUND):
            last = await self.csr_read(label, SMC_REG)
            if (last & SMC_BIT) == want:
                return last
            await RisingEdge(cocotb.top.clk_smc_i)
        raise AssertionError(f"{label}: ISOLATE_REQ_SMC_REG=0x{last:x}, bit 0 never read {want}")

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()
        dut.tb_cfg_flr_pf_active.value = 0
        await self.csr_read("SMC_REG_IDLE", SMC_REG, expected=0)
        dut.tb_cfg_flr_pf_active.value = 1
        await self._await_bit(SMC_BIT, "SMC_REG_FLR")
        dut.tb_cfg_flr_pf_active.value = 0

        await self.csr_write("SMC_REG_LANE1_ZERO", SMC_REG + 1, 0, length=1)
        lane1 = await self.csr_read("SMC_REG_LANE1_RB", SMC_REG)
        assert lane1 & SMC_BIT, (
            f"ISOLATE_REQ_SMC_REG reads 0x{lane1:x} after a one-byte write of 0 at byte 1: "
            f"the write cleared the FLR-latched request from a byte lane the field does not "
            f"occupy"
        )
        await self.csr_write("SMC_REG_LANE0_ONE", SMC_REG, SMC_BIT, length=1)
        lane0 = await self.csr_read("SMC_REG_LANE0_RB", SMC_REG)
        assert lane0 & SMC_BIT, (
            f"ISOLATE_REQ_SMC_REG reads 0x{lane0:x} after writing 1 to bit 0: a sw=rw field "
            f"written with 1 has to read 1"
        )
        cocotb.log.info(
            "CHK-ISOLATE-REQ-SMC-LANE: the FLR-latched request stayed set across a one-byte "
            "write of 0 at byte 1 (0x%x) and a write of 1 to bit 0 (0x%x)",
            lane1,
            lane0,
        )
        await self.csr_write("SMC_REG_CLEAR", SMC_REG, 0)
        await self._await_bit(0, "SMC_REG_CLEARED")
