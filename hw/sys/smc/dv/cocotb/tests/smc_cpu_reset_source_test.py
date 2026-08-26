# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SW RESET_CTRL.core0 to RESET_TIMEOUT.reset_applied."""

from __future__ import annotations

import pyuvm
from smc_base_test import smc_base_test
from seq_lib.smc_cpu_reset_source_test_seq import smc_cpu_reset_source_test_seq


@pyuvm.test()
class smc_cpu_reset_source_test(smc_base_test):
    """SW core0 level reset; no Force drain / no FLR isolate_req_o."""

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_reset_source_test_seq("cpu_rst_src_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.idle_ok and seq.assert_ok and seq.release_ok, (
            f"cpu reset-source incomplete idle={seq.idle_ok} "
            f"assert={seq.assert_ok} rel={seq.release_ok}"
        )
