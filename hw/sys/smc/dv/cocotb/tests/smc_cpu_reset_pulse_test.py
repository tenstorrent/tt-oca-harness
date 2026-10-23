# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_004 ANCHOR: smc_cpu_reset_pulse_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: 426814cd968fdd57c286773e76b962b2f0bf891ec8032cdee33428793e4c7cd4
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 262 `smc_cpu_reset_pulse_test` ENV: cocotb
"""SEP_IN core-reset pulses and level resets, the uncore give-up, the debug reset and vectors.

Pulses core 1 through `RESET_CTRL.core1_reset_pulse_start` with every level
reset high and requires its `core_resets_done` bit to fall and return. It times
a short pulse at the cluster boundary, requiring `post_reset_count` + 1 cycles
in reset, and pulses core 1 with its level reset held, requiring the core to
stay in reset throughout. With `RESET_TIMEOUT` in give-up mode (mode 0, value
1), it holds core 1's level reset and requires the core's cluster reset to assert
with neither status bit set, since a core reset requests no drain. It then
requests the uncore reset and requires `reset_timeout` to set, and both status
bits to clear on release.

Checks the reset values of `RESET_CTRL` and `RESET_VECTOR[1..3]` before any
write, pulses cores 0, 2 and 3 with the reset pulse counts, holds cores 2 and
3 in level reset and releases them, releases and re-asserts `debug_reset_n`,
and sets and clears bit 17 of each of `RESET_VECTOR[1..3]`.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_reset_pulse_test_seq import smc_cpu_reset_pulse_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_reset_pulse_test(smc_base_test):
    """Core-reset pulses and level resets from SEP_IN, the give-up timeout on the uncore,
    the debug reset, and the RESET_VECTOR reset value and storage."""

    required_evidence = (
        "CHK-CPU-DBG-RST-REASSERT",
        "CHK-CPU-RST-GIVEUP",
        "CHK-CPU-RST-LEVEL-CORES",
        "CHK-CPU-RST-LEVEL-DIRECT",
        "CHK-CPU-RST-PULSE",
        "CHK-CPU-RST-PULSE-CORES",
        "CHK-CPU-RST-PULSE-HELD",
        "CHK-CPU-RST-PULSE-WIDTH",
        "CHK-CPU-RST-VECTOR-BIT17",
        "CHK-CPU-RST-VECTOR-RESET",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 12

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_reset_pulse_test_seq("smc_cpu_reset_pulse_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pulse_seen, "core 1's pulse was not observed"
        assert seq.width_runs is not None, "the pulse-width leg did not run"
        assert seq.held_samples is not None, "the held-level leg did not run"
        assert seq.direct is not None, "the direct level-reset leg did not run"
        assert seq.give_up is not None, "the give-up leg did not run"
        assert sorted(seq.pulse_cores) == [0, 2, 3], "the core 0/2/3 pulse legs did not all run"
        assert sorted(seq.level_cores) == [2, 3], "the core 2/3 level legs did not all run"
        assert len(seq.fence) == 6, "the ordered fence did not record every term"
