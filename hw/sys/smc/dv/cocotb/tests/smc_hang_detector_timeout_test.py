# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Hang-detector stall timeout. Not irq_test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_detector_timeout_test_seq import (
    smc_hang_detector_timeout_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_detector_timeout_test(smc_base_test):
    """SEP outstanding stall → timeout irq; unique vs irq_test sanity."""

    required_evidence = (
        "CHK-HANG-TIMEOUT-AR",
        "CHK-HANG-TIMEOUT-ARM",
        "CHK-HANG-TIMEOUT-BASIC",
        "CHK-HANG-TIMEOUT-DISABLED",
        "CHK-HANG-TIMEOUT-DROP",
        "CHK-HANG-TIMEOUT-FIRE",
        "CHK-HANG-TIMEOUT-STATUS-DROP",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_timeout_test_seq("hang_detector_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.fire_ok and seq.drop_ok and seq.disable_ok, (
            f"hang timeout incomplete fire={seq.fire_ok} "
            f"drop={seq.drop_ok} disable={seq.disable_ok}"
        )
