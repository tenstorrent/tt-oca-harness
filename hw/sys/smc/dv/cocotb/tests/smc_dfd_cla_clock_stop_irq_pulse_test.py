# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Raw interrupt bit 320 pulses once per rise of the held CLA clock-stop output.

With `tdr_dbg_ctrl_clock_stop_en_i` driven high, the halt-clock action raises
the clock-stop output and bit 320 is high for one `clk_smc_i` sample; PLIC
source 321 is claimed once and does not pend again while the output is held,
and an enable 0 -> 1 gives exactly one more pulse.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_dfd_cla_clock_stop_irq_pulse_test_seq import (
    smc_dfd_cla_clock_stop_irq_pulse_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_dfd_cla_clock_stop_irq_pulse_test(smc_base_test):
    """Fire the clock-halt action with the enable set; grade bit 320 and PLIC source 321."""

    required_evidence = (
        "CHK-CLA-CLKSTOP-IRQ-NO-REPEND",
        "CHK-CLA-CLKSTOP-IRQ-PULSE",
        "CHK-CLA-CLKSTOP-IRQ-REARM",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dfd_cla_clock_stop_irq_pulse_test_seq("smc_dfd_cla_clock_stop_irq_pulse_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
