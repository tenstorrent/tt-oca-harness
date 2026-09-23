# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag_smoke_test — SMU_ALL_005 PTAP IDCODE/BYPASS/TRST.

DV-CARD:          SMU_ALL_005   ANCHOR: smu_dtp_jtag_smoke_test

Card OWNS DTP-JTAG-PTAP.S1/S2/S3 ONLY (IDCODE/BYPASS/TRST).
JTAG2AXI / OTP / STAP are owned by SMU_ALL_008.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_jtag_smoke_test_seq import smu_dtp_jtag_smoke_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag_smoke_test(smu_base_test):
    """SMU_ALL_005: PTAP IDCODE + BYPASS + TRST/POR → Test-Logic-Reset."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_dtp_jtag_smoke_test SMU_ALL_005 under "
            "--dut smu (PTAP.S1/S2/S3 only)"
        )
        seq = smu_dtp_jtag_smoke_test_seq(self)
        await seq.run()
