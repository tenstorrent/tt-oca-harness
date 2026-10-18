# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_cold_boot_release_order_test - cold boot power-good, cold and primary reset order.

Drives powergood_i and rst_cold_ni on the wrapper after bring-up and samples the boundary
reset pins on clk_ref_i and clk_smu_i: power-good stretch, cold reset hold and release
extension, and the release order of the primary resets behind the stable cold reset.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_cold_boot_release_order_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_cold_boot_release_order_test_seq import (
    smu_smc_cold_boot_release_order_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_cold_boot_release_order_test(smu_base_test):
    """Leaf-driven cold boot: power-good stretch, cold extension, primary reset release order."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_smc_cold_boot_release_order_test_seq(self).run()
