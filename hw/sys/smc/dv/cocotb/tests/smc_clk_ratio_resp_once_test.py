# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Exactly-once SEP_IN responses across the SMC-domain and peripheral CDC paths at 10 / 1.25 / 5 ns.

Spec sources: hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/clk_rst.adoc, hw/sys/smc/doc/fabric.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_clk_ratio_resp_once_test_seq import smc_clk_ratio_resp_once_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-NONVAC",
    "CHK-RESP-ONCE-MIXED",
    "CHK-RESP-ONCE-PERIPH",
    "CHK-RESP-ONCE-SMC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_clk_ratio_resp_once_test(smc_base_test):
    """Counted scratch, UART SCR and mixed outstanding sequences with a passive sampler."""

    required_evidence = REQUIRED
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clk_ratio_resp_once_test_seq("clk_ratio_resp_once_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n != "CHK-NONVAC" and n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
