# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag_smoke_test — SMU_ALL_005 PTAP IDCODE/BYPASS/TRST (SEP=0).

DV-CARD:          SMU_ALL_005   ANCHOR: smu_dtp_jtag_smoke_test
DV-CARD-REVISION: 9   RECORD-SHA256: d1b60225e167bf1eae0232095647a37e7077704f340f2a4b37ad864fbc56f57d
DV-CARD-SOURCE:   hw/sys/smu/dv/tb/SMU_ALL_VPLAN_DETAIL.md @ artifact_revision 9   ENV: cocotb

Card OWNS DTP-JTAG-PTAP.S1/S2/S3 ONLY (IDCODE/BYPASS/TRST).
JTAG2AXI / OTP / STAP are out of scope (re-homed to SMU_ALL_008).
"""

from __future__ import annotations

import pyuvm

from seq_lib.smu_dtp_jtag_smoke_test_seq import smu_dtp_jtag_smoke_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag_smoke_test(smu_base_test):
    """SMU_ALL_005: PTAP IDCODE + BYPASS + TRST/POR → Test-Logic-Reset."""

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=BARE smu_dtp_jtag_smoke_test SMU_ALL_005 under "
            "--dut smu SEP=0 (PTAP.S1/S2/S3 only)"
        )
        seq = smu_dtp_jtag_smoke_test_seq(self)
        await seq.run()
