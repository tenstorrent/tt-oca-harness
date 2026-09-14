# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Sequence for smc_ijtag_basic_test.

The bench has no iJTAG (IEEE 1687) VIP; this sequence checks the CSR/AXI path
around the DFT window, and the test module drives the CPU JTAG TAP through
``smc_jtag_vip_utils``. The DFT window is not probed over SEP_IN AXI: that
access does not return on the Verilator model.
"""

from __future__ import annotations

from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

# ``_REPO`` / ``_field_mask`` come from the authoritative-map module:
# it is the single place that knows the repo layout and how to read a generated
# PeakRDL C header, and the chip_config block resets live in a block header
# (misc_wrap.h) that ``smc_addr_map`` exposes no named accessor for.
from .smc_addr_map import _REPO, _field_mask, smc_addr, smc_indexed_addr
from .smc_base_test_seq import smc_base_test_seq

_MISC_WRAP_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "misc_wrap.h"

# Addressed by the PER-REGISTER generated symbol, not the enclosing CHIP_CONFIG
# block base: a block base makes the register identity printed in the log
# depend on VERSION_LO staying at block offset 0
# ([ADDRESS-FROM-AUTHORITATIVE-MAP], log-name/symbol agreement clause).
CHIP_CONFIG_VERSION_LO = smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR")
# Expected value from the generated block header rather than a hand literal, so
# the address and the value come from one regenerated source.
CHIP_CONFIG_VERSION_LO_VALUE = _field_mask(
    _MISC_WRAP_H, "CHIP_CONFIG__VERSION_LO__VERSION_LO_reset"
)
# Addressed by the generated PeakRDL indexed symbol (smc_addr.h) instead of a
# hand ``+ 0x4`` off the array base, so the register identity in the log cannot
# rot away from the map when SCRATCH_COLD is regenerated.
SCRATCH_COLD_1 = smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", 1)
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
