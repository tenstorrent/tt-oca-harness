# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_alias_dma_manager_test — SMC alias remap applied to an iDMA copy's source and destination."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_alias_dma_manager_test_seq import smu_alias_dma_manager_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_alias_dma_manager_test(smu_base_test):
    """An iDMA copy with every alias region at reset, then with a source and destination region."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_alias_dma_manager_test TierA SMC alias remap iDMA SEP=1 J2A"
        )
        await smu_alias_dma_manager_test_seq(self).run()
