# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FLR cool overlapped with rst_cold_ni; cold wins."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cool_reset_x_cold_reset_test_seq import (
    smc_cool_reset_x_cold_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cool_reset_x_cold_reset_test(smc_base_test):
    """FLR×cold interaction; not rst_cool_ni alias or BMC Force cool."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cool_reset_x_cold_reset_test_seq("flr_x_cold_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.pos_ok and seq.wins_ok, (
            f"FLR×cold incomplete pos={seq.pos_ok} wins={seq.wins_ok}"
        )
