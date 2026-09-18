# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the LCC flow firmware against one lifecycle state's eFuse image."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_lcc_state_matrix_seq import SmuSepLccStateMatrixSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_lcc_state_matrix_test(smu_base_test):
    """Require the LCC profile to match the state its eFuse image encodes."""

    async def run_scenario(self) -> None:
        await SmuSepLccStateMatrixSeq(self).run()
