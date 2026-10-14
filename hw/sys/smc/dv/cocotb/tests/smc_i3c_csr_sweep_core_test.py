# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Register sweep of the base, PIO and standby controller blocks of all six I3C instances.

Sources: the pinned i3c-core RDL, the generated I3C wrapper map and smc_addr.h.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_i3c_csr_sweep_core_test_seq import smc_i3c_csr_sweep_core_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_i3c_csr_sweep_core_test(smc_base_test):
    """Reset, read-only, read-write, write-one-to-clear and isolation sweep over SEP_IN."""

    required_evidence = (
        "CHK-I3C-SWEEP-RESET-READ",
        "CHK-I3C-SWEEP-RO-IGNORED",
        "CHK-I3C-SWEEP-RW-ROUNDTRIP",
        "CHK-I3C-SWEEP-W1C-CLEAR",
        "CHK-I3C-SWEEP-INSTANCE-ISOLATION",
        "CHK-NONVAC",
    )
    min_evidence = 6

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_i3c_csr_sweep_core_test_seq("smc_i3c_csr_sweep_core_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
