# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
# DV-TESTCASE-CONTRACT: SMC_COV_B4_007 ANCHOR: smc_hang_data_timeout_window_test
# DV-TESTCASE-CONTRACT-REVISION: 1 RECORD-SHA256: d9b71cae4533d0963caa8e51ebe1b76291b2af12f09b36945a6e6be8e677556e
# DV-TESTCASE-CONTRACT-SOURCE: hw/sys/smc/dv/docs/SMC_VPLAN.adoc section 480 `smc_hang_data_timeout_window_test` ENV: cocotb
"""DATA_ACCEL hang detector stalls below, beyond and at the timeout threshold, then CTRL gating."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_data_timeout_window_test_seq import smc_hang_data_timeout_window_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_data_timeout_window_test(smc_base_test):
    """A 16-rise stall stays quiet; a held stall raises data irq and raw bit 286; enable,
    irq_en and irq_test gate the interrupt."""

    required_evidence = (
        "CHK-DATAWIN-AT-LOG",
        "CHK-DATAWIN-BELOW",
        "CHK-DATAWIN-BEYOND",
        "CHK-DATAWIN-DISABLE-AFTER-TIMEOUT",
        "CHK-DATAWIN-IRQEN-CLEAR",
        "CHK-DATAWIN-IRQTEST-DISABLED",
        "CHK-DATAWIN-IRQTEST-NOIRQEN",
        "CHK-DATAWIN-IRQTEST-RAISE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_data_timeout_window_test_seq("hang_data_timeout_window_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 8, f"phases {seq.phases}, want 8"
        assert seq.accesses >= 60, f"only {seq.accesses} SEP_IN accesses issued, want >= 60"
