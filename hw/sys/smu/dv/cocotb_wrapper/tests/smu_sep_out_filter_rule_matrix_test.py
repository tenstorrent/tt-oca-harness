# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_out_filter_rule_matrix_test - SEP outbound filter rules from the debug system bus."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_out_filter_rule_matrix_test_seq import (
    smu_sep_out_filter_rule_matrix_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_out_filter_rule_matrix_test(smu_base_test):
    """Block by default, admit, permission, polarity, granule, index and priority on 32 entries."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_sep_out_filter_rule_matrix_test TierA SEP-OUT filter SEP=1 "
            "SEP DM SBA"
        )
        await smu_sep_out_filter_rule_matrix_test_seq(self).run()
