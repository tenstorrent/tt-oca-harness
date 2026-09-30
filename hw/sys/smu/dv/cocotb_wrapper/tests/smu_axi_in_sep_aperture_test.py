# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_in_sep_aperture_test — inbound SMN traffic across the SEP aperture."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_in_sep_aperture_test_seq import smu_axi_in_sep_aperture_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_in_sep_aperture_test(smu_base_test):
    """ext_in reaches SEP SRAM, the SEP error paths and every SEP aperture address bit."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        self.logger.info("DUT_TAG=WRAPPER smu_axi_in_sep_aperture_test SEP=1 ext_in -> sep_in")
        seq = smu_axi_in_sep_aperture_test_seq(self)
        await seq.run()
        steps = (seq.s1_ok, seq.s2_ok, seq.s3_ok) + tuple(
            seq.steps.get(s, False) for s in ("S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
        )
        assert all(steps), f"sep_aperture incomplete s1..s11={steps}"
