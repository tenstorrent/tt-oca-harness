# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DATA hang-detector stall timeout. Not SEP, SYS, or irq_test."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_detector_data_timeout_test_seq import (
    smc_hang_detector_data_timeout_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_detector_data_timeout_test(smc_base_test):
    """DATA_ACCEL outstanding stall → timeout irq; unique vs SEP/SYS timeout."""

    required_evidence = (
        "CHK-HANG-DATA-TIMEOUT-ACCEPT",
        "CHK-HANG-DATA-TIMEOUT-ARM",
        "CHK-HANG-DATA-TIMEOUT-BASIC",
        "CHK-HANG-DATA-TIMEOUT-DISABLED",
        "CHK-HANG-DATA-TIMEOUT-DROP",
        "CHK-HANG-DATA-TIMEOUT-FIRE",
        "CHK-HANG-DATA-TIMEOUT-SEP-POS",
        "CHK-HANG-DATA-TIMEOUT-STATUS-DROP",
        "CHK-HANG-DATA-TIMEOUT-STATUS-FIRE",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_detector_data_timeout_test_seq("hang_detector_data_timeout_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.fire_ok and seq.drop_ok and seq.disable_ok, (
            f"DATA hang timeout incomplete fire={seq.fire_ok} "
            f"drop={seq.drop_ok} disable={seq.disable_ok}"
        )
