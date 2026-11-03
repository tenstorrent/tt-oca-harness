# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Output remaps leave AxPROT unchanged; each outbound path leaves with its own AxUSER source ID."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_outremap_prot_srcid_test_seq import smc_outremap_prot_srcid_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_outremap_prot_srcid_test(smc_base_test):
    """JTAG accesses with all eight AxPROT values through the remaps and the direct path."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-PROT-AFTER-REMAPS",
        "CHK-PROT-DIRECT",
        "CHK-PROT-MMODE",
        "CHK-PROT-XVISOR",
        "CHK-SRCID-DIRECT-0X3",
        "CHK-SRCID-MMODE-0XC",
        "CHK-SRCID-XVISOR-0X0",
        "CHK-TIMEOUT-PATHS",
        "CHK-VALID0-SRCID-MMODE-0XC",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outremap_prot_srcid_test_seq("smc_outremap_prot_srcid_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses + seq.jtag_accesses >= 81, "fewer accesses than the required floor"
