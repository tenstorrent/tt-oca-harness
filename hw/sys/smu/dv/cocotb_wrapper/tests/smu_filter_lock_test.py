# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_filter_lock_test — write-once locked bit of the inbound and outbound filter entries."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_filter_lock_test_seq import smu_filter_lock_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_filter_lock_test(smu_base_test):
    """Lock entry 5 of both filter instances; rejected writes, frozen values, isolation."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_filter_lock_test SMU_FABRIC_FILTER_014 SEP=1 J2A+s_axi"
        )
        seq = smu_filter_lock_test_seq(self)
        await seq.run()
        assert seq.done, "filter lock scenario incomplete"
