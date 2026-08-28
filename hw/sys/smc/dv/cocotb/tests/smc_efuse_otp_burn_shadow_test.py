# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U7-5 / P2-6 OTP burn + shadow verify (behavioral eFuse responder)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from smc_base_test import smc_base_test
from seq_lib.smc_efuse_otp_burn_shadow_test_seq import (
    smc_efuse_otp_burn_shadow_test_seq,
)


@pyuvm.test()
class smc_efuse_otp_burn_shadow_test(smc_base_test):
    """Real fuse-sense + program-fail + sticky-OR burn through DUT CSR."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_otp_burn_shadow_test_seq("efuse_otp_burn_shadow_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor: 8 SEP_IN AXI OTP sense/shadow/burn
            # accesses. Literal here, not read from `seq.accesses`.
            min_csr_accesses=8,
            csr_accesses=seq.accesses,
            proxy=False,
            details="OTP sense+shadow+burn/fail via efuse_bank_model",
        )
