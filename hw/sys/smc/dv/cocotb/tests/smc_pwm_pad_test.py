# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_pwm_pad_test: PWM channels claim GPIO pads 59-62 through PWM_CTRL.CTRL.PAD_EN."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_pwm_pad_test_seq import CHK_ORDER, smc_pwm_pad_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_pwm_pad_test(smc_base_test):
    """Claim, idle level, software veto and release of the PWM pads, and the cool-reset
    pads at 63 and 64."""

    required_evidence = tuple(sorted(CHK_ORDER))
    min_evidence = len(CHK_ORDER)

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_pwm_pad_test_seq("pwm_pad_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        missing = set(CHK_ORDER) - set(seq.chk_seen)
        assert not missing, f"missing CHK tokens {sorted(missing)} (seen={seq.chk_seen})"
