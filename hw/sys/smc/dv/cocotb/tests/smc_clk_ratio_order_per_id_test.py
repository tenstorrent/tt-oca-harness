# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Per-ID SEP_IN response order across the SMC-domain and peripheral paths at 10 / 1.25 / 5 ns.

Contract SMC_CLOCK_RATIO_010, anchor smc_clk_ratio_order_per_id_test.
Allocated scenarios: RATIO-ORDER-PER-ID.S1, RATIO-ORDER-PER-ID.S2, RATIO-ORDER-PER-ID.S3.
Spec sources: hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/fabric.adoc.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_clk_ratio_order_per_id_test_seq import smc_clk_ratio_order_per_id_test_seq
from smc_base_test import smc_base_test

REQUIRED = (
    "CHK-ORDER-READS-SAME-ID",
    "CHK-ORDER-WRITES-SAME-ID",
    "CHK-ORDER-DIFFERENT-IDS",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


@pyuvm.test()
class smc_clk_ratio_order_per_id_test(smc_base_test):
    """Same-ID read and write groups and a four-ID read group over both domains."""

    required_evidence = REQUIRED
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_clk_ratio_order_per_id_test_seq("clk_ratio_order_per_id_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = [n for n in REQUIRED if n != "CHK-NONVAC" and n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
