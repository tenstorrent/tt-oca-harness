# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_ijtag_basic_test (Batch C).

The public OSS TB does not yet include an active JTAG/iJTAG VIP. This active
precheck keeps the planned test runnable by proving the surrounding CSR/AXI
environment is healthy. The real JTAG/iJTAG transaction remains blocked on VIP
integration; do not probe the DFT window over SEP_IN AXI because it does not
return in the current public Verilator model.
"""

from __future__ import annotations

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import smc_addr
from .smc_base_test_seq import smc_base_test_seq

CHIP_CONFIG_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_BASE_ADDR")
CHIP_CONFIG_VERSION_LO_VALUE = 0x0001_00A0
SCRATCH_COLD_1 = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_BASE_ADDR") + 0x4
SCRATCH_PATTERN = 0x1A7A_0001


class smc_ijtag_basic_test_seq(smc_base_test_seq):
    def __init__(self, name: str = "smc_ijtag_basic_test_seq") -> None:
        super().__init__(name)
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

    async def body(self) -> None:
        await self._read(
            "CHIP_CONFIG_VERSION_LO", CHIP_CONFIG_VERSION_LO, expected=CHIP_CONFIG_VERSION_LO_VALUE
        )
        await self._write("SCRATCH_COLD_1", SCRATCH_COLD_1, SCRATCH_PATTERN)
        await self._read("SCRATCH_COLD_1", SCRATCH_COLD_1, expected=SCRATCH_PATTERN)
        await self._write("SCRATCH_COLD_1_RESTORE", SCRATCH_COLD_1, 0)
        await self._read("SCRATCH_COLD_1_RESTORE", SCRATCH_COLD_1, expected=0)
        assert self.accesses == 5, "expected iJTAG precheck CSR access sequence"
