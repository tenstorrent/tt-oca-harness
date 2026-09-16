# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""ext_in master + real SEP and SMC firmware, all three parties live."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_ext_axi_seq import SmuSepExtAxiSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_ext_axi_test(smu_base_test):
    async def run_scenario(self) -> None:
        await SmuSepExtAxiSeq(self).run()
