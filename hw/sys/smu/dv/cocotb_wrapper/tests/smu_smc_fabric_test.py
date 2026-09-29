# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_fabric_test - SMC firmware on every hart through the SMU fabric.

The SMC ROM image smu_smc_fabric runs on all four SMC harts; after the SEP
debug system bus opens the SEP aperture and the SMC outbound filter, each
hart stores to and reads back SEP SRAM and an ext_out address, and hart 0
posts TEST_PASS. The bench cross-checks every word the firmware wrote.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_fabric_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_fabric_test_seq import smu_smc_fabric_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_fabric_test(smu_base_test):
    """SMC ROM firmware stores and loads on smc_out and ext_out from four harts; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_smc_fabric_test SEP=1 SMC firmware")
        seq = smu_smc_fabric_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok, *seq.steps.values())
        assert all(steps), f"smc fabric firmware incomplete {steps}"
