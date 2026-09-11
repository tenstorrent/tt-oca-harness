# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP-driven SMC bring-up plus the SEP<->SMC crossbar handshake."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_sep_smc_xbar_seq import SmuSepSmcXbarSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_sep_smc_xbar_test(smu_base_test):
    """Require the SEP to boot the SMC from SRAM and complete the handshake."""

    async def run_scenario(self) -> None:
        await SmuSepSmcXbarSeq(self).run()
