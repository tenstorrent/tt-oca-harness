# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_base_config_corners_test — LOCAL_BASE read-only and GLOBAL_BASE moves with the ports."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_base_config_corners_test_seq import smu_base_config_corners_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_base_config_corners_test(smu_base_test):
    """SMC base configuration corners seen from JTAG2AXI, the external input and the ports."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_base_config_corners_test TierA SMC base config SEP=1 J2A+ext_in"
        )
        await smu_base_config_corners_test_seq(self).run()
