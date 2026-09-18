# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""P0 alias for the AVSBus sideband precheck."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_sideband_protocol_smoke_test_seq import (
    smc_sideband_protocol_smoke_test_seq,
)
from seq_lib.smc_sideband_vip_utils import check_sideband_observability
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_sanity_test(smc_base_test):
    """Run the AVSBus sideband proxy scenario."""

    required_evidence = (
        "CHK-AVS-DEBUG-READBACK-NONDESTRUCTIVE",
        "CHK-AVS-FIFOS-STATUS",
        "CHK-AVS-INTERRUPT-MASK",
        "CHK-AVS-INTERRUPT-W1C",
        "CHK-AVS-NORMAL-STATUS",
        "CHK-AVS-READBACK-EMPTY-FIFO-READ",
        "CHK-AVS-READBACK-POINTER-ADVANCE",
        "CHK-AVS-SLAVE-STATUS",
        "CHK-SIDEBAND-OBSERVABILITY",
    )
    min_evidence = 9

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_sideband_protocol_smoke_test_seq("avsbus_sanity_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await check_sideband_observability()
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Directed stimulus floor: 6 SEP_IN AXI AVSBus CSR accesses.
            # Literal here, not read from `seq.accesses`.
            min_csr_accesses=6,
            csr_accesses=seq.accesses,
            proxy=True,
            details="AVSBus CSR decode plus bounded IRQ/state observability",
        )
