# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The reset unit's two woset locks: write-one-to-set, and they mask their target.

Covers `SS_COLD_RESET_LOCK` and `SS_CONFIG_LOCK` over SEP_IN AXI, which reaches
the reset unit without a firmware image. One sequence
covers both because the two registers have the same declaration and the same
gate in `smc_subsystem_resets.sv`, so a second testcase would differ only in
two addresses.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reset_unit_lock_test_seq import LOCK_PAIRS, smc_reset_unit_lock_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_reset_unit_lock_test(smc_base_test):
    """Each woset lock sets once and gates the register it guards."""

    required_evidence = (
        "CHK-RESET-LOCK-ARM",
        "CHK-RESET-LOCK-MASKS-WRITE",
        "CHK-RESET-LOCK-WOSET",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_reset_unit_lock_test_seq("reset_unit_lock_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the emitted tokens rather than on a boolean the sequence set:
        # each leg raises on failure, so a relayed flag could only ever report
        # that the line was reached. Required per pair, so a pair silently
        # dropped from LOCK_PAIRS fails here instead of shrinking the test.
        required = [
            f"{tok}[{label}]"
            for label, _, _, _ in LOCK_PAIRS
            for tok in (
                "CHK-RESET-LOCK-ARM",
                "CHK-RESET-LOCK-WOSET",
                "CHK-RESET-LOCK-MASKS-WRITE",
            )
        ]
        missing = [n for n in required if n not in seq.chk_seen]
        assert not missing, f"missing CHK evidence tokens: {missing}"
