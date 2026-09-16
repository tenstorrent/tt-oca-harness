# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Prove the lifecycle posture enforces debug gating on JTAG2AXI."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_dbg_gating_seq import SmuSepDbgGatingSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_dbg_gating_test(smu_base_test):
    """Require JTAG2AXI to be launched or blocked per the lifecycle state."""

    async def run_scenario(self) -> None:
        await SmuSepDbgGatingSeq(self).run()
