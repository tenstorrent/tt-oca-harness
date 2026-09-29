# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC_XVISOR_REMAP full sweep (TC_SMC_P1CG_20).

The generated map declares an 8-entry hypervisor remap table
(SMC_XVISOR_REMAP_0..7, ATTRS-only per entry), a sibling of the ALIAS_REMAP and
MMODE_REMAP tables. Two legs, both scoreboard-compared: every entry reads its
generated reset, and every entry then holds a distinct pattern while the other
seven hold theirs, so a decode that aliases two entries -- or an undecoded
window that answers OKAY with zeros -- fails the readback.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cocotb

from .smc_csr_seq_utils import SmcCsrSeq

# Generated PeakRDL map (hw/sys/smc/regs/gen/py/smc_reg.py).
_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_reg import (  # noqa: E402
    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
    SMC_XVISOR_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
)

# Per-entry REGION_ATTRS addresses from the generated map. The reset value comes
# from the same generated map (output_remap.rdl).
XVISOR_REMAP_ATTRS_ADDRS = (
    SMC_XVISOR_REMAP_0__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_1__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_2__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_3__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_4__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_5__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_6__REGION_REGION_ATTRS_REG_ADDR,
    SMC_XVISOR_REMAP_7__REGION_REGION_ATTRS_REG_ADDR,
)
# One distinct pattern per entry inside the 56-bit `offset` field
# (output_remap.rdl), with `valid` clear. No outbound traffic runs while the
# table holds them, and every entry is restored to its reset afterwards.
XVISOR_REMAP_PATTERNS = tuple((0x5A5 << 40) | ((i + 1) << 12) for i in range(8))
assert len(set(XVISOR_REMAP_PATTERNS)) == len(XVISOR_REMAP_ATTRS_ADDRS)
# 8 reset reads + 8 x (pattern write, pattern read, restore write, restore read).
EXPECTED_ACCESSES = 8 + 4 * 8


class smc_xvisor_remap_test_seq(SmcCsrSeq):
    async def body(self) -> None:
        # XVISOR_REMAP 0..7 (ATTRS-only per entry). The reset read proves the
        # generated reset content of each address; on its own it cannot tell
        # eight registers from one aliased register or an OKAY-zero hole.
        observed = []
        for i, addr in enumerate(XVISOR_REMAP_ATTRS_ADDRS):
            observed.append(
                await self.csr_read(
                    f"XVISOR_REMAP_{i}_ATTRS",
                    addr,
                    expected=OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                    length=8,
                )
            )
        assert self.accesses == len(XVISOR_REMAP_ATTRS_ADDRS), "XVISOR_REMAP sweep count mismatch"
        cocotb.log.info(
            "CHK-XVISOR-REMAP-RESET-DEFAULT: XVISOR_REMAP_0..%d REGION_ATTRS at "
            "%#x..%#x read %s over SEP_IN AXI, each an OKAY scoreboard value "
            "compare against the RDL reset %#x",
            len(XVISOR_REMAP_ATTRS_ADDRS) - 1,
            XVISOR_REMAP_ATTRS_ADDRS[0],
            XVISOR_REMAP_ATTRS_ADDRS[-1],
            [f"{value:#x}" for value in observed],
            OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
        )
        # Per-entry decode: all eight patterns are written before any is read
        # back, so an aliased pair holds the last pattern written and the first
        # readback of the pair fails; every entry is then restored and re-read.
        await self.rw_coresident(
            [
                (
                    f"XVISOR_REMAP_{i}_ATTRS",
                    addr,
                    XVISOR_REMAP_PATTERNS[i],
                    OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
                )
                for i, addr in enumerate(XVISOR_REMAP_ATTRS_ADDRS)
            ],
            length=8,
        )
        assert self.accesses == EXPECTED_ACCESSES, (
            f"XVISOR_REMAP body issued {self.accesses} accesses, expected {EXPECTED_ACCESSES}"
        )
        cocotb.log.info(
            "CHK-XVISOR-REMAP-CORESIDENT: XVISOR_REMAP_0..%d REGION_ATTRS each held its own "
            "pattern (%s) while the other seven held theirs and read it back exactly, then "
            "read back the RDL reset %#x after the restore write; every readback a scoreboard "
            "value compare",
            len(XVISOR_REMAP_ATTRS_ADDRS) - 1,
            ", ".join(f"{p:#x}" for p in XVISOR_REMAP_PATTERNS),
            OUTPUT_REMAP_REGION_REGION_ATTRS_REG_DEFAULT,
        )
