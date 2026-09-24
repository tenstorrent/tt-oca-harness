# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A controller finding SDA pulled low under it, at points across a write."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_controller_sda_interference_test_seq import (
    smc_i2c_controller_sda_interference_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_controller_sda_interference_test(smc_base_test):
    """Pull SDA low under a transmitting controller at points across a write."""

    required_evidence = (
        "CHK-I2C0-CTRL-SDA-INTERFERENCE",
        "CHK-I2C1-CTRL-SDA-INTERFERENCE",
        "CHK-I2C2-CTRL-SDA-INTERFERENCE",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_controller_sda_interference_test_seq(
            "smc_i2c_controller_sda_interference_test_seq"
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Directed stimulus floor: the LSIO arming for three instances, and
            # per instance the control transaction plus a hard reset of both
            # instances and an injection for each of the four points. Literal
            # here, not read from `seq.accesses`.
            min_csr_accesses=250,
            csr_accesses=seq.accesses,
            proxy=False,
            details="SDA pulled low under a transmitting I2C controller at swept write points",
        )
