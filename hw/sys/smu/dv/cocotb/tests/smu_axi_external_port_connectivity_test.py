# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_external_port_connectivity_test — SMU_ALL_002 rev 4.

DV-CARD:          SMU_ALL_002   ANCHOR: smu_axi_external_port_connectivity_test
DV-CARD-REVISION: 4   RECORD-SHA256: 61e6a1d6e4b3a7f36b116cea03e3071127257a88b50b87161c3dd4b5bc62cca6
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md @ artifact_revision 4   ENV: cocotb
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_axi_external_port_connectivity_test_seq import (
    smu_axi_external_port_connectivity_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_external_port_connectivity_test(smu_base_test):
    """SMU_ALL_002 r4: SEP=0 inbound SMN→SMC + direct IW converters."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_axi_external_port_connectivity_test "
            "SMU_ALL_002 SEP=0"
        )
        seq = smu_axi_external_port_connectivity_test_seq(self)
        await seq.run()
