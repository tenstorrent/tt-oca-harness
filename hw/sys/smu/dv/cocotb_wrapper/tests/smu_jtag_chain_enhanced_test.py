# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_jtag_chain_enhanced_test — IDCODE/BYPASS at 1/5/10/20 MHz TCK."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_jtag_chain_enhanced_test_seq import smu_jtag_chain_enhanced_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_jtag_chain_enhanced_test(smu_base_test):
    """PTAP IDCODE + BYPASS after VIP TCK period reprogram; no Force."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_jtag_chain_enhanced_test TierC DTP-JTAG-CHAIN-ENHANCED SEP=1 JTAG"
        )
        seq = smu_jtag_chain_enhanced_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"jtag_chain_enhanced incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok}"
        )
