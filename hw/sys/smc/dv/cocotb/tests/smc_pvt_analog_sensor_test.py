# SPDX-License-Identifier: Apache-2.0
"""SMC OSS P1 coverage-gap: PVT combined + temp + GPIO POC/PBIAS sweep."""

from __future__ import annotations

import pyuvm

from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_pvt_analog_sensor_test_seq import smc_pvt_analog_sensor_test_seq


@pyuvm.test()
class smc_pvt_analog_sensor_test(smc_base_test):
    """P1 coverage-gap depth: PVT combined + temp + GPIO POC/PBIAS sweep."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_pvt_analog_sensor_test_seq("smc_pvt_analog_sensor_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CLOCK,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=True,
            details="P1 coverage-gap: PVT combined + temp + GPIO POC/PBIAS sweep",
        )
