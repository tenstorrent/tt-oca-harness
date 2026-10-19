# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_output_remap_region_matrix_test - SEP AP and STEE output remap regions 1 to 15."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_output_remap_region_matrix_test_seq import (
    smu_sep_output_remap_region_matrix_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_output_remap_region_matrix_test(smu_base_test):
    """Region translation, isolation, table independence and invalid-region pass-through."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_sep_output_remap_region_matrix_test TierA SEP-OUT remap SEP=1 "
            "SEP DM SBA"
        )
        await smu_sep_output_remap_region_matrix_test_seq(self).run()
