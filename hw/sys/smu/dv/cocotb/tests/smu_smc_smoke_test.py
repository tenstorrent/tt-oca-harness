# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_smoke_test — SMU_ALL_003.

DV-CARD:          SMU_ALL_003   ANCHOR: smu_smc_smoke_test

Bare ``tb_top`` / ``smu_uvm_top`` SEP=0 — hierarchical dual-net CONNECTIVITY.
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_smc_smoke_test_seq import smu_smc_smoke_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_smoke_test(smu_base_test):
    """SMU_ALL_003: SMC dual-network AXI4-Lite LP + 64-bit width."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_smc_smoke_test SMU_ALL_003 r6 SEP=0 dual-net"
        )
        seq = smu_smc_smoke_test_seq(self)
        await seq.run()
