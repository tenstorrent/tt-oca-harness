# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Firmware-driven SEP lifecycle flow, traced to SMC and DTP."""

from __future__ import annotations

import pyuvm

from seq_lib.smu_sep_lcc_flow_seq import SmuSepLccFlowSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_lcc_flow_test(smu_base_test):
    """Require the demote posture to reach every LCC consumer."""

    async def run_scenario(self) -> None:
        await SmuSepLccFlowSeq(self).run()
