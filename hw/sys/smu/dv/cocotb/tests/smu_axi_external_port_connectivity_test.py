# SPDX-License-Identifier: Apache-2.0
"""smu_axi_external_port_connectivity_test — SMU P0 SMN inbound port (SMU_003 rev 2).

DV-CARD:          SMU_003   ANCHOR: smu_axi_external_port_connectivity_test
DV-CARD-REVISION: 2   RECORD-SHA256: b3f464d54600dbb3056b1b509d0a68a416ef0a3a1db7ac08ab3c9840259cbeb9
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_VPLAN_DETAIL.md @ artifact_revision 2   ENV: cocotb
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_axi_external_port_connectivity_test_seq import (
    smu_axi_external_port_connectivity_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_external_port_connectivity_test(smu_base_test):
    """SMU_003 rev2: smu_axi_in inbound completion ONLY (outbound deferred)."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_axi_external_port_connectivity_test SMU_003 SEP=0"
        )
        seq = smu_axi_external_port_connectivity_test_seq(self)
        await seq.run()
