# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""VeeR EL2 fetches and retires every instruction of the staged boot-ROM program.

The test boots VeeR EL2 from the behavioral boot-ROM responder and samples the
retired-instruction trace from before the CPU release.

Checks:
  CHK-ROM-EXEC : the trace retires base+0/4/8/12 of cocotb/tests/sep_boot_rom.hex, so a
                 fetch path that skips a ROM word or breaks control flow fails.
                 sep_boot_rom_lsu_read_test checks the ROM content.

cpu / +skip_fuse_sense (no fuse data is read).
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import RisingEdge
from sep_base_test import sep_base_test
from sep_reg_meta import sym

_BOOT_ROM_BASE = sym("SEP_BOOT_ROM_MEM_BASE_ADDR")
_LOOP_PC = _BOOT_ROM_BASE + 12
_MAX_CYCLES = 50_000


@pyuvm.test()
class sep_boot_rom_smoke_test(sep_base_test):
    """All four boot-ROM PCs retire, not only the final loop PC."""

    build_env = False

    async def run_scenario(self) -> None:
        dut = cocotb.top
        pcs: set[int] = set()

        # Sample the retire trace from BEFORE the CPU is released. The ROM program's
        # first three PCs are transient -- the core retires them and then spins at
        # the loop PC forever -- so a sampler started after bring_up_cpu_boot() only
        # ever observes base+12 and cannot prove the rest of the program ran.
        async def _trace_sampler() -> None:
            while True:
                await RisingEdge(dut.clk_i)
                if self.rd(dut.cpu_trace_valid_o):
                    pcs.add(self.rd_known(dut.cpu_trace_addr_o) & 0xFFFF_FFFF)

        sampler = cocotb.start_soon(_trace_sampler())
        try:
            await self.bring_up_cpu_boot(_BOOT_ROM_BASE >> 1)
            for _cycle in range(_MAX_CYCLES):
                await RisingEdge(dut.clk_i)
                if _LOOP_PC in pcs:
                    break
        finally:
            sampler.kill()

        self.logger.info("boot-ROM PCs seen: %s", sorted(hex(pc) for pc in pcs))

        # Require the WHOLE known program to have retired, not just its final PC.
        # cocotb/tests/sep_boot_rom.hex is four instructions -- addi, addi, addi,
        # then `j .` -- so a healthy fetch path retires base+0/4/8/12. Asserting only
        # the loop PC cannot tell a correctly-fetched ROM from any image that happens
        # to reach base+12, which is the claim this smoke test exists to make.
        # (Instruction-CONTENT verification against a staged image is the separate
        # sep_boot_rom_lsu_read_test, which reads the ROM back over the LSU.)
        expected = [_BOOT_ROM_BASE + off for off in (0, 4, 8, 12)]
        missing = [pc for pc in expected if pc not in pcs]
        assert not missing, (
            "boot ROM fetch did not retire the full known program; missing "
            f"{[hex(pc) for pc in missing]}, saw {sorted(hex(pc) for pc in pcs)}"
        )
        self.logger.info(
            "CHK-ROM-EXEC PASS: retired all %d instructions of the staged boot-ROM program (%s)",
            len(expected),
            " ".join(hex(pc) for pc in expected),
        )
