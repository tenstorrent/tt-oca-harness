# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Base and last register decode of the mailbox, eFuse, timer, CLA, DMA and zeroer apertures.

Spec sources: smc.rdl unit placements and past-extent, memmap.adoc Address Space Organization,
fabric.adoc Fabric Topology.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_unit_extent_register_decode_test_seq import (
    smc_unit_extent_register_decode_test_seq,
)
from smc_base_test import smc_base_test

# Accesses the sequence issues: 8 filter setup and restore, 42 base-register reads (7 registers x
# 3 ports x 2 bases), 12 ROM reads, 16 SPM accesses, 12 spare, 3 last-register, 12 DMA and zeroer.
STIMULUS_FLOOR = 105


@pyuvm.test()
class smc_unit_extent_register_decode_test(smc_base_test):
    """Base registers, last registers and memory words of the unit apertures."""

    required_evidence = (
        "CHK-MAILBOX-BASE-PORTS",
        "CHK-EFUSE-BASE-PORTS",
        "CHK-TIMER-BASE-PORTS",
        "CHK-CLA-BASE-PORTS",
        "CHK-ROM-WORDS-PORTS",
        "CHK-SPM-WORDS-BASES",
        "CHK-SPARE-LAST-REGS",
        "CHK-LAST-REG-MAILBOX-EFUSE-TIMER",
        "CHK-LAST-REG-DMA-ZEROER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_unit_extent_register_decode_test_seq("unit_extent_register_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        seq.assert_all_reachable(STIMULUS_FLOOR, "UNIT_EXTENT_REGISTER_DECODE")
        seq.log_timeout_paths()
        seq.nonvac_fence(STIMULUS_FLOOR)
