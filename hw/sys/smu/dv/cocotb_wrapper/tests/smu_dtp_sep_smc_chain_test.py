# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""End-to-end DTP-SEP-SMC chain with all three subsystems active."""

from __future__ import annotations

from seq_lib.smu_dtp_sep_smc_chain_seq import SmuDtpSepSmcChainSeq
from smu_base_test import smu_base_test


class smu_dtp_sep_smc_chain_test(smu_base_test):
    """Require the SEP posture to govern a DTP read that the SMC answers.

    Shared body: not a test itself. The testlist names one module per eFuse
    image, each a subclass in its own file, so the module a testlist entry names
    ends in that entry's name.
    """

    async def run_scenario(self) -> None:
        await SmuDtpSepSmcChainSeq(self).run()
