# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Reset-pin 32-sample de-glitch threshold.

Contract SMC_RESET_029, anchor smc_reset_pin_deglitch_test.
Scenarios: RST-COLD-RESET.S1, RST-COOL-PIN.S1.
Spec: clk_rst.adoc (Power-Good and Cold Reset), port_table.adoc (SMC Port Declaration).

A 31-sample low pulse on ``rst_cold_ni`` or ``rst_cool_ni`` leaves the stable cold reset and
the primary resets released.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_reset_pin_deglitch_test_seq import (
    COLD_WINDOW_SAMPLES,
    COOL_WINDOW_SAMPLES,
    PULSE_SAMPLES,
    smc_reset_pin_deglitch_test_seq,
)
from smc_base_test import smc_base_test

# Bounded reset WAIT_STATE handshakes of the positive control (asserted, released).
EXPECTED_WAIT_CHECKS = 2


@pyuvm.test()
class smc_reset_pin_deglitch_test(smc_base_test):
    """Sub-threshold pulses on the cold and cool reset pins are ignored."""

    required_evidence = (
        "CHK-COLD-31-IGNORED",
        "CHK-COOL-31-IGNORED",
        "CHK-NONVAC",
    )
    min_evidence = 3

    async def run_scenario(self) -> None:
        seq = smc_reset_pin_deglitch_test_seq("reset_pin_deglitch_seq")
        await self.start_seq(seq, self.env.reset_agent.sequencer)
        assert seq.cold_pulse_samples == PULSE_SAMPLES, seq.cold_pulse_samples
        assert seq.cool_pulse_samples == PULSE_SAMPLES, seq.cool_pulse_samples
        assert seq.cold_checked == COLD_WINDOW_SAMPLES, seq.cold_checked
        assert seq.cool_checked == COOL_WINDOW_SAMPLES, seq.cool_checked
        sb = self.env.scoreboard
        assert sb.reset_wait_checks_seen >= EXPECTED_WAIT_CHECKS, (
            f"scoreboard booked {sb.reset_wait_checks_seen} reset WAIT_STATE checks, expected at "
            f"least {EXPECTED_WAIT_CHECKS}"
        )
