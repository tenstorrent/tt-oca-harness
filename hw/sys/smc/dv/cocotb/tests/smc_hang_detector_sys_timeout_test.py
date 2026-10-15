# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS hang-detector stall timeout. Not SEP or irq_test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_detector_sys_timeout_test_seq import (
    smc_hang_detector_sys_timeout_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_detector_sys_timeout_test(smc_base_test):
    """SYS_IN outstanding stall → timeout irq; unique vs SEP timeout."""

    required_evidence = (
        "CHK-HANG-SYS-TIMEOUT-AR",
        "CHK-HANG-SYS-TIMEOUT-ARM",
        "CHK-HANG-SYS-TIMEOUT-BASIC",
        "CHK-HANG-SYS-TIMEOUT-DISABLED",
        "CHK-HANG-SYS-TIMEOUT-DROP",
        "CHK-HANG-SYS-TIMEOUT-FIRE",
        "CHK-HANG-SYS-TIMEOUT-STATUS-DROP",
        "CHK-HANG-SYS-TIMEOUT-STATUS-FIRE",
    )
    min_evidence = 8

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_sys_timeout_test_seq("hang_detector_sys_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.fire_ok and seq.drop_ok and seq.disable_ok, (
            f"SYS hang timeout incomplete fire={seq.fire_ok} "
            f"drop={seq.drop_ok} disable={seq.disable_ok}"
        )
