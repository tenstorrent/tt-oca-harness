# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_warm_reset_register_retention_test - registers across the CORE0 watchdog warm reset.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_warm_reset_register_retention_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_warm_reset_register_retention_test_seq import (
    smu_smc_warm_reset_register_retention_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_warm_reset_register_retention_test(smu_base_test):
    """Reset-unit and isolation registers survive the warm reset; CORE0 CMP and CTRL return."""

    use_shared_env = True
    required_evidence = (
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
        "CHK-WARM-RET-EVENT",
        "CHK-WARM-RET-ISO",
        "CHK-WARM-RET-MEASURED",
        "CHK-WARM-RET-PRIMARY-STAY",
        "CHK-WARM-RET-RELEASE",
        "CHK-WARM-RET-SSCFG",
        "CHK-WARM-RET-SSCOLD",
        "CHK-WARM-RET-WDT-RETURN",
    )

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_warm_reset_register_retention_test SEP=1 JTAG")
        seq = smu_smc_warm_reset_register_retention_test_seq(self)
        await seq.run()
        assert seq.done, "warm reset register retention scenario incomplete"
