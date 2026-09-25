# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OCTS timer's CREDIT_EXPIRED register on a secondary starved of credits, and its reset by a write."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_octs_credit_expired_test_seq import smc_octs_credit_expired_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_octs_credit_expired_test(smc_base_test):
    """Starve a secondary OCTS timer of credits and reset CREDIT_EXPIRED by a write."""

    required_evidence = ("CHK-OCTS-CREDIT-EXPIRED",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_octs_credit_expired_test_seq("smc_octs_credit_expired_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
