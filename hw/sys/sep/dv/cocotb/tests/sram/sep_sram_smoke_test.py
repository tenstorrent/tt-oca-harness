# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SRAM reads 0 after reset, returns a 64-bit write, and a 4-byte write changes only its half.

The CPU-LSU master reads base+0x100 as 0, writes and reads back a 64-bit word,
then a 4-byte (AxSIZE=2) write must change only the upper half (CHK-SRAM-SMOKE,
in seq_lib/sep_sram_smoke_seq.py). Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_sram_smoke_seq import sep_sram_smoke_seq


@pyuvm.test()
class sep_sram_smoke_test(sep_base_test):
    """Every SRAM readback in sep_sram_smoke_seq is OKAY and equals its expected word."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_sram_smoke_seq("sram_smoke_seq")
        await self.start_seq(seq)
