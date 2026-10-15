# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""smc_beu_csr_access_test: BEU register access over SEP_IN.

Sources: hw/sys/smc/regs/blocks/bus_error_unit/bus_error_unit.rdl, hw/sys/smc/doc/cpu.adoc,
hw/sys/smc/doc/memmap.adoc, hw/sys/smc/doc/fabric.adoc (REGION_SIZE).
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_beu_csr_access_test_seq import smc_beu_csr_access_test_seq
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_beu_csr_access_test(smc_base_test):
    """Drive the four BEU register blocks over SEP_IN across the REGION_SIZE aperture."""

    required_evidence = (
        "CHK-BEU-ACCRUED",
        "CHK-BEU-CAUSE-PHYS",
        "CHK-BEU-DECERR-RESET",
        "CHK-BEU-ENABLE-B2B",
        "CHK-BEU-ENABLE-RESET",
        "CHK-BEU-INDEPENDENT",
        "CHK-BEU-INFLIGHT",
        "CHK-BEU-RESERVED-BITS",
        "CHK-BEU-WIDENED-REACH",
        "CHK-NONVAC",
        "CHK-TIMEOUT-PATHS",
    )
    min_evidence = 11

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_beu_csr_access_test_seq("beu_csr_access_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        for token in self.required_evidence:
            assert token in seq.chk_seen, f"missing CHK token {token} (seen={sorted(seq.chk_seen)})"
