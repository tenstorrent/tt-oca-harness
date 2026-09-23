# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the LCC flow firmware against one lifecycle state's eFuse image."""

from __future__ import annotations

from seq_lib.smu_sep_lcc_state_matrix_seq import SmuSepLccStateMatrixSeq
from smu_base_test import smu_base_test


class smu_sep_lcc_state_matrix_test(smu_base_test):
    """Require the LCC profile to match the state its eFuse image encodes.

    Shared body: not a test itself. The testlist names one module per eFuse
    image, each a subclass in its own file, so the module a testlist entry names
    ends in that entry's name.
    """

    required_evidence = ("SEP_LCC_STATE_DECODE_OK", "SEP_LCC_STATE_PROFILE_OK")

    async def run_scenario(self) -> None:
        await SmuSepLccStateMatrixSeq(self).run()
