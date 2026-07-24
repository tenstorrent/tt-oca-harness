# SPDX-License-Identifier: Apache-2.0
"""JTAG-adjacent reset recovery proxy sequence."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_base_test_seq import smc_base_test_seq

CHIP_CONFIG_VERSION_LO = 0xC000_2900
SCRATCH_COLD_2 = 0xC000_2808
SCRATCH_PATTERN = 0x1A7A_0002


class smc_jtag_reset_proxy_test_seq(smc_base_test_seq):
    """Use cool-reset recovery around safe CSRs until public JTAG VIP exists."""

    def __init__(self, name: str = "smc_jtag_reset_proxy_test_seq") -> None:
        super().__init__(name)
        self.dispatch_reset = None
        self.accesses = 0

    async def _read(self, name: str, addr: int, expected: int | None = None) -> int:
        item = SmcSysAxiItem(f"rd_{name}")
        item.op = SmcSysAxiOp.READ
        item.addr = addr
        item.length = 4
        item.expected = expected
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item.rdata

    async def _write(self, name: str, addr: int, data: int) -> None:
        item = SmcSysAxiItem(f"wr_{name}")
        item.op = SmcSysAxiOp.WRITE
        item.addr = addr
        item.length = 4
        item.wdata = data
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1

    async def _reset_op(self, name: str, op: SmcResetOp) -> None:
        item = SmcResetItem(name)
        item.op = op
        await self.dispatch_reset(item)

    async def body(self) -> None:
        await self._read("CHIP_CONFIG_VERSION_LO", CHIP_CONFIG_VERSION_LO,
                         expected=0x0001_00A0)
        await self._write("SCRATCH_COLD_2", SCRATCH_COLD_2, SCRATCH_PATTERN)
        await self._read("SCRATCH_COLD_2", SCRATCH_COLD_2, expected=SCRATCH_PATTERN)

        await self._reset_op("cool_rst_lo", SmcResetOp.COOL_RST_LO)
        await ClockCycles(cocotb.top.clk_ref_i, 20)
        await self._reset_op("cool_rst_hi", SmcResetOp.COOL_RST_HI)
        await ClockCycles(cocotb.top.clk_ref_i, 200)

        await self._read("CHIP_CONFIG_VERSION_LO_RECOVERY", CHIP_CONFIG_VERSION_LO,
                         expected=0x0001_00A0)
        await self._write("SCRATCH_COLD_2_RESTORE", SCRATCH_COLD_2, 0)
        await self._read("SCRATCH_COLD_2_RESTORE", SCRATCH_COLD_2, expected=0)
        assert self.accesses == 6, "JTAG reset proxy access mismatch"
