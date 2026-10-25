# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_W2T_007 ANCHOR: smc_remap_region_offset_walk_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 92cf4012b2ae455ac9e6022c2de06d406e75b909869529282c10afa24f126dab
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_W2T_VPLAN_DETAIL_ADDITIONS.md @ artifact_revision 1 ENV: cocotb
"""Alias, M-mode and Xvisor remap register field walks and one translated read per table.

Every alias, M-mode and Xvisor remap register reads its documented reset; every
address field takes all-ones, zero and a walking one and reads each back; `valid`
is set and cleared on all 24 entries and the alias `cacheable` field takes 0xF
and 0x0. One JTAG read per table then goes through a programmed entry, through
it with `valid` clear and (alias) at the region end, and SYS_OUT shows where.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_remap_region_offset_walk_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_remap_region_offset_walk_test_seq import (
    CHECKERS,
    smc_remap_region_offset_walk_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-NONVAC",
    "CHK-REMAP-ALIAS-ADDR-WALK",
    "CHK-REMAP-ALIAS-ATTR",
    "CHK-REMAP-ALIAS-XLATE",
    "CHK-REMAP-MMODE-WALK",
    "CHK-REMAP-MMODE-XLATE",
    "CHK-REMAP-RESET",
    "CHK-REMAP-XVISOR-WALK",
    "CHK-REMAP-XVISOR-XLATE",
    "CHK-TIMEOUT-PATHS",
)
# S1 LOCAL_BASE; S2 43 reads; S3 1104 write/read pairs; S4 32 pairs; S5 960
# pairs; S6 3 + 2 + 3 pairs; S7 / S8 3 pairs and 2 window probes each; S9 40
# pairs.
SEP_IN_ACCESSES = 1 + 43 + 2 * 1104 + 2 * 32 + 2 * 960 + 2 * 8 + 2 * (2 * 3 + 2) + 2 * 40
JTAG_READS = 3 + 2 + 2


@pyuvm.test()
class smc_remap_region_offset_walk_test(smc_base_test):
    """Every remap address field walked and read back; one translated read per table."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_remap_region_offset_walk_test_seq("smc_remap_region_offset_walk_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses == SEP_IN_ACCESSES, (
            f"{seq.accesses} SEP_IN accesses, the plan issues {SEP_IN_ACCESSES}"
        )
        assert seq.jtag_accesses == JTAG_READS, (
            f"{seq.jtag_accesses} JTAG reads, the plan issues {JTAG_READS}"
        )
        assert sorted(CHECKERS) == list(REQUIRED), "checker set differs from required_evidence"
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
