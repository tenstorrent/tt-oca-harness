# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""JTAG requests through the alias remap regions land at the translated SYS_OUT addresses."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_alias_remap_translate_test_seq import (
    ACCESS_FLOOR,
    JTAG_ACCESSES,
    smc_alias_remap_translate_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-ALIAS-CARRY",
    "CHK-ALIAS-EMPTY-REGION-IDENTITY",
    "CHK-ALIAS-LOWEST-REGION-WINS",
    "CHK-ALIAS-OFFSET-LOW12",
    "CHK-ALIAS-OFFSET-WRAPS-AT-BIT55",
    "CHK-ALIAS-RANGE-EDGES",
    "CHK-ALIAS-RD-WR",
    "CHK-ALIAS-REPROGRAM-OUTSTANDING",
    "CHK-ALIAS-RESET-IDENTITY",
    "CHK-ALIAS-VALID0-TRANSPARENT",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_alias_remap_translate_test(smc_base_test):
    """Alias remap reset identity, offsets, edges, carry, bit-55 wrap, overlap, empty, reprogram."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_alias_remap_translate_test_seq("alias_remap_translate_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        assert seq.jtag_accesses == JTAG_ACCESSES, f"{seq.jtag_accesses} JTAG accesses"
        total = seq.accesses + seq.jtag_accesses
        assert total >= ACCESS_FLOOR, f"{total} accesses issued, floor {ACCESS_FLOOR}"
