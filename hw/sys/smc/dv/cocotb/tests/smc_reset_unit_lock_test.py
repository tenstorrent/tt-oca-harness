# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B1_002 ANCHOR: smc_reset_unit_lock_test
# DV-TESTCASE-CONTRACT-REVISION: 2 RECORD-SHA256: fa06dde2cd49fa2cc3d83376836d9db41e2116779d281dd7e2206650424dd4c7
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B1_VPLAN_DETAIL.md @ artifact_revision 5 ENV: cocotb
"""The reset unit's two RW1S locks: 32-bit accumulation, masking, primary-reset clear.

Covers `SS_CONFIG_LOCK` / `SS_CONFIG` and `SS_COLD_RESET_LOCK` /
`SS_COLD_RESET_N` over SEP_IN AXI, which reaches the reset unit without a
firmware image, and the cool-reset pin for the primary-reset leg. One sequence
covers both pairs because the register documentation declares them alike, so a
second testcase would differ only in four addresses.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reset_unit_lock_test_seq import (
    FENCE_TERMS,
    LOCK_PAIRS,
    smc_reset_unit_lock_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reset_unit_lock_test(smc_base_test):
    """Each RW1S lock accumulates, masks its target both ways, and clears on cool reset."""

    required_evidence = (
        "CHK-LOCK-COLD-MASKED-RESP",
        "CHK-LOCK-COLD-MASKS",
        "CHK-LOCK-COLD-PRIMARY-RESET",
        "CHK-LOCK-COLD-UNLOCKED",
        "CHK-LOCK-COLD-W1S",
        "CHK-LOCK-CONFIG-MASKED-RESP",
        "CHK-LOCK-CONFIG-MASKS",
        "CHK-LOCK-CONFIG-PRIMARY-RESET",
        "CHK-LOCK-CONFIG-UNLOCKED",
        "CHK-LOCK-CONFIG-W1S",
        "CHK-NONVAC",
        "CHK-RESET-LOCK-ARM",
        "CHK-RESET-LOCK-MASKS-WRITE",
        "CHK-RESET-LOCK-WOSET",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 15

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reset_unit_lock_test_seq("reset_unit_lock_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Each leg raises on failure and emits its token only after its compares
        # passed; the tokens are required per LOCK_PAIRS entry.
        required = ["CHK-NONVAC", "CHK-TIMEOUT-PATHS"] + [
            tok
            for label, _, _, _ in LOCK_PAIRS
            for tok in (
                f"CHK-RESET-LOCK-ARM[{label}]",
                f"CHK-RESET-LOCK-WOSET[{label}]",
                f"CHK-RESET-LOCK-MASKS-WRITE[{label}]",
                f"CHK-LOCK-{label}-UNLOCKED",
                f"CHK-LOCK-{label}-W1S",
                f"CHK-LOCK-{label}-MASKS",
                f"CHK-LOCK-{label}-MASKED-RESP",
                f"CHK-LOCK-{label}-PRIMARY-RESET",
            )
        ]
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
        assert tuple(t for t, _, _ in seq.fence) == FENCE_TERMS, (
            f"the lock legs completed fence terms {seq.fence}, want {FENCE_TERMS}"
        )
