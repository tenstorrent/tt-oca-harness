# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP debug-bus producer and SMC DFD-arm consumer under the SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_debug_bus_seq import SmuSepDebugBusSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_debug_bus_test(smu_base_test):
    """Classify the debug-bus pair by the SEP terminal loop."""

    async def run_scenario(self) -> None:
        await SmuSepDebugBusSeq(self).run()
