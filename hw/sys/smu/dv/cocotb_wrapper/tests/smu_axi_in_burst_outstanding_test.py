# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_in_burst_outstanding_test — inbound SMN depth and burst type."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_in_burst_outstanding_test_seq import smu_axi_in_burst_outstanding_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_in_burst_outstanding_test(smu_base_test):
    """Concurrent inbound transfers and unsupported burst types on the wrapper; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_in_burst_outstanding_test AXI-IN")
        seq = smu_axi_in_burst_outstanding_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok, f"axi-in incomplete s1={seq.s1_ok} s2={seq.s2_ok}"
