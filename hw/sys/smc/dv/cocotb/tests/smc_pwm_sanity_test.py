# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_pwm_sanity_test: PWM register reset, read/write, strobe, REGWEN lock and decoded extent."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_pwm_sanity_test_seq import smc_pwm_sanity_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pwm_sanity_test(smc_base_test):
    """Drive the PWM registers over SEP_IN."""

    required_evidence = (
        "CHK-PWM-PAST-END",
        "CHK-PWM-REGWEN",
        "CHK-PWM-RESET",
        "CHK-PWM-RW",
        "CHK-PWM-STROBE",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_pwm_sanity_test_seq("pwm_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
