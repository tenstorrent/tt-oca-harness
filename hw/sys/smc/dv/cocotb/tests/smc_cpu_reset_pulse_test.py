# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A SEP_IN core-reset pulse, and a withheld level reset under give-up timeout mode.

Pulses core 1 through `RESET_CTRL.core1_reset_pulse_start` with every level
reset high and requires its `core_resets_done` bit to fall and return. It times
a short pulse at the cluster boundary, requiring `post_reset_count` + 1 cycles
in reset, and pulses core 1 with its level reset held, requiring the core to
stay in reset throughout. Then it
requests core 1's level reset with `RESET_TIMEOUT` in give-up mode (mode 0,
value 1), and requires that a timed-out request is not applied, and that both
status bits clear on release.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_reset_pulse_test_seq import smc_cpu_reset_pulse_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_reset_pulse_test(smc_base_test):
    """Core-reset pulse from SEP_IN, and the give-up timeout on a withheld reset."""

    required_evidence = (
        "CHK-CPU-RST-GIVEUP",
        "CHK-CPU-RST-PULSE",
        "CHK-CPU-RST-PULSE-HELD",
        "CHK-CPU-RST-PULSE-WIDTH",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_reset_pulse_test_seq("smc_cpu_reset_pulse_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pulse_seen, "core 1's pulse was not observed"
        assert seq.width_runs is not None, "the pulse-width leg did not run"
        assert seq.held_samples is not None, "the held-level leg did not run"
        assert seq.give_up is not None, "the give-up leg did not run"
