# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMC OSS OCTS dual-chiplet sync test (U4-5)."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_octs_dual_sync_test_seq import smc_octs_dual_sync_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_octs_dual_sync_test(smc_base_test):
    """U4-5: SECONDARY start ignored and pad inject + PRIMARY start and sync/credit pad edges."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-OCTS-DUAL-SYNC",
        "CHK-OCTS-PRI-START",
        "CHK-OCTS-SEC-MODE",
        "CHK-OCTS-SEC-START-IGNORED",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_octs_dual_sync_test_seq("octs_dual_sync_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            csr_accesses=0,
            # With no CSR traffic and no byte golden, this record is an activity
            # stamp in the scoreboard's protocol_vip_auto bin; the OCTS pad-edge
            # asserts in the sequence carry the verdict.
            auto_evidence=True,
            proxy=False,
            details=(
                "OCTS dual-chiplet: secondary sync-then-credit COUNT + "
                "primary pad55/56 rising-edge hard-gates"
            ),
        )
