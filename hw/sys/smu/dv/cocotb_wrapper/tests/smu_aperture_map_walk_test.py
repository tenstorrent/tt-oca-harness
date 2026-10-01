# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_aperture_map_walk_test - the SMC aperture decoded at every programmed base and size.

Walks SMC BASE_CONFIG.REGION_SIZE through every power of two JTAG2AXI can
program and still follow, with GLOBAL_BASE alternating between two bit
patterns aligned to each size, and proves at each setting that the SMU
crossbar forwards the window's first and last word to the SMC and refuses the
word below it and the address past it.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_aperture_map_walk_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_aperture_map_walk_test_seq import smu_aperture_map_walk_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_aperture_map_walk_test(smu_base_test):
    """SMC aperture walk with the crossbar decode checked at every setting; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_aperture_map_walk_test SMC-MAP")
        seq = smu_aperture_map_walk_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"aperture walk incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok} s4={seq.s4_ok}"
        )
