# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_dis_sys_not_binding_rma_sip_test - in RMA_SIP the SYS_DIS vector closes no path.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc, hw/sys/dtp/doc/jtag.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_dis_sys_not_binding_rma_sip_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_dis_sys_not_binding_rma_sip_test_seq import (
    smu_lc_dis_sys_not_binding_rma_sip_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_dis_sys_not_binding_rma_sip_test(smu_base_test):
    """SYS_DIS bits 0, 1 and 24 in RMA_SIP leave the fabric, STAPs and SIBs open."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_dis_sys_not_binding_rma_sip_test SEP=1 RMA_SIP SYS_DIS "
            "not binding"
        )
        await smu_lc_dis_sys_not_binding_rma_sip_test_seq(self).run()
