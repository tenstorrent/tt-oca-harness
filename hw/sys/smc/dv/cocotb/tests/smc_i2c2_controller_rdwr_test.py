# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C2 as the bus controller: a write and a two-byte read against I2C1."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c2_controller_rdwr_test_seq import smc_i2c2_controller_rdwr_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c2_controller_rdwr_test(smc_base_test):
    """Drive a controller write and a controller read from I2C2."""

    required_evidence = (
        "CHK-I2C2-CTRL-READ",
        "CHK-I2C2-CTRL-WRITE",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c2_controller_rdwr_test_seq("smc_i2c2_controller_rdwr_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Directed stimulus floor: the LSIO arming for three instances, the
            # target and controller bring-up writes, and the format-FIFO and
            # readback accesses of both legs; the floor is independent of
            # `seq.accesses`, so a sequence that stops issuing accesses cannot
            # lower it.
            min_csr_accesses=60,
            csr_accesses=seq.accesses,
            proxy=False,
            details="I2C2 driving the shared bus as controller for a write and a read",
        )
