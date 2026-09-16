# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_wdt_boundary_timeout_test - the watchdog timeouts at the SMU pins.

smu_smc_wdt_timeout_irq_test stops at the watchdog's pending bit because it
never sets WDOGRSTEN, which is what gates the cluster's reset output. This
leaf sets it, follows the CORE0 timeout out to smc_wdt_first_timeout_o, lets
the held first timeout run the second-stage counter down to
smc_wdt_second_timeout_o, and requires the SMC warm reset to drop with it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_wdt_boundary_timeout_test --target compile_smu_chiplet_no_sep
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_wdt_boundary_timeout_seq import smu_smc_wdt_boundary_timeout_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_wdt_boundary_timeout_test(smu_base_test):
    """CORE0 watchdog first and second timeout at the SMU boundary."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_smc_wdt_boundary_timeout_seq(self).run()
