# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A RESET_TIMEOUT timeout_value of zero disables the drain timer.

Sources: cpu.adoc; the sentences are quoted in `seq_lib/smc_cpu_reset_timeout_zero_test_seq.py`.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_reset_timeout_zero_test_seq import (
    DISABLED_SAMPLES,
    smc_cpu_reset_timeout_zero_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_reset_timeout_zero_test(smc_base_test):
    """Hold an L2 read drain with the timer at zero, then re-arm it."""

    required_evidence = (
        "CHK-RESET-TIMEOUT-REARMS",
        "CHK-RESET-TIMEOUT-ZERO-DISABLED",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_reset_timeout_zero_test_seq("smc_cpu_reset_timeout_zero_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.disabled_samples == DISABLED_SAMPLES and seq.rearm_fired_after is not None, (
            f"disabled window {seq.disabled_samples} samples, re-arm fired after "
            f"{seq.rearm_fired_after}"
        )
