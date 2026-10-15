# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""I2C0 controller read-word transfer against the bench target, with SMBus field variations."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_smbus_pmbus_linear11_read_test_seq import (
    smc_smbus_pmbus_linear11_read_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_pmbus_linear11_read_test(smc_base_test):
    """Two-byte word reads, one with SMBSUS written mid-transfer, one with the mode field clear."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-PMBUS-DECODE-LOG",
        "CHK-PMBUS-NEG-WORD-BYTES",
        "CHK-PMBUS-WORD-BYTES",
        "CHK-SCL-SDA-FIELD-INVARIANT",
        "CHK-SUS-DURING-XFER",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_pmbus_linear11_read_test_seq("smbus_pmbus_linear11_read_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
