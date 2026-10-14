# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The I2C bus monitor's idle-with-SCL-high state, on every instance."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_bus_monitor_idle_test_seq import smc_i2c_bus_monitor_idle_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_bus_monitor_idle_test(smc_base_test):
    """Drive the bus monitor into and out of its idling state on every instance."""

    required_evidence = (
        "CHK-I2C0-BUSMON-IDLE-TIMEOUT",
        "CHK-I2C0-BUSMON-MULTI-ENABLE",
        "CHK-I2C0-BUSMON-RESUME",
        "CHK-I2C1-BUSMON-IDLE-TIMEOUT",
        "CHK-I2C1-BUSMON-MULTI-ENABLE",
        "CHK-I2C1-BUSMON-RESUME",
        "CHK-I2C2-BUSMON-IDLE-TIMEOUT",
        "CHK-I2C2-BUSMON-MULTI-ENABLE",
        "CHK-I2C2-BUSMON-RESUME",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_bus_monitor_idle_test_seq("smc_i2c_bus_monitor_idle_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Directed stimulus floor: the LSIO arming for three instances, the
            # bring-up and HOST_TIMEOUT_CTRL programming with readback per
            # instance, and the interrupt clears, drains and clean writes
            # around each of the three legs; the floor is independent of
            # `seq.accesses`, so a sequence that stops issuing accesses cannot
            # lower it.
            min_csr_accesses=150,
            csr_accesses=seq.accesses,
            proxy=False,
            details="I2C bus monitor idling state entered and left on every instance",
        )
