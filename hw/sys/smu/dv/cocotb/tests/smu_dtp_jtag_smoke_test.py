# SPDX-License-Identifier: Apache-2.0
"""smu_dtp_jtag_smoke_test — SMU P0 PTAP BYPASS + state (SMU_002).

DV-CARD:          SMU_002   ANCHOR: smu_dtp_jtag_smoke_test
DV-CARD-REVISION: 1   RECORD-SHA256: 0fc038c569ce069f62337828e29159a28e551d6c4e827caa3a8d249a25f4a252
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_VPLAN_DETAIL.md @ artifact_revision 1   ENV: cocotb

Card OWNS PTAP BYPASS+state ONLY (not IDCODE; not JTAG2AXI/OTP/scan hosts).
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_dtp_jtag_smoke_test_seq import smu_dtp_jtag_smoke_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag_smoke_test(smu_base_test):
    """SMU_002: PTAP BYPASS one-bit latency + TAP state observation."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_dtp_jtag_smoke_test SMU_002 under --dut smu SEP=0"
        )
        seq = smu_dtp_jtag_smoke_test_seq(self)
        await seq.run()
