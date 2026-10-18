# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_sep_inbound_burst_extension_test - external-input bursts into the extension port and SHIM."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_inbound_burst_extension_test_seq import (
    smu_sep_inbound_burst_extension_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_inbound_burst_extension_test(smu_base_test):
    """INCR bursts reach the SEP extension port and the eFuse SHIM routed on their first address."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_sep_inbound_burst_extension_test SEP=1 ext_in -> sep_in"
        )
        seq = smu_sep_inbound_burst_extension_test_seq(self)
        await seq.run()
        assert seq.done, "sep inbound burst extension scenario incomplete"
