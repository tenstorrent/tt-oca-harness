# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_smc_dtp_jtag2axi_smoke_test — SMC fabric J2A smoke (SEP=1, no Force)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_smc_dtp_jtag2axi_smoke_test_seq import (
    smu_smc_dtp_jtag2axi_smoke_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_smc_dtp_jtag2axi_smoke_test(smu_base_test):
    """SMC fabric J2A SCRATCH_15 + SPM + series INCR; gate open on the SEP=1 wrapper."""

    use_shared_env = True
    # Its last step is an SMC fabric SERIES INCR write, which returns zeros or
    # parks in BUSY whenever jtag_period_ns / smu_clk_period_ns is under 4; see
    # smu_base_test.min_jtag_smu_ratio.
    min_jtag_smu_ratio = 4.0

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_smc_dtp_jtag2axi_smoke_test TierC JTAG2AXI-SMOKE SEP=1 JTAG"
        )
        seq = smu_smc_dtp_jtag2axi_smoke_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"jtag2axi_smoke incomplete s1={seq.s1_ok} s2={seq.s2_ok} s3={seq.s3_ok} s4={seq.s4_ok}"
        )
