# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""eFuse locked-shadow access IRQ. Not map/LC."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_locked_access_interrupt_test_seq import (
    smc_efuse_locked_access_interrupt_test_seq,
)


@pyuvm.test()
class smc_efuse_locked_access_interrupt_test(smc_base_test):
    """CHIPLET_ID unlocked write silent; locked write/read pulse bit 28."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_locked_access_interrupt_test_seq("efuse_lock_irq_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.unlock_ok and seq.wrlock_ok and seq.rdlock_ok, (
            f"efuse lock irq incomplete unlock={seq.unlock_ok} "
            f"wr={seq.wrlock_ok} rd={seq.rdlock_ok}"
        )
