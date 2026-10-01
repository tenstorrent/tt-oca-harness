# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Accesses to the unmapped tail of the misc, GPIO and DMA apertures.

Each unmapped access lies past the block's decoded extent and has to be
refused, the read with DECERR; the write has to leave a seeded live register of
the same block unchanged, and the read must not return that seed.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_decode_hole_test_seq import smc_decode_hole_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_decode_hole_test(smc_base_test):
    """Write and read the unmapped tail of three block apertures."""

    required_evidence = (
        "CHK-DECODE-HOLE-DATA_ACCEL",
        "CHK-DECODE-HOLE-GPIO",
        "CHK-DECODE-HOLE-MISC",
    )
    min_evidence = 3

    async def run_scenario(self) -> None:
        seq = smc_decode_hole_test_seq("smc_decode_hole_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
