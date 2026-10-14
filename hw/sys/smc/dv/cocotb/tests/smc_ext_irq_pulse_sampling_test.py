# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Wide and sub-period pulses on ext_interrupts_i[0] and edge latency to raw bit 0."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_ext_irq_pulse_sampling_test_seq import smc_ext_irq_pulse_sampling_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_ext_irq_pulse_sampling_test(smc_base_test):
    """Pin pulses of controlled width and phase against tb_cpu_interrupts[0]."""

    required_evidence = (
        "CHK-EXTPULSE-LATENCY-LOG",
        "CHK-EXTPULSE-SHORT-NOLATCH",
        "CHK-EXTPULSE-SHORT-SEEN-LOG",
        "CHK-EXTPULSE-WIDE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_ext_irq_pulse_sampling_test_seq("ext_irq_pulse_sampling_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.wide_runs == 12 and seq.short_runs == 12 and seq.latency_runs == 8, (
            f"runs wide={seq.wide_runs} short={seq.short_runs} latency={seq.latency_runs}"
        )
        assert seq.accesses >= 1, f"only {seq.accesses} SEP_IN accesses issued, want >= 1"
