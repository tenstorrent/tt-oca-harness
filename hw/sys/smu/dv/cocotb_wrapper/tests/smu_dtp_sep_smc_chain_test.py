# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""End-to-end DTP-SEP-SMC chain with all three subsystems active."""

from __future__ import annotations

import pyuvm
from seq_lib.smu_dtp_sep_smc_chain_seq import SmuDtpSepSmcChainSeq
from smu_base_test import smu_base_test


@pyuvm.test()
class smu_dtp_sep_smc_chain_test(smu_base_test):
    """Require the SEP posture to govern a DTP read that the SMC answers."""

    async def run_scenario(self) -> None:
        await SmuDtpSepSmcChainSeq(self).run()
