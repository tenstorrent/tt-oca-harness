# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A bus timeout expiring in every phase of a target transaction."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_target_bus_timeout_test_seq import (
    smc_i2c_target_bus_timeout_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_bus_timeout_test(smc_base_test):
    """Expire the programmable bus timeout in every phase, on all three instances."""

    required_evidence = (
        "CHK-I2C0-BUSTO-ADDR-STRETCH",
        "CHK-I2C0-BUSTO-SLOT-SWEEP",
        "CHK-I2C0-BUSTO-STRETCH",
        "CHK-I2C1-BUSTO-ADDR-STRETCH",
        "CHK-I2C1-BUSTO-SLOT-SWEEP",
        "CHK-I2C1-BUSTO-STRETCH",
        "CHK-I2C2-BUSTO-ADDR-STRETCH",
        "CHK-I2C2-BUSTO-SLOT-SWEEP",
        "CHK-I2C2-BUSTO-STRETCH",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_bus_timeout_test_seq("smc_i2c_target_bus_timeout_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Directed stimulus floor: the LSIO arming for three instances, the
            # timeout programming and readback per instance, and the FIFO
            # resets and acquisition drains around every slot and recovery.
            # Literal here, not read from `seq.accesses`.
            min_csr_accesses=300,
            csr_accesses=seq.accesses,
            proxy=False,
            details="Bus timeout expiring at every slot of an addressed target transaction",
        )
