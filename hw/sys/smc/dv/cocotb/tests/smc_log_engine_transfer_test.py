# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A real log-engine transfer on all four uart_log_engine_wrap instances.

Loads four logs into the SPM log region of each wrapper, each filling its whole
slot so its fetch takes more than one beat, points the engine at them and at
the wrapper's own UART transmit holding register, puts that UART in MCR.LOOP,
triggers all four LOG_CTRL elements at once, and reads the byte stream back out
of RBR. The compare is the received stream against the bytes written into
memory, the LOG_CTRL lengths hardware cleared, and an INTR_STATUS that stayed
clear.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_log_engine_transfer_test_seq import smc_log_engine_transfer_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. The drain loop polls LSR, so
# the real count is higher and depends on the baud rate.
#
# 4 wrappers, at least 191 SEP_IN AXI accesses each:
#   the four two-word logs written into their slots and read back            16
#   UART setup: pad-mux enable, DLAB, both divisor latches, the 8-bit line
#     control, MCR.LOOP, the FIFO control, IER, the MCR readback and the
#     quiet-receiver read                                                    10
#   engine setup: disable, region size, both halves of the region address,
#     the write address, the INTR_STATUS clear and its readback, INTR_ENABLE,
#     enable and its readback                                                10
#   the idle read and the trigger write of each of the four elements          8
#   at least one LSR read and one RBR read for each of the 64 bytes         128
#   at least one LOG_CTRL read per element                                    4
#   the quiet LSR read and the final INTR_STATUS read                         2
#   the engine half of the restore, then the UART half                    5 + 8
LOG_ENGINE_TRANSFER_MIN_CSR_ACCESSES = 4 * 191


@pyuvm.test()
class smc_log_engine_transfer_test(smc_base_test):
    """Run a real log transfer through every wrapper's engine and UART."""

    required_evidence = (
        "CHK-LOG-ENGINE-TRANSFER-BYTES",
        "CHK-LOG-ENGINE-TRANSFER-CLEAN",
        "CHK-LOG-ENGINE-TRANSFER-HWCLR",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_transfer_test_seq("smc_log_engine_transfer_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            min_csr_accesses=LOG_ENGINE_TRANSFER_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.transfers} wrapper transfers, {seq.bytes_checked} log bytes compared, "
                f"{seq.hwclr_elements} LOG_CTRL elements cleared by hardware"
            ),
        )
