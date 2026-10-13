# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 target address gate: role select, TARGET_ID match and non-match."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i2c_target_addr_gate_test_seq import smc_i2c_target_addr_gate_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i2c_target_addr_gate_test(smc_base_test):
    """A bench controller addresses the I2C0 target; CTRL and TARGET_ID decide the ACK."""

    required_evidence = (
        "CHK-I2C-TGT-GATE-PAIR0",
        "CHK-I2C-TGT-GATE-PAIR1",
        "CHK-I2C-TGT-GATE-NONMATCH",
        "CHK-I2C-TGT-GATE-MASKZERO",
        "CHK-I2C-TGT-GATE-REWRITE",
        "CHK-I2C-TGT-ROLE-GATE",
        "CHK-I2C-TGT-ADDR-ONLY",
        "CHK-I2C-TGT-RESTART-ADDRESS",
        "CHK-I2C-TGT-ROLE-MIDTRANSFER-LOG",
        "CHK-I2C-TGT-ROLE-MIDTRANSFER-RECOVER",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i2c_target_addr_gate_test_seq("i2c_target_addr_gate_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
