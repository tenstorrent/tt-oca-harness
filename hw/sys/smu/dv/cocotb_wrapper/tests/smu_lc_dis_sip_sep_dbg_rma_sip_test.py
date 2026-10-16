# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_dis_sip_sep_dbg_rma_sip_test - in RMA_SIP SIP_DIS SEP_DBG closes Case 3 only.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc, hw/sys/dtp/doc/jtag.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_dis_sip_sep_dbg_rma_sip_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_dis_sip_sep_dbg_rma_sip_test_seq import (
    smu_lc_dis_sip_sep_dbg_rma_sip_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_dis_sip_sep_dbg_rma_sip_test(smu_base_test):
    """SIP_DIS bit 0 in RMA_SIP shuts the SEP debug STAP and the DFT secure SIB only."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_dis_sip_sep_dbg_rma_sip_test SEP=1 RMA_SIP SIP_DIS "
            "SEP_DBG paths"
        )
        await smu_lc_dis_sip_sep_dbg_rma_sip_test_seq(self).run()
