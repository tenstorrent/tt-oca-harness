# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS OCCP/secure-error public-path test (P2-2 / U7-6).

Uses OTP program-fail + signature gates through the behavioral eFuse responder
(no proprietary OCCP ROM required).
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_occp_sanity_secure_error_test_seq import (
    smc_occp_sanity_secure_error_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_occp_sanity_secure_error_test(smc_base_test):
    """Secure program-fail negative + recovery burn / signature positive."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_occp_sanity_secure_error_test_seq("occp_secure_error_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Directed stimulus floor: 8 SEP_IN AXI OTP-program-fail and
            # EFUSE_MAP signature accesses. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=8,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "OTP program-fail + EFUSE_MAP signature gate "
                "(OSS public secure-error; not full OCCP ROM)"
            ),
        )
