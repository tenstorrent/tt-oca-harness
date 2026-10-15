# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_efuse_shadow_map_readback_test - SMC eFuse map readback against the sense stream.

On the sep_rtl_fuse_sense run mode the eFuse shim response stream is captured at the SMU
boundary during the shared bring-up, and sampled words of the SMC eFuse map are read back over
JTAG2AXI and compared with it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_efuse_shadow_map_readback_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_efuse_shadow_map_readback_test_seq import (
    SmuEfuseStreamCapture,
    smu_smc_efuse_shadow_map_readback_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_efuse_shadow_map_readback_test(smu_base_test):
    """Sampled SMC eFuse map words equal the response words the sense streamed."""

    use_shared_env = True

    async def bring_up(self) -> None:
        """Arm the stream capture, then run the shared bring-up that starts the sense."""
        self.efuse_capture = SmuEfuseStreamCapture()
        self.efuse_capture.arm()
        await super().bring_up()

    async def run_scenario(self) -> None:
        await smu_smc_efuse_shadow_map_readback_test_seq(self).run()
