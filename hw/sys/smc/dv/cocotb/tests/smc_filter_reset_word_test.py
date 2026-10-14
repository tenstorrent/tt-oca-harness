# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Filter, alias remap and output remap reset words; a cold reset clears `locked`."""

from __future__ import annotations

import pyuvm
from seq_lib._one_shot import _OneShot
from seq_lib.smc_filter_reset_word_test_seq import smc_filter_reset_word_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_filter_reset_word_test(smc_base_test):
    """Read reset words, program non-reset values, cold reset, read them back."""

    required_evidence = (
        "CHK-LOCK-WRITABLE-AFTER-RESET",
        "CHK-NONVAC",
        "CHK-RESET-ALIAS-REMAP",
        "CHK-RESET-CLEARS-LOCK",
        "CHK-RESET-FILTER-PROGRAMMED",
        "CHK-RESET-OUTPUT-REMAP",
        "CHK-RESET-WORD-INBOUND",
        "CHK-RESET-WORD-OUTBOUND",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_filter_reset_word_test_seq("filter_reset_word_seq")

        async def dispatch_reset(item):
            await _OneShot(item, "reset_os").start(self.env.reset_agent.sequencer)

        seq.dispatch_reset = dispatch_reset
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses >= 82, f"only {seq.accesses} SEP_IN accesses issued, want >= 82"
