# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS I2C P1 DUT-host read/write protocol test (alias of U4-2)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_i2c_master_target_test_seq import smc_i2c_master_target_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_p1_rdwr_protocol_test(smc_base_test):
    """U4-2 alias: DUT I2C0 host write proof (same sequence as master_target)."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_master_target_test_seq("i2c_p1_rdwr_protocol_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "I2C0 OVRD pin proof + DUT host write 0xAB@0x10 to EEPROM "
                f"slave (ok={seq.dut_host_write_ok})"
            ),
        )
