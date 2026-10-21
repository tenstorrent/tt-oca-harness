# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_001 ANCHOR: smc_reset_unit_sanity_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: dd3cf193bce9ad8497ee7adbb9b5ae0703670f9e3f6d135e2a71b06e927db8de
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 5 ENV: cocotb
"""COLD vs COLD_WARM across SEP WDT, and reset-unit software-owned storage."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reset_unit_sanity_test_seq import (
    FENCE_TERMS,
    smc_reset_unit_sanity_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reset_unit_sanity_test(smc_base_test):
    """COLD scratch persists a SEP WDT pulse; COLD_WARM does not; storage legs."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-RESET-UNIT-PRE",
        "CHK-RESET-UNIT-SS-SWEEP",
        "CHK-RESET-UNIT-WDT",
        "CHK-RU-FLR-B2B",
        "CHK-RU-FLR-COOL-RETAIN",
        "CHK-RU-FLR-STORAGE",
        "CHK-RU-FORCE-STORAGE",
        "CHK-RU-HOLD-ISOLATION",
        "CHK-RU-HOLD-PATTERN",
        "CHK-RU-HOLD-RESET",
        "CHK-RU-ISOLATE-COOL-RETAIN",
        "CHK-RU-ISOLATE-STORAGE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 14

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
        assert tuple(t for t, _, _ in seq.fence) == FENCE_TERMS, (
            f"the storage legs completed fence terms {seq.fence}, want {FENCE_TERMS}"
        )
