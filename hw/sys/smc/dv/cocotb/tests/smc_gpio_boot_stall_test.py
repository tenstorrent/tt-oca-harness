# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO pad57 sticky boot-stall."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_gpio_boot_stall_test_seq import smc_gpio_boot_stall_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_gpio_boot_stall_test(smc_base_test):
    """Pad-57 boot stall hold/release/sticky lockout."""

    required_evidence = (
        "CHK-GPIO-BOOT-STALL-BASIC",
        "CHK-GPIO-BOOT-STALL-HOLD",
        "CHK-GPIO-BOOT-STALL-LOCK",
        "CHK-GPIO-BOOT-STALL-REL",
        "CHK-GPIO-BOOT-STALL-WARM",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_boot_stall_test_seq("gpio_boot_stall_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.held_ok and seq.release_ok and seq.lockout_ok, (
            f"gpio boot stall incomplete hold={seq.held_ok} "
            f"rel={seq.release_ok} lock={seq.lockout_ok}"
        )
