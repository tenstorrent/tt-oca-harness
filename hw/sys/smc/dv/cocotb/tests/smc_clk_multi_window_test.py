# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""
DV-CARD: SMC_CLK_MULTI_WINDOW_TEST ANCHOR: smc_clk_multi_window_test
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_clk_multi_window_test_seq import smc_clk_multi_window_test_seq
from smc_base_test import smc_base_test

# Fail-capable stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
# Composition (smc_clk_multi_window_test_seq): 6 output-fabric pass-all filter
# CSR writes + 2 JTAG-AXI payload write groups + 8 measured hysteresis windows
# (3 required + 5 seeded extras), each programming CLOCK_GATE_CONTROL and the
# DMA descriptor and then polling DMA_CTRL_DONE. The DONE poll length scales with
# the programmed hysteresis, so the floor sits below the smallest count any seed
# produces.
CLK_MULTI_WINDOW_MIN_CSR_ACCESSES = 130


@pyuvm.test()
class smc_clk_multi_window_test(smc_base_test):
    """LIVE hysteresis-window scaling."""

    required_evidence = (
        "CHK-DMA-PAYLOAD-GOLDEN",
        "CHK-HYST-WINDOW",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 4

    auto_protocol_vip = False
    protocol_vip_kind = SmcProtocolVipKind.ZEROER_DMA

    async def run_scenario(self) -> None:
        seq = smc_clk_multi_window_test_seq("clk_multi_window_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        required = ("CHK-HYST-WINDOW", "CHK-NONVAC", "CHK-TIMEOUT-PATHS")
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=CLK_MULTI_WINDOW_MIN_CSR_ACCESSES,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                "MULTI_WINDOW LIVE: hyst min/mid/max "
                f"measured={seq.measured} cells={seq.required_cells_hit}"
            ),
        )
