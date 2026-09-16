# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smu_axi_xbar_structure_test — SEP=0 xbar absent (Nightly FAB_SMU_003)."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_axi_xbar_structure_test_seq import smu_axi_xbar_structure_test_seq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_axi_xbar_structure_test(smu_base_test):
    """gen_no_sep IW converters present; smu_axi_xbar not elaborated."""

    use_shared_env = True

    async def run_scenario(self) -> None:
        seq = smu_axi_xbar_structure_test_seq(self)
        await seq.run()
        assert seq.pos_ok and seq.absent_ok, (
            f"xbar structure incomplete pos={seq.pos_ok} absent={seq.absent_ok}"
        )
