# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_out_filter_rule_matrix_test — SMC outbound filter entries 0 and 1, bridge and iDMA."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_out_filter_rule_matrix_test_seq import smu_out_filter_rule_matrix_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_out_filter_rule_matrix_test(smu_base_test):
    """Default permit, deny by permission, granule and END, priority and src_id on smu_axi_out."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_out_filter_rule_matrix_test TierA SMC outbound filter rules "
            "SEP=1 J2A iDMA"
        )
        await smu_out_filter_rule_matrix_test_seq(self).run()
