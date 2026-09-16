# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OTP program command path + shadow verify (behavioral eFuse responder)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_efuse_otp_burn_shadow_test_seq import (
    DIRECTED_ACCESSES,
    smc_efuse_otp_burn_shadow_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_efuse_otp_burn_shadow_test(smc_base_test):
    """Fuse sense + shadow read + PROGRAM command/status through DUT CSRs.

    The burn itself is absorbed by the adopter's `efuse_bank_model`; see the
    sequence docstring for which assertions are model-scored.
    """

    required_evidence = (
        "CHK-EFUSE-OTP-PRELOAD",
        "CHK-EFUSE-OTP-PROGRAM-FAIL",
        "CHK-EFUSE-OTP-PROGRAM-OK",
        "CHK-EFUSE-OTP-SHADOW",
        "CHK-EFUSE-OTP-STATUS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_efuse_otp_burn_shadow_test_seq("efuse_otp_burn_shadow_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.CPU,
            type(self).__name__,
            # Floor over the DIRECTED, timing-independent accesses only: the two
            # PROGRAM_CTRL writes, the shadow-map read and the EFUSE_STATUS read.
            # `seq.accesses` also counts `_wait_program_done` poll iterations,
            # whose number depends on how fast the DUT completes a program, so a
            # floor set at the observed total would trip on a DUT that finished
            # one poll sooner -- moving in the wrong direction with respect to
            # DUT health.
            min_csr_accesses=DIRECTED_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                "eFuse sense + SMC_EFUSE_MAP shadow read + PROGRAM "
                "command/status through DUT CSRs; the OTP array itself is the "
                "adopter efuse_bank_model, so no silicon fuse-burn claim"
            ),
        )
