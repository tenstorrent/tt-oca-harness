# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Run the SEP<->SMC bidirectional handshake under the OSS SMU wrapper."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_bidirect_seq import SmuSepBidirectSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_bidirect_test(smu_base_test):
    """Require both SEP->SMC and SMC->SEP directions to complete."""

    async def run_scenario(self) -> None:
        await SmuSepBidirectSeq(self).run()
