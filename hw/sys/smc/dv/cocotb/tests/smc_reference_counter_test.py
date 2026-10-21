# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_003 ANCHOR: smc_reference_counter_test
# DV-TESTCASE-CONTRACT-REVISION: 3 RECORD-SHA256: 31bb60a38828f335ba0f376099bb58de13c3ac556b44ca2cedc2e5e850f347fa
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 6 ENV: cocotb
"""CPU_CTRL REFERENCE_COUNTER rate, and its write-load and poll-until-reflected protocol."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reference_counter_test_seq import (
    FENCE_TERMS,
    smc_reference_counter_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reference_counter_test(smc_base_test):
    """64-bit refclk counter rate check and V1..V8 load legs; not the OCTS timer."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-REF-COUNT",
        "CHK-REF-COUNT-BASIC",
        "CHK-REFCNT-LOAD",
        "CHK-REFCNT-MONOTONIC",
        "CHK-REFCNT-RELOAD",
        "CHK-REFCNT-UPPER-HALF",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

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
        assert tuple(t for t, _, _ in seq.fence) == FENCE_TERMS, (
            f"the load legs completed fence terms {seq.fence}, want {FENCE_TERMS}"
        )
