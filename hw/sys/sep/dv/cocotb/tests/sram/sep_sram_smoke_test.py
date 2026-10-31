# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SRAM returns a 64-bit write, and a 4-byte write changes only its half.

The CPU-LSU master reads base+0x100 before any write and requires an OKAY
answer and a word other than the 64-bit pattern (CTRL-SRAM-PRE), writes and
reads back the pattern, then a 4-byte (AxSIZE=2) write must change only the
upper half (CHK-STORE, CHK-LANE, in seq_lib/sep_sram_smoke_seq.py). Every access answers OKAY
with no scoreboard rejection (CHK-RESP). Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_sram_smoke_seq import sep_sram_smoke_seq


@pyuvm.test()
class sep_sram_smoke_test(sep_base_test):
    """Every SRAM readback in sep_sram_smoke_seq is OKAY and equals its expected word."""

    required_evidence = ("CHK-STORE", "CHK-LANE", "CHK-RESP")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_sram_smoke_seq("sram_smoke_seq")
        mark = self.sb_mark()
        await self.start_seq(seq)
        bad = [f"{op}@0x{addr:08x}" for op, addr, ok in seq.responses if not ok]
        rejected = self.env.scoreboard.errors[mark[0] :]
        assert not bad and not rejected, (
            f"CHK-RESP FAIL: non-OKAY {bad}; scoreboard rejections {rejected}"
        )
        self.logger.info(
            "CHK-RESP PASS: accesses=%d all OKAY, 0 scoreboard rejections", len(seq.responses)
        )
