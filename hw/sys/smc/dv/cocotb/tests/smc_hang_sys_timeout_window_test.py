# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_006 ANCHOR: smc_hang_sys_timeout_window_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: df1683f6c28194c2a230844b8f7f49d7d59852e82dc25fe24a3d9ac47dea2f87
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/ai/dv_vplan_gen/SMC_COV_B4_VPLAN_DETAIL.md @ artifact_revision 2 ENV: cocotb
"""SYS_AXI hang detector stalls below, beyond and at the timeout threshold, then CTRL gating."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_sys_timeout_window_test_seq import smc_hang_sys_timeout_window_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_sys_timeout_window_test(smc_base_test):
    """A 16-rise stall stays quiet; a held stall raises sys irq and raw bit 286; enable,
    irq_en and irq_test gate the interrupt."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-SYSWIN-AT-LOG",
        "CHK-SYSWIN-BELOW",
        "CHK-SYSWIN-BEYOND",
        "CHK-SYSWIN-DISABLE-AFTER-TIMEOUT",
        "CHK-SYSWIN-IRQEN-CLEAR",
        "CHK-SYSWIN-IRQTEST-DISABLED",
        "CHK-SYSWIN-IRQTEST-NOIRQEN",
        "CHK-SYSWIN-IRQTEST-RAISE",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_sys_timeout_window_test_seq("hang_sys_timeout_window_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 8, f"phases {seq.phases}, want 8"
        assert seq.accesses >= 41, f"only {seq.accesses} SEP_IN accesses issued, want >= 41"
