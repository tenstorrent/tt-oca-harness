# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""GPIO pad57 sticky boot-stall."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_gpio_boot_stall_test_seq import smc_gpio_boot_stall_test_seq


@pyuvm.test()
class smc_gpio_boot_stall_test(smc_base_test):
    """Pad-57 boot stall hold/release/sticky lockout."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_gpio_boot_stall_test_seq("gpio_boot_stall_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.held_ok and seq.release_ok and seq.lockout_ok, (
            f"gpio boot stall incomplete hold={seq.held_ok} "
            f"rel={seq.release_ok} lock={seq.lockout_ok}"
        )
