# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Byte-offset accesses, all-ones and all-zero words, and a high offset on every mailbox port.

Every one of the 64 mailbox apertures pushes a byte on lane 1 and on lane 2 with lane-strobed
64-bit writes whose other lanes carry the complement and pops each as the byte on its lane with
zeros elsewhere, pushes a byte at offset 3 and pops it with a 1-byte read there, pops an
all-ones word intact, pushes an all-zero word that `STATUS` reports queued and pops it as 0, and
with one word queued is read at an offset no register occupies (SLVERR with data 0 inside the
mailbox span, DECERR past it), after which `STATUS` still reports the word queued, the word
pops intact and `STATUS` reports the FIFO empty.

Run:
    python3 tools/dv/run_dv.py --dut smc --items smc_mailbox_lane_offset_walk_test --tool vcs
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_mailbox_lane_offset_walk_test_seq import (
    CHECKERS,
    PLANNED_ACCESSES,
    smc_mailbox_lane_offset_walk_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_mailbox_lane_offset_walk_test(smc_base_test):
    """Byte-offset, all-ones, all-zero and high-offset accesses on every mailbox port."""

    required_evidence = CHECKERS
    min_evidence = len(CHECKERS)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_mailbox_lane_offset_walk_test_seq()
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses == PLANNED_ACCESSES, (
            f"{seq.accesses} SEP_IN accesses, the plan issues {PLANNED_ACCESSES}"
        )
        missing = [n for n in CHECKERS if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
