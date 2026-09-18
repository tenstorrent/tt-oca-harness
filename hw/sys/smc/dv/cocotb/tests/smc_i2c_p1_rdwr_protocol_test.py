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

    required_evidence = (
        "CHK-I2C0-HOST-WRITE",
        "CHK-I2C0-OVRD-PAD",
        "CHK-I2C0-SMBUS-ARA",
        "CHK-I2C0-SMBUS-PEC",
        "CHK-I2C0-U4-2-SMBUS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_master_target_test_seq("i2c_p1_rdwr_protocol_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: it sits below the
            # run-to-run minimum because the OVRD/EEPROM status polls are timing-dependent.
            min_csr_accesses=48,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "I2C0 OVRD pin proof + DUT host write 0xAB@0x10 to EEPROM "
                f"slave (ok={seq.dut_host_write_ok})"
            ),
        )
