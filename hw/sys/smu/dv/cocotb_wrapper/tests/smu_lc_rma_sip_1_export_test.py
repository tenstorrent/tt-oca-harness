# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_rma_sip_1_export_test - the RMA_SIP LC_STATE pair is exported as 0xC3.

Contract SMU_WRAPPER_LC_GATING_009 (hw/sys/sep/doc/otp_fuse_controller.adoc:216-224,
hw/sys/sep/doc/lifecycle_controller.adoc:98-148, hw/sys/smu/doc/port_table.adoc:131).

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_rma_sip_1_export_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_rma_sip_1_export_test_seq import smu_lc_rma_sip_1_export_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_rma_sip_1_export_test(smu_base_test):
    """lc_state_o, obs_sep_lc_state_o and smc_lc_state_in_o carry 0xC3 under the RMA_SIP image."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_rma_sip_1_export_test SEP=1 RMA_SIP LC_STATE export"
        )
        await smu_lc_rma_sip_1_export_test_seq(self).run()
