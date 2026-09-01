# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CSR persistence representative across public reset controls."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles
from env.smc_reset_item import SmcResetItem, SmcResetOp

from .smc_addr_map import smc_addr
from .smc_csr_seq_utils import SmcCsrSeq

SCRATCH_COLD_WARM_1 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_BASE_ADDR") + 0x4
CHIP_CONFIG_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR")
PERSIST_PATTERN = 0xCAFE_0020


class smc_multi_reset_csr_persistence_test_seq(SmcCsrSeq):
    """Check CSR access before/after cool reset and restore the scratch."""

    def __init__(self, name: str = "smc_multi_reset_csr_persistence_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None

    async def _reset_op(self, name: str, op: SmcResetOp) -> None:
        item = SmcResetItem(name)
        item.op = op
        await self.dispatch_reset(item)

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        await self.csr_read(
            "CHIP_CONFIG_VERSION_LO_BASELINE", CHIP_CONFIG_VERSION_LO, expected=0x0001_00A0
        )
        await self.csr_write_readback("SCRATCH_COLD_WARM_1", SCRATCH_COLD_WARM_1, PERSIST_PATTERN)

        await self._reset_op("cool_rst_lo", SmcResetOp.COOL_RST_LO)
        await ClockCycles(dut.clk_ref_i, 20)
        await self._reset_op("cool_rst_hi", SmcResetOp.COOL_RST_HI)
        await ClockCycles(dut.clk_ref_i, 800)

        await self.csr_read(
            "CHIP_CONFIG_VERSION_LO_RECOVERY", CHIP_CONFIG_VERSION_LO, expected=0x0001_00A0
        )
        await self.csr_read(
            "SCRATCH_COLD_WARM_1_POST_COOL", SCRATCH_COLD_WARM_1, expected=PERSIST_PATTERN
        )
        await self.csr_restore("SCRATCH_COLD_WARM_1", SCRATCH_COLD_WARM_1)
        assert self.accesses == 7, "multi-reset persistence access mismatch"
