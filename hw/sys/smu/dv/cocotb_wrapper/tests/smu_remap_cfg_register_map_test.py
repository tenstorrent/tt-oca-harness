# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_remap_cfg_register_map_test — alias and output remap register map."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_remap_cfg_register_map_test_seq import smu_remap_cfg_register_map_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_remap_cfg_register_map_test(smu_base_test):
    """Reset, placement and field masks of the alias and output remap registers."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_remap_cfg_register_map_test SEP=1 J2A+s_axi")
        seq = smu_remap_cfg_register_map_test_seq(self)
        await seq.run()
        assert seq.done, "remap register map incomplete"
