# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS AVSBus clock/config bounded VIP test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_avsbus_clock_config_proxy_test_seq import (
    smc_avsbus_clock_config_proxy_test_seq,
)
from seq_lib.smc_sideband_vip_utils import check_sideband_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_clock_config_proxy_test(smc_base_test):
    """Run AVS clock-gate and config decode proxy checks."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_clock_config_proxy_test_seq("avsbus_clock_config_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_sideband_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=True,
            details="AVSBus clock/config timeout path plus bounded IRQ/state observability",
        )
