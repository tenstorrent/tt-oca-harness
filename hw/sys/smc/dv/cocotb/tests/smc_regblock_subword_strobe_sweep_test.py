# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_W2T_008 ANCHOR: smc_regblock_subword_strobe_sweep_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 6267422078430d380d02f714df24eeee005c62cb6d96000f1dd983845f6c5ecb
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_W2T_VPLAN_DETAIL_ADDITIONS.md @ artifact_revision 2 ENV: cocotb
"""Sub-word reads, byte-lane and strobed writes, and window sweeps of the generated register blocks.

One reference register of each of the 133 register-block instances takes 1- and
2-byte reads between two full-width reads; five registers take 1-byte writes;
three remap entries take all ones; the system-timer and telemetry windows are
read word by word to the end of their apertures; and FILTER_CONFIG of all 32
filter entries takes single-lane strobed writes, a write-once lock and refused
writes once locked.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_regblock_subword_strobe_sweep_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_regblock_subword_strobe_sweep_test_seq import (
    CHECKERS,
    smc_regblock_subword_strobe_sweep_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-NONVAC",
    "CHK-SWEEP-BYTE-LANE",
    "CHK-SWEEP-FCFG-LANES",
    "CHK-SWEEP-FULLWIDTH-FILTER",
    "CHK-SWEEP-FULLWIDTH-REMAP",
    "CHK-SWEEP-LOCK-SET",
    "CHK-SWEEP-LOCKED-DECERR",
    "CHK-SWEEP-SUBWORD",
    "CHK-SWEEP-TELEM-WINDOW",
    "CHK-SWEEP-TIMER-WINDOW",
    "CHK-TIMEOUT-PATHS",
)
# S1 3; S2 58 64-bit instances x 17 and 75 32-bit instances x 9; S3 53; S4 12;
# S5 1024; S6 1026; S7 32 x 58; S8 32 x 2; S9 5; S10 31 x 4; S11 32 x 8. The
# S8 restores and S10 full-width fallbacks add two accesses each.
SEP_IN_FIXED = (
    3 + (58 * 17 + 75 * 9) + 53 + 12 + 1024 + 1026 + 32 * 58 + 32 * 2 + 5 + 31 * 4 + 32 * 8
)


@pyuvm.test()
class smc_regblock_subword_strobe_sweep_test(smc_base_test):
    """Sub-word, byte-lane, strobed and window sweeps of every generated register block."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_regblock_subword_strobe_sweep_test_seq(
            "smc_regblock_subword_strobe_sweep_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        planned = SEP_IN_FIXED + seq.branch_accesses
        assert seq.accesses == planned, (
            f"{seq.accesses} SEP_IN accesses, the plan issues {planned} "
            f"({seq.branch_accesses} on the restore / fallback branches)"
        )
        assert sorted(CHECKERS) == list(REQUIRED), "checker set differs from required_evidence"
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
