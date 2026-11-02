# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""An SPM write cut by a watchdog warm reset is answered once the reset releases.

Reproducer for #3510: an SPM write burst from SEP_IN is cut by the watchdog
warm reset after its AW handshake and before its B; after the release the cut
write must receive a B, and a fresh SPM write and a `CPU_CTRL` write with the
same AXI ID bits [2:0] must complete OKAY.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_spm_write_cut_by_warm_reset_test_seq import (
    smc_spm_write_cut_by_warm_reset_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_spm_write_cut_by_warm_reset_test(smc_base_test):
    """Cut an SPM write burst with the watchdog warm reset, release it, then grade the port."""

    required_evidence = (
        "CHK-SPM-WRITE-CUT-BY-WARM-RESET-ARM",
        "CHK-SPM-WRITE-CUT-BY-WARM-RESET",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_spm_write_cut_by_warm_reset_test_seq("smc_spm_write_cut_by_warm_reset_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
