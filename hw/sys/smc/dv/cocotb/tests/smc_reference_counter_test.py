# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""CPU_CTRL REFERENCE_COUNTER advances at one count per clk_ref_i edge."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reference_counter_test_seq import smc_reference_counter_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reference_counter_test(smc_base_test):
    """64-bit refclk counter rate check; not the OCTS timer."""

    required_evidence = (
        "CHK-REF-COUNT",
        "CHK-REF-COUNT-BASIC",
    )
    min_evidence = 2

    async def run_scenario(self) -> None:
        seq = smc_reference_counter_test_seq("ref_count_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The verdict rests on the measured counter and edge values, independent
        # of any flag the sequence set.
        assert None not in (seq.c0, seq.c1, seq.ref_edges_lo, seq.ref_edges_hi), (
            "REFERENCE_COUNTER samples or the clk_ref_i edge measurement were "
            f"never taken: c0={seq.c0} c1={seq.c1} lo={seq.ref_edges_lo} "
            f"hi={seq.ref_edges_hi}"
        )
        assert seq.ref_edges_lo > 0, (
            f"the clk_ref_i measurement window was empty (lo={seq.ref_edges_lo})"
        )
        assert (
            seq.ref_edges_lo - seq.cdc_skew <= seq.c1 - seq.c0 <= seq.ref_edges_hi + seq.cdc_skew
        ), (
            f"REFERENCE_COUNTER delta {seq.c1 - seq.c0} is outside the measured "
            f"clk_ref_i edge bounds [{seq.ref_edges_lo - seq.cdc_skew}, "
            f"{seq.ref_edges_hi + seq.cdc_skew}] (0x{seq.c0:x} -> 0x{seq.c1:x})"
        )
