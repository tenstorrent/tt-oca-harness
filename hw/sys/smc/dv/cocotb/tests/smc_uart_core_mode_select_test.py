# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The UART mode selectors no leaf drives: FIFOs off, DMA mode 1, line loopback.

On all four wrappers: turn the FIFOs off with a character unread and send two
more through the receiver buffer register, then select DMA mode 1 with the
receive trigger at four characters and check the reception timeout below the
trigger and the round trip with it reached. On wrapper 0, whose receive pad the
testbench drives: set MCR.LINE_LOOPBACK, check the four MSR level bits read 0
and that nothing is received, and burst more characters than the transmit FIFO
holds so it fills and drains.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_core_mode_select_test_seq import smc_uart_core_mode_select_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. Every leg polls, so the real
# count is higher and depends on the baud rate.
#
# 4 wrappers, at least 55 SEP_IN AXI accesses each:
#   UART setup and restore                                              10 + 8
#   receiver-buffer leg: the parked character and its poll, FCR off, IIR,
#     LSR, then per character a THR write, a poll and an RBR read, the
#     drained LSR read, FCR on, IIR and its LSR read              5 + 3 x 2 + 4
#   DMA-mode leg: FCR, IER, the timed-out character with its poll, its IIR
#     poll, its RBR read and the drained IIR, then four characters with a
#     drain poll each, one IIR poll, four RBR reads, IER and FCR
#                                                        7 + 2 x 4 + 1 + 4 + 2
#
# plus 77 on wrapper 0 for the line-loopback leg: the divisor change, MCR, FCR,
# two MSR reads, the quiet character and its drain poll, the 64-character burst
# and the two LSR reads around it, and the MCR restore.
UART_CORE_MODE_SELECT_MIN_CSR_ACCESSES = 4 * 55 + 77


@pyuvm.test()
class smc_uart_core_mode_select_test(smc_base_test):
    """Drive the UART mode selectors no other leaf moves, and check each one."""

    required_evidence = (
        "CHK-UART-DMA-MODE-1",
        "CHK-UART-LINE-LOOPBACK",
        "CHK-UART-RBR-PATH",
        "CHK-UART-RX-TIMEOUT",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_core_mode_select_test_seq("smc_uart_core_mode_select_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            min_csr_accesses=UART_CORE_MODE_SELECT_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.uarts} UARTs, {seq.rbr_bytes} bytes through RBR, "
                f"{seq.dma_bytes} bytes in DMA mode 1, {seq.timeout_legs} timeout legs, "
                f"{seq.line_loopback_legs} line-loopback leg with {seq.burst_bytes} "
                f"burst characters"
            ),
        )
