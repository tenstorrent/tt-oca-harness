# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sram_auto_init_disabled_test - SRAM auto-initialization held off.

The complement of smu_sram_auto_init_done_test: with
smc_disable_sram_auto_init_i high at the SMU boundary, a cold reset must leave
the SMC scratch-RAM zeroing sweep unstarted and no zeroing write may reach the
scratch RAM, yet smc_init_mem_done_o must still assert and hold.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_sram_auto_init_disabled_test --target compile_smu_chiplet_no_sep
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sram_auto_init_disabled_seq import smu_sram_auto_init_disabled_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sram_auto_init_disabled_test(smu_base_test):
    """smc_init_mem_done_o with the SRAM auto-initialization disabled."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_sram_auto_init_disabled_seq(self).run()
