# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_002 ANCHOR: smc_static_cg_sanity_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_static_cg_sanity_test_seq import smc_static_cg_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_static_cg_sanity_test(smc_base_test):
    """P0 bring-up LIVE gate-disabled free-run (+ legacy P1 threshold)."""

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_static_cg_sanity_test_seq("static_cg_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = (
            "CHK-DMA-GATE-DISABLED-FREE-RUN",
            "CHK-ZEROER-GATE-DISABLED-FREE-RUN",
            "CHK-NONVAC",
            # Legacy P1 tokens retained for closed P1 grade compatibility.
            "CHK-MODULE-GATING",
            "CHK-ENABLE-THRESHOLD",
            "CHK-TIMEOUT-PATHS",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                f"STATIC_CG P0+P1 LIVE: measured={seq.measured} cells={seq.required_cells_hit}"
            ),
        )
