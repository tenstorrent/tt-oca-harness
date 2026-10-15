# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_cpu_ctrl_access_rules_test: CPU_CTRL zero, read-only, reserved, AxPROT."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_cpu_ctrl_access_rules_test_seq import smc_cpu_ctrl_access_rules_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_cpu_ctrl_access_rules_test(smc_base_test):
    """Exercise CPU_CTRL zero writes, read-only writes, reserved bits and AxPROT over SEP_IN."""

    required_evidence = (
        "CHK-ACCR-PROT",
        "CHK-ACCR-RESERVED",
        "CHK-ACCR-RO-RESP",
        "CHK-ACCR-ZERO",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_cpu_ctrl_access_rules_test_seq("cpu_ctrl_access_rules_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
