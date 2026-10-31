# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SRAM returns a 64-bit write, and a 4-byte write changes only its half.

The CPU-LSU master reads base+0x100 before any write and requires an OKAY
answer and a word other than the 64-bit pattern (CTRL-SRAM-PRE: a refused read
returns 0, which also differs from the pattern), writes and reads back the
pattern, then a 4-byte (AxSIZE=2) write must change only the upper half
(CHK-STORE, CHK-LANE, in seq_lib/sep_sram_smoke_seq.py). No document states the
response of an SRAM access, so OBS-RESP logs each response code, not graded.
Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from env.sep_fabric_common import RESP_NAME
from sep_base_test import sep_base_test
from seq_lib.sep_sram_smoke_seq import sep_sram_smoke_seq


@pyuvm.test()
class sep_sram_smoke_test(sep_base_test):
    """Every SRAM readback in sep_sram_smoke_seq equals its expected word."""

    required_evidence = ("CHK-STORE", "CHK-LANE")

    async def run_scenario(self) -> None:
        await self.bring_up_no_cpu()
        seq = sep_sram_smoke_seq("sram_smoke_seq")
        await self.start_seq(seq)
        self.logger.info(
            "OBS-RESP LOG accesses=%d %s",
            len(seq.responses),
            " ".join(f"{op}@0x{addr:08x}={RESP_NAME.get(c, c)}" for op, addr, c in seq.responses),
        )
