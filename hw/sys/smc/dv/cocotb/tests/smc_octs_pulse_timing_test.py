# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS pulse widths, credit spacing, START rules, role masks and the pad enable on pads 55/56."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_octs_pulse_timing_test_seq import smc_octs_pulse_timing_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_octs_pulse_timing_test(smc_base_test):
    """Cycle-exact OCTS pulse and credit timing on the pads, with the PRIMARY/SECONDARY masks."""

    required_evidence = (
        "CHK-OCTS-CREDIT-PERIOD",
        "CHK-OCTS-GPIO-ENABLE-PADS",
        "CHK-OCTS-PRIMARY-IGNORES-INPUTS",
        "CHK-OCTS-PULSE-NO-QUEUE",
        "CHK-OCTS-PULSE-WIDTH",
        "CHK-OCTS-SECONDARY-OUTPUTS-QUIET",
        "CHK-OCTS-START-CLEARS-INTERVAL",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_octs_pulse_timing_test_seq("smc_octs_pulse_timing_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
