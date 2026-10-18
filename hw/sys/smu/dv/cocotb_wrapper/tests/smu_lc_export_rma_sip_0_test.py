# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_export_rma_sip_0_test - RMA_SIP exports 0xD2 and its gated paths follow that posture.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc, hw/sys/smu/doc/port_table.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_export_rma_sip_0_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_export_seq import (
    FEAT_CTRL_ALL_ENABLED,
    LANE_ENABLED,
    ExportSpec,
    smu_lc_export_seq,
)
from smu_base_test import smu_base_test

SPEC = ExportSpec(
    state="RMA_SIP_0",
    tag="RMA-SIP",
    image="sep_efuse_shadow_lc_rma_sip_0.preload",
    feat_ctrl=FEAT_CTRL_ALL_ENABLED,
    lane=LANE_ENABLED,
)


@pyuvm.test()
class smu_lc_export_rma_sip_0_test(smu_base_test):
    """The RMA_SIP image exports 0xD2 and leaves the lifecycle-gated paths in its posture."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_export_rma_sip_0_test SEP=1 RMA_SIP export and path posture"
        )
        await smu_lc_export_seq(self, SPEC).run()
