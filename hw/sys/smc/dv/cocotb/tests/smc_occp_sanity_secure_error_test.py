# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCCP secure-error test without the boot ROM: OTP program-fail and eFuse signature gates.

Drives both through the behavioral eFuse responder on the SMC wrapper bench.
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
    """An OTP program failure is flagged; a recovery burn and a signature read then pass."""

    required_evidence = ("CHK-OCCP-SECURE-ERROR-RECOVERY",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_occp_sanity_secure_error_test_seq("occp_secure_error_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # A fixed floor: deriving it from seq.accesses would make the check always pass.
            min_csr_accesses=8,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "OTP program-fail + EFUSE_MAP signature gate "
                "(OSS public secure-error; not full OCCP ROM)"
            ),
        )
