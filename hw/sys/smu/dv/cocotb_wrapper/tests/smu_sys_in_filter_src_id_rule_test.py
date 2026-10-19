# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sys_in_filter_src_id_rule_test — SYS_IN entry 0 source-ID match and term conjunction."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sys_in_filter_src_id_rule_test_seq import (
    smu_sys_in_filter_src_id_rule_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sys_in_filter_src_id_rule_test(smu_base_test):
    """AxUSER source ID, group ID, wildcard, term flips and per-channel permission on SYS_IN 0."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_sys_in_filter_src_id_rule_test TierA SYS-IN src_id SEP=1 "
            "J2A+ext_in"
        )
        await smu_sys_in_filter_src_id_rule_test_seq(self).run()
