# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP_AXI hang detector control writes while a SEP_IN read stays held."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_hang_sep_drop_controls_test_seq import smc_hang_sep_drop_controls_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_hang_sep_drop_controls_test(smc_base_test):
    """Clearing irq_en or enable drops the SEP_AXI timeout irq while the read stays held."""

    required_evidence = (
        "CHK-DROPCTL-BOTH-CAUSES-LOG",
        "CHK-DROPCTL-ENABLE-CLEAR",
        "CHK-DROPCTL-GATE-HOLD",
        "CHK-DROPCTL-IRQEN-CLEAR",
        "CHK-DROPCTL-REENABLE-LOG",
        "CHK-DROPCTL-TOGGLE-GATING",
        "CHK-DROPCTL-TOGGLE-LOG",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_hang_sep_drop_controls_test_seq("hang_sep_drop_controls_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.phases == 7, f"phases {seq.phases}, want 7"
        assert seq.accesses >= 11, f"only {seq.accesses} SEP_IN accesses issued, want >= 11"
