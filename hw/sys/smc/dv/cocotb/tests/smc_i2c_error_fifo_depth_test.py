# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I2C error/FIFO depth pin-level test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_master_target_test_seq import smc_i2c_master_target_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_error_fifo_depth_test(smc_base_test):
    """Run I2C CSR decode plus SCL/SDA pin override depth checks."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_master_target_test_seq("i2c_error_fifo_depth_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Conservative stimulus floor: 59 accesses observed in the retained
            # regression run; the I2C STATUS/FIFO polls are a timing-dependent
            # remainder, so the floor is set below the observed count. Literal
            # here, not read from `seq.accesses`.
            min_csr_accesses=45,
            csr_accesses=seq.accesses,
            proxy=False,
            details="I2C0 LSIO SCL/SDA release and pull-low behavior checked",
        )
