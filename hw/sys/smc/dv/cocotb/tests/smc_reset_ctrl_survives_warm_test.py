# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""RESET_CTRL keeps a held core across a watchdog warm reset.

Spec: clk_rst.adoc (SMC Reset Distribution, the warm-reset bullet).
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reset_ctrl_survives_warm_test_seq import (
    CHK,
    smc_reset_ctrl_survives_warm_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reset_ctrl_survives_warm_test(smc_base_test):
    """A core held through RESET_CTRL stays held after a SEP watchdog warm reset."""

    required_evidence = (CHK,)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reset_ctrl_survives_warm_test_seq("smc_reset_ctrl_survives_warm_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.passed, "the sequence did not reach its end"
