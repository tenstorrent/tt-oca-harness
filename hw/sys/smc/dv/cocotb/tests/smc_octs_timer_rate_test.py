# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OCTS system timer counts at the clk_smc_i rate.

clk_rst.adoc (Timer and Debug Timebases) states "OCTS uses clk_smc_i":
TIMER_COUNT is read twice over SEP_IN while the bench counts clk_smc_i edges
independently, and the delta must match the clk_smc_i edge count within the
OCTS credit granularity; the clk_ref_i edge count over the same window must
fall outside that bracket. The CLINT mtime cell is left open because the
cluster-local window is unreachable from SEP_IN.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_octs_timer_rate_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_octs_timer_rate_test_seq import smc_octs_timer_rate_test_seq
from smc_base_test import smc_base_test

# CTRL reset read, TIMER_START write, at least one STATUS read, two 64-bit
# count samples of two reads each.
EXPECTED_MIN_ACCESSES = 7


@pyuvm.test()
class smc_octs_timer_rate_test(smc_base_test):
    """OCTS TIMER_COUNT delta against an independent clk_smc_i edge count."""

    required_evidence = (
        "CHK-CLINT-TICK-NOT-CLOSED",
        "CHK-OCTS-TICK-ON-CLK-SMC",
        "CHK-OCTS-TIMER-RATE",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_octs_timer_rate_test_seq("octs_timer_rate_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.delta is not None and seq.smc_edges_lo is not None, (
            "the sequence ended without both TIMER_COUNT samples"
        )
        cocotb.log.info(
            "CHK-OCTS-TIMER-RATE: delta=%d within [%d, %d] (tolerance %d), %d accesses",
            seq.delta,
            seq.smc_edges_lo - seq.tolerance,
            seq.smc_edges_hi + seq.tolerance,
            seq.tolerance,
            seq.accesses,
        )
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            csr_accesses=seq.accesses,
            min_csr_accesses=EXPECTED_MIN_ACCESSES,
            proxy=False,
            details=(
                f"OCTS TIMER_COUNT advanced {seq.delta} over {seq.smc_edges_lo}..{seq.smc_edges_hi} "
                f"clk_smc_i edges ({seq.ref_edges_hi} clk_ref_i edges)"
            ),
        )
