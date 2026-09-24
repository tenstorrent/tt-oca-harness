# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The DMA register block refusing a sub-word write, at every writable register.

At each of the thirteen writable registers: read what it holds, write that
same word back full width and require it to be accepted, write two bytes at
the same address and require an error response, then read again and require
the register unchanged.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_dma_reg_byte_enable_error_test_seq import (
    smc_dma_reg_byte_enable_error_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
#   13 writable registers x (read, full-width write, sub-word write, read)   52
DMA_REG_BYTE_ENABLE_ERROR_MIN_CSR_ACCESSES = 13 * 4


@pyuvm.test()
class smc_dma_reg_byte_enable_error_test(smc_base_test):
    """Refuse a sub-word write at every writable DMA register."""

    required_evidence = (
        "CHK-DMA-REG-BYTE-ENABLE-ERROR",
        "CHK-DMA-REG-REFUSED-WRITE-NO-EFFECT",
    )
    min_evidence = 2

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_dma_reg_byte_enable_error_test_seq("smc_dma_reg_byte_enable_error_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.ZEROER_DMA,
            type(self).__name__,
            min_csr_accesses=DMA_REG_BYTE_ENABLE_ERROR_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers_checked} writable DMA registers refused a sub-word write "
                f"and read back unchanged"
            ),
        )
