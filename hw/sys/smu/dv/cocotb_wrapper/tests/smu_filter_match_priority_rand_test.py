# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_filter_match_priority_rand_test - filter match terms, priority and permission, seed-drawn.

CCACHE_DISABLE=1 python3 tools/dv/run_dv.py --dut smu \\
    --items smu_filter_match_priority_rand_test --target compile_smu_chiplet
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_filter_match_priority_rand_test_seq import (
    smu_filter_match_priority_rand_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_filter_match_priority_rand_test(smu_base_test):
    """Drawn entries of the SYS_IN, SMC outbound and SEP outbound filters decide as specified."""

    use_shared_env = True
    required_evidence = (
        "CHK-FMATCH-ADMIT",
        "CHK-FMATCH-PERM",
        "CHK-FMATCH-PRIORITY",
        "CHK-FMATCH-TERMS",
        "CHK-FMATCH-WILDCARD",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_filter_match_priority_rand_test SYS_IN SMC-OUT SEP-OUT filters "
            "SEP=1 J2A SEP DM SBA"
        )
        seq = smu_filter_match_priority_rand_test_seq(self)
        await seq.run()
        assert seq.done, "filter match priority scenario incomplete"
