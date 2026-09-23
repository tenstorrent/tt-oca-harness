# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""A log-engine transfer halted part-way by clearing the engine enable.

On each of the four wrappers: start a transfer of a whole slot, clear
`CTRL.EN` once bytes are reaching the receiver, drain until the UART reports
itself idle and require fewer than the whole log to have arrived with nothing
following, then put a shorter length in the same element while the engine is
still disabled, re-enable it, and require exactly those bytes and the hardware
clear.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_log_engine_abort_test_seq import smc_log_engine_abort_test_seq
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses. The drains poll LSR, so the
# real count is higher and depends on the baud rate.
#
# 4 wrappers, at least 188 SEP_IN AXI accesses each:
#   the eight log words written into the slot and read back                  16
#   UART setup                                                               10
#   engine setup                                                             10
#   the element's idle read and its trigger write                             2
#   one poll to see the first byte reach the receiver                         1
#   the disable write                                                         1
#   the abort drain: at least one byte and the idle run                      34
#   the second drain: the idle run alone                                     32
#   the preserved-length read                                                 1
#   the re-trigger write and the re-enable write                              2
#   the re-triggered 16 bytes and their idle run                             64
#   one hardware-clear poll and the final INTR_STATUS read                    2
#   the engine half of the restore, then the UART half                    5 + 8
LOG_ENGINE_ABORT_MIN_CSR_ACCESSES = 4 * 188


@pyuvm.test()
class smc_log_engine_abort_test(smc_base_test):
    """Halt a log transfer with CTRL.EN and bring the engine back."""

    required_evidence = (
        "CHK-LOG-ENGINE-ABORT-HALTED",
        "CHK-LOG-ENGINE-ABORT-LENGTH-KEPT",
        "CHK-LOG-ENGINE-ABORT-RETRIGGER",
    )
    min_evidence = 3

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_log_engine_abort_test_seq("smc_log_engine_abort_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            min_csr_accesses=LOG_ENGINE_ABORT_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.aborts} halted transfers, bytes moved before each disable "
                f"{seq.moved_before_disable}, {seq.retriggers} re-triggered transfers"
            ),
        )
