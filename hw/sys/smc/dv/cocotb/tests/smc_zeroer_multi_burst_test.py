# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A zeroer job too large for one AXI burst.

Poisons four probe words spanning both halves of a 0x1000-byte region and a
witness word past its end, clears the region with one zeroer job, and requires
both halves to read zero, the witness to keep its poison, CTRL_STATUS.STATUS to
leave and return to its idle level, and the output responder to book at least
the two write transactions the size demands.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_zeroer_multi_burst_test_seq import smc_zeroer_multi_burst_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. The status polls add more.
#
#   6 output-fabric pass-all filter writes                                    6
#   DEST_ADDR and SIZE written and read back                                  4
#   the idle STATUS read and the trigger write                                2
#   at least one STATUS poll for the busy level and one for the return        2
#   the armed CTRL_STATUS readback                                            1
#   SIZE and DEST_ADDR cleared, SIZE read back                                3
ZEROER_MULTI_BURST_MIN_CSR_ACCESSES = 18


@pyuvm.test()
class smc_zeroer_multi_burst_test(smc_base_test):
    """Clear a region larger than one AXI burst and check both halves."""

    required_evidence = (
        "CHK-ZEROER-MULTI-BURST-PRELOAD",
        "CHK-ZEROER-MULTI-BURST-STATUS",
        "CHK-ZEROER-MULTI-BURST-ZEROED",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_zeroer_multi_burst_test_seq("smc_zeroer_multi_burst_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=ZEROER_MULTI_BURST_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            timeouts=seq.timeouts,
            proxy=False,
            details=(
                f"{seq.bursts_observed} output write transaction(s) for the job, "
                f"{seq.checked_bytes} probe bytes read back as zero"
            ),
        )
