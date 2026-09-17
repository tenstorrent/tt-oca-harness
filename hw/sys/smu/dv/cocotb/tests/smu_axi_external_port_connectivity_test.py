# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_external_port_connectivity_test — SMU_ALL_002.

DV-CARD:          SMU_ALL_002   ANCHOR: smu_axi_external_port_connectivity_test
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_external_port_connectivity_test_seq import (
    smu_axi_external_port_connectivity_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_external_port_connectivity_test(smu_base_test):
    """SMU_ALL_002: SEP=0 inbound SMN→SMC + direct IW converters."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=BARE smu_axi_external_port_connectivity_test SMU_ALL_002 SEP=0")
        seq = smu_axi_external_port_connectivity_test_seq(self)
        await seq.run()
