# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Supplementary GPIO blocks of the external window and the eFuse SHIM boundary.

Spec sources: hw/sys/smc/doc/memmap.adoc (AXI-Lite External Window).

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_gpio_ext_extra_decode_test --tool verilator
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_ext_extra_decode_test_seq import smc_gpio_ext_extra_decode_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_ext_extra_decode_test(smc_base_test):
    """gpio_extra_intf / gpio_extra_ctrl forwarding and the SHIM boundary."""

    required_evidence = (
        "CHK-GPIO-EXT-EXTRA-CTRL-ROUTED",
        "CHK-GPIO-EXT-EXTRA-INTF-ROUTED",
        "CHK-GPIO-EXT-EXTRA-RESPONSE",
        "CHK-GPIO-EXT-EXTRA-SHIM-BOUNDARY",
        "CHK-NONVAC",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_ext_extra_decode_test_seq("gpio_ext_extra_decode_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
