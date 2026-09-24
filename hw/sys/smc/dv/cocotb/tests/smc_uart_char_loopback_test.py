# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A character through each UART's own loopback, and the registers it moves.

On all four wrappers: drive the write-only FCR both ways and read its effect
out of IIR, send six distinct bytes through the transmit holding register and
compare what comes back out of RBR, check the interrupt identification with a
character waiting and once it is drained, drive the four MCR outputs and check
the MSR levels and sticky deltas the programming guide maps them to, flush the
receive FIFO with the singlepulse reset, and write at the LSR and MSR
addresses to show a read-only register takes no write.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_char_loopback_test_seq import smc_uart_char_loopback_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. The round trip polls LSR, so
# the real count is higher and depends on the baud rate.
#
# 4 wrappers, at least 60 SEP_IN AXI accesses each:
#   UART setup and restore                                              10 + 8
#   FIFO-enable leg: IIR, FCR off, IIR, FCR on, IIR                          5
#   round trip: the idle LSR read, then per byte a THR write, at least one
#     LSR poll and an RBR read, then the quiet LSR read              2 + 3 x 6
#   interrupt-identification leg                                             7
#   modem leg                                                                7
#   receive-FIFO reset leg                                                   5
#   the two writes at the read-only addresses and their readbacks            4
UART_CHAR_LOOPBACK_MIN_CSR_ACCESSES = 4 * 66


@pyuvm.test()
class smc_uart_char_loopback_test(smc_base_test):
    """Send characters through every UART's loopback and check what moves."""

    required_evidence = (
        "CHK-UART-CHAR-LOOPBACK",
        "CHK-UART-FCR-EFFECT",
        "CHK-UART-IIR-RX-READY",
        "CHK-UART-MSR-LOOPBACK",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_char_loopback_test_seq("smc_uart_char_loopback_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            min_csr_accesses=UART_CHAR_LOOPBACK_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.uarts} UARTs, {seq.bytes_checked} bytes round-tripped, "
                f"{seq.intr_legs} interrupt legs, {seq.modem_legs} modem legs"
            ),
        )
