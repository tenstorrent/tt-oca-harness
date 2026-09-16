# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The OCTS system timer counts at the reference clock rate.

Closes the OCTS cell of SMC-CLK-REF.S1 (clk_rst.adoc: The Reference Clock
Domain): TIMER_COUNT is read twice over SEP_IN while the bench counts
clk_ref_i edges independently, and the delta must match the reference-clock
edge count within the OCTS credit granularity; the clk_smc_i edge count over
the same window is shown to fall outside that tolerance. The CLINT mtime cell
is left open because the cluster-local window is unreachable from SEP_IN.

Run:
    CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smc \\
        --items smc_ref_clock_timer_rate_test --tool verilator
"""

from __future__ import annotations

import cocotb
import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_ref_clock_timer_rate_test_seq import smc_ref_clock_timer_rate_test_seq
from smc_base_test import smc_base_test

# CTRL reset read, TIMER_START write, at least one STATUS read, two 64-bit
# count samples of two reads each.
EXPECTED_MIN_ACCESSES = 7


@pyuvm.test()
class smc_ref_clock_timer_rate_test(smc_base_test):
    """OCTS TIMER_COUNT delta against an independent clk_ref_i edge count."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ref_clock_timer_rate_test_seq("ref_clock_timer_rate_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.delta is not None and seq.ref_edges_lo is not None, (
            "the sequence ended without both TIMER_COUNT samples"
        )
        cocotb.log.info(
            "CHK-REF-CLOCK-TIMER-RATE: delta=%d within [%d, %d] (tolerance %d), %d accesses",
            seq.delta,
            seq.ref_edges_lo - seq.tolerance,
            seq.ref_edges_hi + seq.tolerance,
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
                f"OCTS TIMER_COUNT advanced {seq.delta} over {seq.ref_edges_lo}..{seq.ref_edges_hi} "
                f"clk_ref_i edges ({seq.smc_edges_hi} clk_smc_i edges)"
            ),
        )
