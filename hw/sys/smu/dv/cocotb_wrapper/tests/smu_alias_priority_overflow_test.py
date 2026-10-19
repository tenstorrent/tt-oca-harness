# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_alias_priority_overflow_test — alias remap overlap, degenerate regions and offset carry."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_alias_priority_overflow_test_seq import smu_alias_priority_overflow_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_alias_priority_overflow_test(smu_base_test):
    """Alias regions over JTAG2AXI: overlap, START >= END, top offset and field preservation."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_alias_priority_overflow_test TierA SMC alias remap SEP=1 J2A"
        )
        await smu_alias_priority_overflow_test_seq(self).run()
