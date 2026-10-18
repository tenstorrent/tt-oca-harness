# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SYS_AXI hang detector stalls below, beyond and at the timeout threshold."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_sys_timeout_window_test_seq import smc_hang_sys_timeout_window_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_sys_timeout_window_test(smc_base_test):
    """A 16-rise stall stays quiet; a held stall raises sys irq and raw bit 286."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SYSWIN-AT-LOG",
        "CHK-SYSWIN-BELOW",
        "CHK-SYSWIN-BEYOND",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 5

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_sys_timeout_window_test_seq("hang_sys_timeout_window_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 5, f"phases {seq.phases}, want 5"
        assert seq.accesses >= 19, f"only {seq.accesses} SEP_IN accesses issued, want >= 19"
