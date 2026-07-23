# SPDX-License-Identifier: Apache-2.0
"""Sequence for smc_flr_sanity_test (Batch D).

The public OSS TB does not yet expose a dedicated PCIe FLR source. This sequence
uses the available cool-reset control as the current FLR-like recovery stimulus:
prove CSR access before the pulse, assert/release cool reset, verify reset
stability, and prove the SEP_IN AXI CSR path recovers afterwards.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from env.smc_reset_item import SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_base_test_seq import smc_base_test_seq

CHIP_CONFIG_VERSION_LO = 0xC000_2900
CHIP_CONFIG_VERSION_LO_VALUE = 0x0001_00A0
SCRATCH_COLD_WARM_0 = 0xC000_2880
SCRATCH_PATTERN = 0xF1A0_0001


class smc_flr_sanity_test_seq(smc_base_test_seq):
    def __init__(self, name: str = "smc_flr_sanity_test_seq") -> None:
        super().__init__(name)
        self.samples: list[SmcResetItem] = []
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

    async def _sample_reset(self, name: str) -> SmcResetItem:
        item = SmcResetItem(name)
        item.op = SmcResetOp.SAMPLE
        await self.dispatch_reset(item)
        self.samples.append(item)
        return item

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done()

        await self._read("CHIP_CONFIG_VERSION_LO_BASELINE", CHIP_CONFIG_VERSION_LO,
                         expected=CHIP_CONFIG_VERSION_LO_VALUE)
        await self._write("SCRATCH_COLD_WARM_0_PRE", SCRATCH_COLD_WARM_0,
                          SCRATCH_PATTERN)
        await self._read("SCRATCH_COLD_WARM_0_PRE", SCRATCH_COLD_WARM_0,
                         expected=SCRATCH_PATTERN)

        await self._reset_op("cool_rst_lo", SmcResetOp.COOL_RST_LO)
        await ClockCycles(dut.clk_ref_i, 20)
        await self._reset_op("cool_rst_hi", SmcResetOp.COOL_RST_HI)
        await ClockCycles(dut.clk_ref_i, 800)
        await self._sample_reset("post_cool_reset")

        await self._read("CHIP_CONFIG_VERSION_LO_RECOVERY", CHIP_CONFIG_VERSION_LO,
                         expected=CHIP_CONFIG_VERSION_LO_VALUE)
        await self._write("SCRATCH_COLD_WARM_0_RESTORE", SCRATCH_COLD_WARM_0, 0)
        await self._read("SCRATCH_COLD_WARM_0_RESTORE", SCRATCH_COLD_WARM_0,
                         expected=0)

        for s in self.samples:
            assert s.resolvable, f"unresolved FLR sample: {s.get_name()}"
            assert s.powergood_stable == 1, \
                f"powergood unstable at {s.get_name()}"
            assert s.rst_primary_ref_clk_n == 1, \
                f"primary ref reset asserted at {s.get_name()}"
            assert s.rst_primary_smc_clk_n == 1, \
                f"primary smc reset asserted at {s.get_name()}"
        assert self.accesses == 6, "expected FLR sanity CSR access sequence"
