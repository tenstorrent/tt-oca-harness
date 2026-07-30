# SPDX-License-Identifier: Apache-2.0
"""SEP boot-ROM smoke test.

Boots VeeR EL2 from the OSS behavioral boot-ROM responder and checks that the
retired-instruction trace advances through the expected ROM addresses.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import RisingEdge

import pyuvm

from sep_base_test import sep_base_test

_BOOT_ROM_BASE = 0x1004_0000
_LOOP_PC = _BOOT_ROM_BASE + 12
_MAX_CYCLES = 50_000


@pyuvm.test()
class sep_boot_rom_smoke_test(sep_base_test):
    """Fetch and retire instructions out of the OSS boot-ROM responder."""

    build_env = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        await self.bring_up_cpu_boot(_BOOT_ROM_BASE >> 1)

        pcs: set[int] = set()
        for _cycle in range(_MAX_CYCLES):
            await RisingEdge(dut.clk_i)
            if self.rd(dut.cpu_trace_valid_o):
                pc = self.rd(dut.cpu_trace_addr_o) & 0xFFFF_FFFF
                pcs.add(pc)
                if pc == _LOOP_PC:
                    break

        self.logger.info("boot-ROM PCs seen: %s", sorted(hex(pc) for pc in pcs))
        assert _LOOP_PC in pcs, (
            "boot ROM fetch did not retire the expected loop PC; "
            f"expected 0x{_LOOP_PC:08x}, saw {sorted(hex(pc) for pc in pcs)}"
        )
