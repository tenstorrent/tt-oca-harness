# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Alias remap AxCACHE replacement, attribute hold across half writes and the shared table."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_alias_remap_attr_test_seq import (
    ACCESS_FLOOR,
    JTAG_ACCESSES,
    smc_alias_remap_attr_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-ALIAS-CACHE-REPLACE-AW",
    "CHK-ALIAS-CACHE-REPLACE-AR",
    "CHK-ALIAS-CACHE-MISS",
    "CHK-ALIAS-CACHE-ZERO-OBSERVE",
    "CHK-ALIAS-ATTR-HOLD-OFFSET-HALF",
    "CHK-ALIAS-ATTR-HOLD-UPPER-HALF",
    "CHK-ALIAS-SHARED-DMA",
    "CHK-ALIAS-SHARED-SIMULTANEOUS",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_alias_remap_attr_test(smc_base_test):
    """JTAG and DMA traffic through alias remap regions 2, 4, 5 and 6."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_alias_remap_attr_test_seq("alias_remap_attr_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        assert seq.jtag_accesses == JTAG_ACCESSES, f"{seq.jtag_accesses} JTAG accesses"
        total = seq.accesses + seq.jtag_accesses
        assert total >= ACCESS_FLOOR, f"{total} accesses issued, floor {ACCESS_FLOOR}"
