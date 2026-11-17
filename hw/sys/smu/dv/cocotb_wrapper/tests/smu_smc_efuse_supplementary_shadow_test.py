# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_efuse_supplementary_shadow_test - the SMC supplementary fuse window after the boot sense.

On the sep_rtl_fuse_sense run mode the eFuse shim response stream is captured at the SMU
boundary during the shared bring-up, 35 sampled words of the SMC supplementary fuse window are
read over JTAG2AXI and compared with the stream and the image, and all 128 stream words are
compared with the image.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_smc_efuse_supplementary_shadow_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_efuse_shadow_map_readback_test_seq import SmuEfuseStreamCapture
from seq_lib.smu_smc_efuse_supplementary_shadow_test_seq import (
    smu_smc_efuse_supplementary_shadow_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_efuse_supplementary_shadow_test(smu_base_test):
    """The supplementary window words equal the sensed stream words and the image."""

    use_shared_env = True

    async def bring_up(self) -> None:
        """Arm the stream capture, then run the shared bring-up that starts the sense."""
        self.efuse_capture = SmuEfuseStreamCapture()
        self.efuse_capture.arm()
        await super().bring_up()

    async def run_scenario(self) -> None:
        await smu_smc_efuse_supplementary_shadow_test_seq(self).run()
