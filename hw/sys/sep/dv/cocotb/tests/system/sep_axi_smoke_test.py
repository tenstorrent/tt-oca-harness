# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_LOCAL_BASE_ADDR reads its reset value, and four SEP_CPU_CTRL registers read back OKAY.

The CPU-LSU master reads SEP_LOCAL_BASE_ADDR and writes and reads back four
SEP_CPU_CTRL registers. Each read must answer OKAY with the expected value
(CHK-AXI-SMOKE, in seq_lib/sep_axi_smoke_seq.py). Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_axi_smoke_seq import sep_axi_smoke_seq


@pyuvm.test()
class sep_axi_smoke_test(sep_base_test):
    """SEP_LOCAL_BASE_ADDR equals its reset value, and four SEP_CPU_CTRL registers
    return the written pattern, OKAY, over the CPU LSU bus."""

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_axi_smoke_seq("smoke_seq")
        await self.start_seq(seq)
