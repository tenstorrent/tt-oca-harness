# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_demote_test_dev_test - in TEST_DEV a demotion forces its debug group open until a cold
reset.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc, hw/sys/sep/regs/blocks/sep_lifecycle_ctrl.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_demote_test_dev_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_demote_test_dev_test_seq import smu_lc_demote_test_dev_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_demote_test_dev_test(smu_base_test):
    """DEMOTE_1 and DEMOTE_2 written over the SEP system bus force DBG_1 and DBG_2 open."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_demote_test_dev_test SEP=1 TEST_DEV demotion over the "
            "system bus and cold-reset clear"
        )
        await smu_lc_demote_test_dev_test_seq(self).run()
