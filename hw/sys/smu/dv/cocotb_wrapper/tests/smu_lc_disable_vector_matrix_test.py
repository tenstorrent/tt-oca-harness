# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_lc_disable_vector_matrix_test - debug-path posture of one disable-vector preload file.

Spec: hw/sys/sep/doc/lifecycle_controller.adoc, hw/sys/sep/regs/blocks/sep_efuse_map/
sep_efuse_map.rdl. Ten testlist entries name this module, one per file of the preload set; each
supplies its file as ``+sep_shadow_reg_preload``.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_lc_disable_vector_matrix_prod_test --target compile_smu_chiplet
"""

from __future__ import annotations

import cocotb
import pyuvm
from seq_lib.smu_lc_disable_vector_matrix_test_seq import (
    sample_pre_sense,
    smu_lc_disable_vector_matrix_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_lc_disable_vector_matrix_test(smu_base_test):
    """The image and disable-vector pair of the run's preload file set the debug paths."""

    use_shared_env = True
    required_evidence = (
        "CHK-LCVEC-FEAT",
        "CHK-LCVEC-IMAGE",
        "CHK-LCVEC-OPEN",
        "CHK-LCVEC-READBACK",
        "CHK-LCVEC-SHUT",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def bring_up(self) -> None:
        self.pre_sense = {"samples": 0, "lc": None, "feat": None}
        cocotb.start_soon(sample_pre_sense(cocotb.top, self.pre_sense))
        await super().bring_up()

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_lc_disable_vector_matrix_test SEP=1 lifecycle image and "
            "disable-vector pair"
        )
        seq = smu_lc_disable_vector_matrix_test_seq(self)
        await seq.run()
        assert seq.done, "disable-vector matrix scenario incomplete"
