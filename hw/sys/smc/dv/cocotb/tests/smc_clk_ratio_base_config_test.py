# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
Contract SMC_CLOCK_RATIO_006 ANCHOR: smc_clk_ratio_base_config_test
Scenarios: RATIO-BASECFG-XFER.S1, RATIO-BASECFG-XFER.S2, RATIO-BASECFG-XFER.S3
Sources: hw/sys/smc/regs/blocks/smc_base_config/smc_base_config.rdl, hw/sys/smc/doc/memmap.adoc
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_clk_ratio_base_config_test_seq import smc_clk_ratio_base_config_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-BASECFG-RESET-READ",
    "CHK-BASECFG-THRESHOLD-WRITE",
    "CHK-BASECFG-RO-IGNORED",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_clk_ratio_base_config_test(smc_base_test):
    """smc_base_config reset reads, threshold round trip and LOCAL_BASE write."""

    required_evidence = REQUIRED
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clk_ratio_base_config_test_seq("clk_ratio_base_config_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
