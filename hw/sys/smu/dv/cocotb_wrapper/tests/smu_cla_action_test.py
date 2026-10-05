# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_cla_action_test - SMC CLA node 0 actions observed at the SMU.

JTAG2AXI programs the SMC CLA node 0 event-action pair to fire each custom
action, both cross-trigger outputs and the clock-halt action; each is compared
on the SMU nets it drives and cleared again.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_cla_action_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_cla_action_test_seq import smu_cla_action_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_cla_action_test(smu_base_test):
    """CLA custom, cross-trigger and clock-halt actions; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_cla_action_test CLA")
        seq = smu_cla_action_test_seq(self)
        await seq.run()
        assert all(seq.steps.values()), f"CLA action sweep incomplete {seq.steps}"
