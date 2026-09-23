# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Each AVSBus FIFO interrupt source raised and cleared through the write-1 register."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_avsbus_interrupt_sources_test_seq import (
    smc_avsbus_interrupt_sources_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_avsbus_interrupt_sources_test(smc_base_test):
    """Raise each AVSBus FIFO interrupt source and clear it through AVS_INTERRUPT_CLEAR."""

    required_evidence = (
        "CHK-AVS-CMD-FIFO-FULL-INT",
        "CHK-AVS-CMD-FIFO-OVERFLOW-INT",
        "CHK-AVS-INTERRUPT-CLEAR-SOURCES",
        "CHK-AVS-IRQ-UNMASKED",
        "CHK-AVS-READBACK-FIFO-FULL-INT",
        "CHK-AVS-READBACK-HAS-DATA-INT",
        "CHK-AVS-READBACK-UNDERFLOW-INT",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_avsbus_interrupt_sources_test_seq("smc_avsbus_interrupt_sources_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.SIDEBAND,
            type(self).__name__,
            # Directed stimulus floor: the clock-gate save and restore with
            # readbacks, one AVS_CMD write per command FIFO slot plus the
            # overflow write, the status and FIFO reads around each source,
            # one AVS_READBACK read per readback slot, and a clear with its
            # readback per source. Literal here, not read from
            # `seq.accesses`.
            min_csr_accesses=50,
            csr_accesses=seq.accesses,
            proxy=False,
            details="AVSBus FIFO interrupt sources raised and cleared through the write-1 register",
        )
