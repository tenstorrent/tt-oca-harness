# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMCCGP0_001 ANCHOR: smc_clk_running_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_clk_running_test_seq import smc_clk_running_test_seq
from smc_base_test import smc_base_test

# Fail-capable stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
# Composition (smc_clk_running_test_seq): 6 output-fabric pass-all filter CSR
# writes + 2 JTAG-AXI payload write groups + the CG-enable program/readback pair
# + the DMA descriptor programming and trigger. The DMA-DONE completion poll adds
# a seed-dependent number of reads, so the floor sits below the smallest count
# any seed produces.
CLK_RUNNING_MIN_CSR_ACCESSES = 20


@pyuvm.test()
class smc_clk_running_test(smc_base_test):
    """P0 bring-up LIVE CG enable / idle gate / DMA ungate."""

    required_evidence = (
        "CHK-ACTIVE-RUNNING",
        "CHK-CG-ENABLE-READBACK",
        "CHK-DMA-ACTIVITY-UNGATE",
        "CHK-DMA-PAYLOAD-GOLDEN",
        "CHK-IDLE-GATED-BASELINE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_clk_running_test_seq("clk_running_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = (
            "CHK-CG-ENABLE-READBACK",
            "CHK-IDLE-GATED-BASELINE",
            "CHK-DMA-ACTIVITY-UNGATE",
            "CHK-TIMEOUT-PATHS",
            "CHK-NONVAC",
            # P1 alias token (see smc_clk_running_test_seq).
            "CHK-ACTIVE-RUNNING",
        )
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLK_RUNNING_MIN_CSR_ACCESSES,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "CLK_RUNNING P0 LIVE: CG-enable / idle-gated / DMA-ungate "
                f"evidence emitted (fence={seq.fence})"
            ),
        )
