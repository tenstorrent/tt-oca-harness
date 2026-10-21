# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A SEP_IN core-reset pulse, a core level reset without a drain, and a withheld uncore reset.

Pulses core 1 through `RESET_CTRL.core1_reset_pulse_start` with every level
reset high and requires its `core_resets_done` bit to fall and return. It times
a short pulse at the cluster boundary, requiring `post_reset_count` + 1 cycles
in reset, and pulses core 1 with its level reset held, requiring the core to
stay in reset throughout. With `RESET_TIMEOUT` in give-up mode (mode 0, value
1), it holds core 1's level reset and requires the core's cluster reset to assert
with neither status bit set, since a core reset requests no drain. It then
requests the uncore reset and requires `reset_timeout` to set, and both status
bits to clear on release.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_reset_pulse_test_seq import smc_cpu_reset_pulse_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_reset_pulse_test(smc_base_test):
    """Core-reset pulse and level reset from SEP_IN, and the give-up timeout on the uncore."""

    required_evidence = (
        "CHK-CPU-RST-GIVEUP",
        "CHK-CPU-RST-LEVEL-DIRECT",
        "CHK-CPU-RST-PULSE",
        "CHK-CPU-RST-PULSE-HELD",
        "CHK-CPU-RST-PULSE-WIDTH",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_reset_pulse_test_seq("smc_cpu_reset_pulse_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pulse_seen, "core 1's pulse was not observed"
        assert seq.width_runs is not None, "the pulse-width leg did not run"
        assert seq.held_samples is not None, "the held-level leg did not run"
        assert seq.direct is not None, "the direct level-reset leg did not run"
        assert seq.give_up is not None, "the give-up leg did not run"
