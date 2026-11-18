# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART baud, word length, and parity."""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_baud_word_parity_format_test_seq import (
    smc_uart_baud_word_parity_format_test_seq,
)
from smc_base_test import smc_base_test


@pyuvm.test()
class smc_uart_baud_word_parity_format_test(smc_base_test):
    """UART0 divisor x frame-format sweep decoded on the TX pad and driven on the RX pad."""

    required_evidence = (
        "CHK-UART-BAUD-BASIC",
        "CHK-UART-BAUD-FMT",
        "CHK-UART-FMT-FE-ASSERTS",
        "CHK-UART-FMT-PE-ASSERTS",
        "CHK-UART-RX-GLITCH-REJECT",
        "CHK-UART-STB5-SECOND-STOP-IGNORED",
        "CHK-UART-STB5-TX-STOP-LENGTH",
    )
    min_evidence = 7

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_baud_word_parity_format_test_seq("uart_baud_fmt_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        assert seq.combos_ok == 32, f"expected 32 combos got {seq.combos_ok}"
        assert len(seq.frame_lengths_ps) == 32, "not every combo measured its frame length"
        assert seq.pe_asserted and seq.fe_asserted, "PE/FE error controls did not assert"
        assert seq.stb5_tx_cells == 4, f"expected 4 5-bit STB=1 TX cells got {seq.stb5_tx_cells}"
        assert seq.stb5_rx_legs == 2, f"expected 2 second-stop-bit legs got {seq.stb5_rx_legs}"
        assert seq.glitch_frames == 32, f"expected 32 glitch frames got {seq.glitch_frames}"
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            # Stimulus floor, literal here rather than read from `seq.accesses`: each combo
            # issues 8 programming writes, 3 THR writes and at least an LSR poll and an RBR
            # read (32 x 13 = 416); the LSR polls are timing-dependent, so the floor sits below.
            min_csr_accesses=400,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"baud/format combos={seq.combos_ok} decoded on the TX pad and read back from "
                f"the RX pad; PE/FE asserted at both divisors; 5-bit STB=1 TX frames pinned to "
                f"2 stop bits and the low second stop bit ignored on receive; "
                f"{seq.glitch_frames} single-clock glitch frames read back intact"
            ),
        )
