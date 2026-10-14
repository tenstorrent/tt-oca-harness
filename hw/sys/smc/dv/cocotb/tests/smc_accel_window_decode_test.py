# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""DMA and zeroer register window decode: aliasing, boundary, neighbours, REGION_SIZE."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_accel_window_decode_test_seq import smc_accel_window_decode_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_accel_window_decode_test(smc_base_test):
    """Drive both accelerator register windows and their neighbours from SEP_IN."""

    required_evidence = (
        "CHK-ACCEL-WIN-DECERR-NEIGHBOURS",
        "CHK-ACCEL-WIN-FIRST-LAST",
        "CHK-ACCEL-WIN-HOLES",
        "CHK-ACCEL-WIN-NO-ALIAS",
        "CHK-ACCEL-WIN-REGION-SIZE",
        "CHK-ACCEL-WIN-RO-WRITES",
        "CHK-NONVAC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_accel_window_decode_test_seq("smc_accel_window_decode_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
