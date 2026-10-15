# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_ss_config_lane_drive_test - SS_CONFIG register to the ss_config_o lanes.

Writes SS_CONFIG one lane at a time, then all ones and all zeros, over the SMC fabric JTAG2AXI
bridge and compares the ss_config_o boundary output after each write.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_ss_config_lane_drive_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_ss_config_lane_drive_test_seq import smu_ss_config_lane_drive_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_ss_config_lane_drive_test(smu_base_test):
    """Every SS_CONFIG bit reaches its own ss_config_o lane."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        await smu_ss_config_lane_drive_test_seq(self).run()
