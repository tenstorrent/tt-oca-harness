# SPDX-License-Identifier: Apache-2.0
"""I2C0 and I2C2 hosts both write I2C1 target."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i2c_p0_multictrl_test_seq import smc_i2c_p0_multictrl_test_seq


@pyuvm.test()
class smc_i2c_p0_multictrl_test(smc_base_test):
    """Three-phase I2C0/1/2 shared-bus write + ACQ proof."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_multictrl_test_seq("i2c_p0_multictrl_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert all(seq.phases_ok), f"multictrl incomplete: {seq.phases_ok}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "I2C0/1/2 time-multiplexed shared-bus writes; "
                f"phases_ok={seq.phases_ok}"
            ),
        )
