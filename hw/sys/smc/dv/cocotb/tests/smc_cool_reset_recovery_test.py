# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset-unit CSR and reset-output recovery after a colliding cool reset; the FLR latch."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_cool_reset_recovery_test_seq import smc_cool_reset_recovery_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor: S1 stages seven registers and reads them back, S3 reads twelve words,
# S4 and S5 read and write the latch and the hold counter.
COOL_RESET_RECOVERY_MIN_CSR_ACCESSES = 30


@pyuvm.test()
class smc_cool_reset_recovery_test(smc_base_test):
    """Primary-reset registers recover, cold-reset registers retain, and the FLR latch sets."""

    required_evidence = (
        "CHK-COOLRST-COLD-STAYS",
        "CHK-COOLRST-CSR-RECOVERY",
        "CHK-COOLRST-ISOLATE-VIS",
        "CHK-COOLRST-LATCH-CLEAR",
        "CHK-COOLRST-LATCH-HOLD0",
        "CHK-COOLRST-LATCH-SET-HOLD",
        "CHK-COOLRST-OTHER-CSR-MEASURED",
        "CHK-COOLRST-PRIMARY-RELEASE",
        "CHK-COOLRST-RESET-VECTOR",
        "CHK-COOLRST-WARM-FOLLOWS",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cool_reset_recovery_test_seq("smc_cool_reset_recovery_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.recovery_ok, "cool reset recovery scenario failed"
        await self.record_protocol_vip(
            SmcProtocolVipKind.CSR,
            type(self).__name__,
            min_csr_accesses=COOL_RESET_RECOVERY_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details="cool reset recovery and FLR isolation latch",
        )
