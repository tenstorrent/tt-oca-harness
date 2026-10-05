# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_jtag2axi_vs_smn_same_csr_race_test — J2A vs SMN coherent winner."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_jtag2axi_vs_smn_same_csr_race_test_seq import (
    smu_jtag2axi_vs_smn_same_csr_race_test_seq,
)
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_jtag2axi_vs_smn_same_csr_race_test(smu_base_test):
    """Race J2A vs SMN on SCRATCH; coherent winner, no tear."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info(
            "DUT_TAG=WRAPPER smu_jtag2axi_vs_smn_same_csr_race_test TierA J2A||SMN race"
        )
        seq = smu_jtag2axi_vs_smn_same_csr_race_test_seq(self)
        await seq.run()
        assert seq.s1_ok and seq.s2_ok and seq.s3_ok and seq.s4_ok, (
            f"jtag2axi_vs_smn race incomplete s1={seq.s1_ok} s2={seq.s2_ok} "
            f"s3={seq.s3_ok} s4={seq.s4_ok}"
        )
