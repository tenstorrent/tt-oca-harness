# SPDX-License-Identifier: Apache-2.0
"""Hang-detector IRQ enable/clear. No CPU firmware."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_hang_detector_sanity_test_seq import smc_hang_detector_sanity_test_seq


@pyuvm.test()
class smc_hang_detector_sanity_test(smc_base_test):
    """irq_test fire/clear on sys/sep/data hang detectors + OR."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_sanity_test_seq("hang_detector_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.poison_ok and seq.per_source_ok and seq.or_ok, (
            f"hang detector incomplete poison={seq.poison_ok} "
            f"per_source={seq.per_source_ok} or={seq.or_ok}"
        )
