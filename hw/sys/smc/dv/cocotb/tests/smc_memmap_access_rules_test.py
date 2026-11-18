# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Burst, exclusive, hole and past-end rules of memmap.adoc over SEP_IN.

A read or write burst that starts between unit apertures answers DECERR on every beat with
the gap word; an exclusive read or write of a generated block answers OKAY, never EXOKAY,
and the write lands; an unoccupied offset inside a block reads 0 with OKAY and ignores a
write; the beat of a split burst past the last register of smc_cpu_ctrl answers SLVERR with
data 0; the padding between remap and filter array entries answers OKAY with 0.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_memmap_access_rules_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_memmap_access_rules_test_seq import smc_memmap_access_rules_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_memmap_access_rules_test(smc_base_test):
    """Gap burst, exclusive, hole, past-end and array-padding answers of the SMC map."""

    required_evidence = (
        "CHK-ARRAY-PADDING-OKAY",
        "CHK-EXCL-OKAY-NEVER-EXOKAY",
        "CHK-GAP-BURST-ALL-BEATS-DECERR",
        "CHK-REGBLOCK-HOLE-OKAY-ZERO",
        "CHK-REGBLOCK-PAST-END-SLVERR",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    async def run_scenario(self) -> None:
        seq = smc_memmap_access_rules_test_seq("smc_memmap_access_rules_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
