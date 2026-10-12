# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""OCTS register decode, reset values, read-back, read-only writes and the aperture edge."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_octs_csr_access_test_seq import smc_octs_csr_access_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_octs_csr_access_test(smc_base_test):
    """Read, write and decode the nine OCTS registers over SEP_IN on the PRIMARY strap."""

    required_evidence = (
        "CHK-OCTS-RESET-VALUES",
        "CHK-OCTS-CTRL-PRESET-READBACK",
        "CHK-OCTS-GPIO-ENABLE-RW",
        "CHK-OCTS-DECODE-OFFSETS",
        "CHK-OCTS-READONLY-START",
        "CHK-OCTS-APERTURE-PAST",
        "CHK-NONVAC",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_octs_csr_access_test_seq("smc_octs_csr_access_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
