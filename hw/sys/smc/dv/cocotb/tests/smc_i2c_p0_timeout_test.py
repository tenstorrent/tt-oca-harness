# SPDX-License-Identifier: Apache-2.0
"""I2C1 stretch-timeout while I2C0 target holds SCL."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_i2c_p0_timeout_test_seq import smc_i2c_p0_timeout_test_seq


@pyuvm.test()
class smc_i2c_p0_timeout_test(smc_base_test):
    """Stretch-timeout observation (empty target TX during host READ)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_p0_timeout_test_seq("i2c_p0_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.stretch_ok, "stretch_timeout not observed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=f"STRETCH_TIMEOUT stretch_ok={seq.stretch_ok}",
        )
