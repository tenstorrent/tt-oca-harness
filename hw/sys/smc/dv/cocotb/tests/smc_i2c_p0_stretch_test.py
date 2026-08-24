# SPDX-License-Identifier: Apache-2.0
"""I2C0 target clock-stretch; I2C1 host waits."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i2c_p0_stretch_test_seq import smc_i2c_p0_stretch_test_seq


@pyuvm.test()
class smc_i2c_p0_stretch_test(smc_base_test):
    """TX stretch recover + RSTART read/write on shared I2C pads."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_stretch_test_seq("i2c_p0_stretch_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.stretch_ok and seq.read_ok, (
            f"stretch incomplete stretch={seq.stretch_ok} read={seq.read_ok}"
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"TX_PENDING stretch={seq.stretch_ok} read={seq.read_ok}"
            ),
        )
