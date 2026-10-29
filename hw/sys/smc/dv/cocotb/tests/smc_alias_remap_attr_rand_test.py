# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded alias remap regions translate JTAG accesses and replace their AxCACHE."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_alias_remap_attr_rand_test_seq import (
    COMPARED_ACCESSES,
    smc_alias_remap_attr_rand_test_seq,
)
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-ALR-EDGE-MISS",
    "CHK-ALR-HIT-CACHE",
    "CHK-ALR-HIT-TRANSLATE",
    "CHK-ALR-LOGGED",
    "CHK-ALR-RESET-TRANSPARENT",
    "CHK-ALR-RESET-WORDS",
    "CHK-ALR-VALID-CLEAR",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_alias_remap_attr_rand_test(smc_base_test):
    """Drawn alias remap regions: hits, edges, valid clear, and the measured legs."""

    required_evidence = REQUIRED
    min_evidence = len(REQUIRED)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_alias_remap_attr_rand_test_seq(
            "alias_remap_attr_rand_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        assert seq.compared == COMPARED_ACCESSES, f"{seq.compared} compared JTAG accesses"
