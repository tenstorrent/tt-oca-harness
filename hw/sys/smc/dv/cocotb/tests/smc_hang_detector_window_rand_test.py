# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded hang-detector threshold, hold and enable passes over the three detector ports."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_detector_window_rand_test_seq import smc_hang_detector_window_rand_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_detector_window_rand_test(smc_base_test):
    """Drawn port, threshold and hold: short holds stay quiet, long holds fire and drop."""

    required_evidence = (
        "CHK-HDW-BELOW",
        "CHK-HDW-DISABLE",
        "CHK-HDW-DROP",
        "CHK-HDW-FIRES",
        "CHK-HDW-OR",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_window_rand_test_seq(
            "smc_hang_detector_window_rand_test_seq", seed=self.random_seed()
        )
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.done, "hang detector window sequence did not complete"
