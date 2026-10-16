# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_dis_sys_chiplet_dbg_test_dev_test - in TEST_DEV SYS_DIS CHIPLET_DBG closes Case 2 and 3.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc, hw/sys/dtp/doc/jtag.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_dis_sys_chiplet_dbg_test_dev_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq import (
    smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_dis_sys_chiplet_dbg_test_dev_test(smu_base_test):
    """SYS_DIS bit 1 in TEST_DEV shuts the SMC fabric, SMC, extra and SEP STAPs and both DFT SIBs."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_dis_sys_chiplet_dbg_test_dev_test SEP=1 TEST_DEV SYS_DIS "
            "CHIPLET_DBG paths"
        )
        await smu_lc_dis_sys_chiplet_dbg_test_dev_test_seq(self).run()
