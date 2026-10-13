# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Output remaps leave AxPROT unchanged; the AxUSER source ID of each path is observed."""

from __future__ import annotations

import pyuvm
from seq_lib.smc_outremap_prot_srcid_test_seq import smc_outremap_prot_srcid_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_outremap_prot_srcid_test(smc_base_test):
    """JTAG accesses with all eight AxPROT values through the remaps and the direct path."""

    required_evidence = (
        "CHK-PROT-MMODE",
        "CHK-PROT-XVISOR",
        "CHK-PROT-DIRECT",
        "CHK-PROT-AFTER-REMAPS",
        "CHK-SRCID-DIRECT-OBSERVE",
        "CHK-SRCID-MMODE-OBSERVE",
        "CHK-SRCID-XVISOR-OBSERVE",
        "CHK-VALID0-SRCID-OBSERVE",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 10

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_outremap_prot_srcid_test_seq("smc_outremap_prot_srcid_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.accesses + seq.jtag_accesses >= 81, "fewer accesses than the contract floor"
