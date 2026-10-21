# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_005 ANCHOR: smc_gpio_output_driveback_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: 2588af6e0f784bdfcb96f67b00532a7fe208f4c3ec4cddde01ad3a340df538bc
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 109 `smc_gpio_output_driveback_test` ENV: cocotb
"""SMC OSS GPIO register-driven output (core2pad) driveback and pad direction walk."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_output_driveback_test_seq import (
    WALKED_COUNT,
    smc_gpio_output_driveback_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_output_driveback_test(smc_base_test):
    """Program GPIO wrap 0 as TX output and check the DUT pad outputs, then walk the
    direction enables of every free GPIO interface through DATA_CTRL."""

    required_evidence = (
        "CHK-GPIO-OUTPUT-DRIVEBACK",
        "CHK-GPIO-PAD-BOTH-DISABLED",
        "CHK-GPIO-PAD-RESTORE",
        "CHK-GPIO-PAD-TX-ENABLE",
        "CHK-NONVAC",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_output_driveback_test_seq("gpio_output_driveback_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert len(seq.pads) == WALKED_COUNT, "the pad direction walk did not cover every interface"
        assert seq.fence and seq.fence[0][0] == "WRAP0-LEG", "the ordered fence did not record"
