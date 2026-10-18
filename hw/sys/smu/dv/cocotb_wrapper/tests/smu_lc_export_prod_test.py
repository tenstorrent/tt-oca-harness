# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_export_prod_test - PROD exports 0xE1 and its gated paths follow that posture.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc, hw/sys/smu/doc/port_table.adoc.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_export_prod_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_lc_export_seq import (
    FEAT_CTRL_FUNCTION_ONLY,
    LANE_DISABLED,
    ExportSpec,
    smu_lc_export_seq,
)
from smu_base_test import smu_base_test

SPEC = ExportSpec(
    state="PROD",
    tag="PROD",
    image="sep_efuse_shadow_lc_prod.preload",
    feat_ctrl=FEAT_CTRL_FUNCTION_ONLY,
    lane=LANE_DISABLED,
    witness="token_write_read",
    lane_check=True,
    closed_paths=True,
)


@pyuvm.test()
class smu_lc_export_prod_test(smu_base_test):
    """The PROD image exports 0xE1 and leaves the lifecycle-gated paths in its posture."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_export_prod_test SEP=1 PROD export and path posture"
        )
        await smu_lc_export_seq(self, SPEC).run()
