# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS eFuse/OTP observable bounded semantics test."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_otp_clock_test_seq import smc_efuse_otp_clock_test_seq
from seq_lib.smc_efuse_vip_utils import check_efuse_otp_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_otp_clock_test(smc_base_test):
    """Run the eFuse/OTP and clock-control CSR precheck."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_otp_clock_test_seq("efuse_otp_clock_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_efuse_otp_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.EFUSE,
            type(self).__name__,
            csr_accesses=seq.accesses,
            proxy=False,
            details="eFuse/OTP chip-config observable semantics and clock stability checked",
        )
