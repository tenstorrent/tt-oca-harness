# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I2C_1/2 + I2C_CTRL CSR sweep."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_multi_instance_test_seq import (
    EXPECTED_ACCESSES,
    smc_i2c_multi_instance_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_multi_instance_test(smc_base_test):
    """I2C_1/2 + I2C_CTRL reset sweep and per-instance TARGET_ID co-resident patterns."""

    required_evidence = (
        "CHK-I2C-INSTANCE-CORESIDENT",
        "CHK-I2C-INSTANCE-RESET-DECODE",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_multi_instance_test_seq("smc_i2c_multi_instance_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Directed stimulus floor: 3 reset reads plus 4 accesses per
            # controller for the co-resident TARGET_ID leg. A constant of the
            # sequence module, not read back from `seq.accesses`.
            min_csr_accesses=EXPECTED_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details="I2C_1/2 + I2C_CTRL reset sweep; TARGET_ID co-resident per instance",
        )
