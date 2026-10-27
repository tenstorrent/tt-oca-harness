# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ISOLATE_REQ_SMC_REG clears only on a write of 1 to bit 0 on its own byte lane.

`reset_unit.rdl` makes `isolate_req_smc_reg` a single `onwrite = woclr`
field at bit 0: hardware sets it when `cfg_flr_pf_active` rises, and software
clears it by writing 1 to bit 0 with byte 0's strobe set. A write of 0, or a
write whose byte strobes do not select byte 0, leaves it unchanged.
`smc_cool_reset_wrap.sv` qualifies the clear with the field's own write enable
and its written data.

This leaf raises the request through FLR with the FLR counters at their reset
value of 0, which latches it without starting the cool-reset sequence, then
drives the three writes that must leave it set and the one write that clears it.
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
    """Raise the request through FLR; write lane 1 with 0 and 0xFF and lane 0 with 0, then 1."""

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
        lane1_zero = await self.csr_read("SMC_REG_LANE1_ZERO_RB", SMC_REG)
        assert lane1_zero & SMC_BIT, (
            f"ISOLATE_REQ_SMC_REG reads 0x{lane1_zero:x} after a one-byte write of 0 at byte 1: "
            f"a write that does not strobe byte 0 must leave the FLR-latched request set"
        )
        await self.csr_write("SMC_REG_LANE1_ONES", SMC_REG + 1, 0xFF, length=1)
        lane1_ones = await self.csr_read("SMC_REG_LANE1_ONES_RB", SMC_REG)
        assert lane1_ones & SMC_BIT, (
            f"ISOLATE_REQ_SMC_REG reads 0x{lane1_ones:x} after a one-byte write of 0xFF at "
            f"byte 1: a write that does not strobe byte 0 must leave the FLR-latched request set"
        )
        await self.csr_write("SMC_REG_WORD_ZERO", SMC_REG, 0)
        word_zero = await self.csr_read("SMC_REG_WORD_ZERO_RB", SMC_REG)
        assert word_zero & SMC_BIT, (
            f"ISOLATE_REQ_SMC_REG reads 0x{word_zero:x} after a write of 0: a write-1-to-clear "
            f"field must ignore a written 0"
        )
        await self.csr_write("SMC_REG_LANE0_ONE", SMC_REG, SMC_BIT, length=1)
        lane0_one = await self._await_bit(0, "SMC_REG_LANE0_ONE_RB")
        cocotb.log.info(
            "CHK-ISOLATE-REQ-SMC-LANE: the FLR-latched request stayed set across a one-byte "
            "write of 0 at byte 1 (0x%x), a one-byte write of 0xFF at byte 1 (0x%x) and a word "
            "write of 0 (0x%x), and cleared on a one-byte write of 1 to bit 0 (0x%x)",
            lane1_zero,
            lane1_ones,
            word_zero,
            lane0_one,
        )
