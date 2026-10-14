# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""AVSBus pad enables follow AVS_CONFIG.AVS_GPIO_ENABLE and the enabled pads carry a frame.

Sources: hw/ip/avsbus_controller/doc/interface.adoc, hw/sys/smc/doc/clk_rst.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_avsbus_pad_enable_test_seq import smc_avsbus_pad_enable_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_pad_enable_test(smc_base_test):
    """Toggle AVS_GPIO_ENABLE and watch the pad enables, then run one frame on the pads."""

    required_evidence = (
        "CHK-AVS-PAD-ENABLE-FOLLOWS",
        "CHK-AVS-PAD-PROTOCOL",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_pad_enable_test_seq("smc_avsbus_pad_enable_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
