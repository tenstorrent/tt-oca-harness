# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_alias_cache_reset_test — alias remap AxCACHE replacement and reset transparency."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_alias_cache_reset_test_seq import smu_alias_cache_reset_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_alias_cache_reset_test(smu_base_test):
    """Alias region 0 cacheable 0..15 on smu_axi_out, miss and reset transparency."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_alias_cache_reset_test SMU_FABRIC_FILTER_019 SEP=1 J2A+s_axi"
        )
        seq = smu_alias_cache_reset_test_seq(self)
        await seq.run()
        assert seq.done, "alias cache reset scenario incomplete"
