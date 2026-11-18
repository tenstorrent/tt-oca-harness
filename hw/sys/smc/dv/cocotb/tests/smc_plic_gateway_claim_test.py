# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PLIC gateway: one request in flight, re-pend after completion, sticky status untouched."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_plic_gateway_claim_test_seq import smc_plic_gateway_claim_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_plic_gateway_claim_test(smc_base_test):
    """Claim and complete on context 0 around input 0 pulses and a sticky mailbox status."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-PLIC-GATEWAY-ONE-IN-FLIGHT",
        "CHK-PLIC-REPEND-AFTER-COMPLETE",
        "CHK-PLIC-STICKY-STATUS",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_plic_gateway_claim_test_seq("plic_gateway_claim_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
