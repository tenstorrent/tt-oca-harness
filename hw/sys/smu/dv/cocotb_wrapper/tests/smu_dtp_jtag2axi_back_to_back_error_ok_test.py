# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_dtp_jtag2axi_back_to_back_error_ok_test — DECERR then immediate OK."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_jtag2axi_back_to_back_error_ok_test_seq import (
    smu_dtp_jtag2axi_back_to_back_error_ok_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_jtag2axi_back_to_back_error_ok_test(smu_base_test):
    """Unmapped DECERR then immediate VERSION_LO SUCCESS; gate tied open."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_dtp_jtag2axi_back_to_back_error_ok_test TierC JTAG2AXI-B2B SEP=1 JTAG"
        )
        seq = smu_dtp_jtag2axi_back_to_back_error_ok_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok and seq.s5_ok, (
            f"jtag2axi_b2b incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok} s5={seq.s5_ok}"
        )
