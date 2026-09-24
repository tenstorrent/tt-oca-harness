# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The log engine's fetch refused by the bus, and the error interrupt it raises."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_log_engine_fetch_error_test_seq import smc_log_engine_fetch_error_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_log_engine_fetch_error_test(smc_base_test):
    """Point the log engine's fetch at an address that refuses it."""

    required_evidence = (
        "CHK-LOG-ENGINE-FETCH-ERR",
        "CHK-LOG-ENGINE-WRITE-ERR-TEST",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_fetch_error_test_seq("smc_log_engine_fetch_error_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
