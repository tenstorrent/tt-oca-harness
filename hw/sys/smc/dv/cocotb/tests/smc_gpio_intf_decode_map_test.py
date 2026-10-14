# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO_INTF instance decode and aliasing.

Spec sources: hw/ip/gpio/regs/gpio_intf.rdl, doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_intf_decode_map_test_seq import smc_gpio_intf_decode_map_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_intf_decode_map_test(smc_base_test):
    """Check GPIO_INTF decode, aliasing and the Programmer's Guide formula."""

    required_evidence = (
        "CHK-GPIO-DECODE-ENDPOINTS",
        "CHK-GPIO-DECODE-NO-ALIAS",
        "CHK-GPIO-DECODE-REG-DISTINCT",
        "CHK-GPIO-DECODE-PG-FORMULA",
        "CHK-NONVAC",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_intf_decode_map_test_seq("smc_gpio_intf_decode_map_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
