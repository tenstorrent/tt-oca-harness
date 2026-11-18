# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_reset_retention_matrix_rand_test - SMC register retention across drawn resets.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_reset_retention_matrix_rand_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_reset_retention_matrix_rand_test_seq import (
    smu_reset_retention_matrix_rand_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_reset_retention_matrix_rand_test(smu_base_test):
    """Cool, cold and warm resets clear or keep each SMC register bank as its domain gives."""

    use_shared_env = True
    required_evidence = (
        "CHK-NONVAC",
        "CHK-RETMX-CLEARED",
        "CHK-RETMX-ISOLATE-ALIVE",
        "CHK-RETMX-KEPT",
        "CHK-RETMX-RESETVAL",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_reset_retention_matrix_rand_test SEP=1 JTAG2AXI")
        seq = smu_reset_retention_matrix_rand_test_seq(self)
        await seq.run()
        assert seq.done, "reset retention matrix scenario incomplete"
