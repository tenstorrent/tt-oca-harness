# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS PyUVM SMBus + PMBus protocol test (P2-A / P2-11)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_smbus_pmbus_test_seq import smc_smbus_pmbus_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_smbus_pmbus_test(smc_base_test):
    """P2-A / P2-11: SMBus ARA + PEC + PMBus Linear11 proof."""

    required_evidence = (
        "CHK-SMBUS-ARA",
        "CHK-SMBUS-PEC-REF",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_smbus_pmbus_test_seq("smbus_pmbus_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.I2C,
            type(self).__name__,
            csr_accesses=0,
            # This scenario issues no CSR traffic and carries no byte golden on
            # the record, so there is nothing on the record that could fail.
            # It is therefore booked as an ACTIVITY STAMP in the scoreboard's
            # protocol_vip_auto bin instead of as a protocol VIP check
            # ([NO-ALWAYS-PASS-CHECKER]). The scenario's real proof is its own
            # in-sequence PEC/ARA/Linear11 asserts, which are unaffected.
            auto_evidence=True,
            proxy=False,
            details=(
                "SMBus write-with-PEC + ARA query traversed tb_i2c0_* pins; "
                "PMBus Linear11 encode/decode round-trip verified"
            ),
        )
