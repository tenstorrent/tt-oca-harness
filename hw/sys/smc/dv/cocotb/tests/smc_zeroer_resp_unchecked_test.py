# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Zeroer jobs whose write responses carry SLVERR, DECERR or a mix.

Sources hw/sys/smc/doc/zeroer.adoc (Outstanding Transaction Management, Status Features).
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_resp_unchecked_test_seq import smc_zeroer_resp_unchecked_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, independent of the sequence's own counter:
#   6 output-fabric pass-all filter writes                               6
#   DEST_ADDR and SIZE written and read back                             4
#   one start write, one STATUS poll and one CTRL_STATUS read per run    18
#   SIZE and DEST_ADDR cleared, SIZE read back                           3
ZEROER_RESP_UNCHECKED_MIN_CSR_ACCESSES = 31


@pyuvm.test()
class smc_zeroer_resp_unchecked_test(smc_base_test):
    """Complete multi-burst zeroer jobs under SLVERR, DECERR and mixed B responses."""

    required_evidence = (
        "CHK-NONVAC",
        "CHK-ZEROER-DECERR-ALL-COMPLETES",
        "CHK-ZEROER-MIXED-RESP",
        "CHK-ZEROER-SLVERR-COMPLETES",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_resp_unchecked_test_seq("smc_zeroer_resp_unchecked_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_RESP_UNCHECKED_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=f"{seq.runs} injected-response zeroer job(s) completed",
        )
