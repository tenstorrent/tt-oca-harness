# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART, divisor-latch and log-engine register cycles on all four wrappers.

Drives the six writable UART 16550 registers and the log engine's INTR_ENABLE
to all-ones and all-zeros through half-register writes, exercises both divisor
latches behind LCR.DLAB, raises and clears the INTR_STATUS events the
write-only INTR_TEST fields map to, and gives all 16 LOG_CTRL elements of each
wrapper an index-unique log length read back while they are co-resident.
"""

from __future__ import annotations

import pyuvm
from env.smc_protocol_vip_item import SmcProtocolVipKind
from seq_lib.smc_uart_log_engine_field_sweep_test_seq import (
    smc_uart_log_engine_field_sweep_test_seq,
)
from smc_base_test import smc_base_test

# Directed stimulus floor, written out here rather than read back from
# `seq.accesses`: a floor derived from the sequence's own counter shrinks with a
# sequence that silently stopped issuing accesses.
#
# 4 uart_log_engine_wrap instances, 171 SEP_IN AXI accesses each:
#   six UART register cycles: reset read, 2x(half write + readback) for the
#     ones pattern, the same for the zeros pattern, 2 restore writes, restore
#     read -- 12 each                                                        72
#   divisor-latch leg: DLAB set and its readback, both latches written and read
#     back, DLAB cleared with its readback and the IER read at the aliased
#     address, DLAB raised again, both latches re-read, both restored and
#     re-read, DLAB cleared with its readback                                18
#   log engine INTR_ENABLE cycle                                             12
#   log engine INTR_TEST pulse leg: the clear-state read, the test write, the
#     raised read, the clearing write and the cleared read                    5
#   LOG_CTRL: 16 elements x (signature write, co-resident readback, restore
#     write, restore readback)                                               64
UART_LOG_ENGINE_FIELD_SWEEP_MIN_CSR_ACCESSES = 4 * 171


@pyuvm.test()
class smc_uart_log_engine_field_sweep_test(smc_base_test):
    """Cycle the UART, divisor-latch and log-engine registers on every wrapper."""

    required_evidence = (
        "CHK-LOG-ENGINE-INTR-SWEEP",
        "CHK-LOG-ENGINE-LOG-CTRL-SWEEP",
        "CHK-UART-16550-DL-WINDOW",
        "CHK-UART-16550-FIELD-SWEEP",
    )
    min_evidence = 4

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        seq = smc_uart_log_engine_field_sweep_test_seq("smc_uart_log_engine_field_sweep_test_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        await self.record_protocol_vip(
            SmcProtocolVipKind.UART_LOG,
            type(self).__name__,
            min_csr_accesses=UART_LOG_ENGINE_FIELD_SWEEP_MIN_CSR_ACCESSES,
            csr_accesses=seq.accesses,
            proxy=False,
            details=(
                f"{seq.registers_swept} register cycles, {seq.dl_legs} divisor-latch legs, "
                f"{seq.pulses} INTR_TEST pulses, {seq.log_ctrl_elements} LOG_CTRL elements"
            ),
        )
