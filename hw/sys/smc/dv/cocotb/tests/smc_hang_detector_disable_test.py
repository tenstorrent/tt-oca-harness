# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang detector enable cleared while fired, and irq_test with enable clear."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_detector_disable_test_seq import smc_hang_detector_disable_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_detector_disable_test(smc_base_test):
    """Disable a fired SEP detector mid-stall, and drive irq_test with enable clear."""

    required_evidence = (
        "CHK-HANG-DISABLE-FIRED",
        "CHK-HANG-TEST-GATED",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_disable_test_seq("hang_detector_disable_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.disabled_drop and seq.test_gated
