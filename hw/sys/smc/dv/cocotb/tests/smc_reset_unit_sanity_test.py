# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""COLD vs COLD_WARM across SEP WDT."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reset_unit_sanity_test_seq import smc_reset_unit_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reset_unit_sanity_test(smc_base_test):
    """COLD scratch persists a SEP WDT pulse; COLD_WARM does not."""

    required_evidence = (
        "CHK-RESET-UNIT-PRE",
        "CHK-RESET-UNIT-SS-SWEEP",
        "CHK-RESET-UNIT-WDT",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reset_unit_sanity_test_seq("reset_unit_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # The scratch and SS_* readback verdicts, `_await_warm_cleared`'s bounded
        # poll and the CSR-to-pin comparison against `tb_isolate_req_o` are
        # enforced inside the sequence; this assert only catches a sequence body
        # that issued no register sweep.
        assert seq.ss_regs_swept, (
            "the RESET_UNIT SS_* write/readback sweep issued no stimulus in this run"
        )
