# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_efuse_shadow_sense_reset_test - the SMC eFuse shadow map at the wrapper.

``smc_shadow_regs_o`` takes the sensed eFuse image word for word after a real
fuse sense, and reads the reset value of every ``smc_efuse_map`` field while
``rst_cold_ni`` is held. The image ``+smc_efuse_hex`` names programs every fuse
bit, so both samples are taken on the full width of the port.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_efuse_shadow_sense_reset_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_efuse_shadow_sense_reset_seq import smu_smc_efuse_shadow_sense_reset_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_efuse_shadow_sense_reset_test(smu_base_test):
    """The SMC eFuse shadow map proved against the image the sense read, then against reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_smc_efuse_shadow_sense_reset_seq(self).run()
