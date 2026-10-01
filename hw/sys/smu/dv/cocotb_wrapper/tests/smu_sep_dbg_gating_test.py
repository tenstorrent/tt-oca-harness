# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove the lifecycle posture enforces debug gating on JTAG2AXI."""

from __future__ import annotations

from seq_lib.smu_sep_dbg_gating_seq import SmuSepDbgGatingSeq
from smu_base_test import smu_base_test


class smu_sep_dbg_gating_test(smu_base_test):
    """Require JTAG2AXI to be launched or blocked per the lifecycle state.

    Shared body: not a test itself. The testlist names one module per eFuse
    image, each a subclass in its own file, so the module a testlist entry names
    ends in that entry's name.
    """

    async def run_scenario(self) -> None:
        await SmuSepDbgGatingSeq(self).run()
