# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_filter_cfg_register_map_test — filter control register map of both filter instances."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_filter_cfg_register_map_test_seq import smu_filter_cfg_register_map_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_filter_cfg_register_map_test(smu_base_test):
    """Reset values, field masks, entry stride and half-word access of both filter instances."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_filter_cfg_register_map_test SMU_FABRIC_FILTER_011 SEP=1 J2A+s_axi"
        )
        seq = smu_filter_cfg_register_map_test_seq(self)
        await seq.run()
        assert seq.done, "filter cfg register map scenario incomplete"
