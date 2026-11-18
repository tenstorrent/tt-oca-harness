# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 FIFO integrity faults: a real parity fault and a real pointer fault.

The 16550's only hardware-detected fault is the storage integrity extension
(`architecture.adoc`, Error Handling): a parity or pointer failure drives
`err_o`, reports IIR id 7 under `IER.EFEI`, and is not repaired by an IIR
read. Every other leaf reaches id 7 through `ITR.TFEI`; this one flips a
stored bit.
"""

from __future__ import annotations

import pyuvm
from seq_lib.smc_uart_fifo_integrity_fault_test_seq import (
    ID_FIFO_ERROR,
    IIR_FIFO_ERROR_PENDING,
    IIR_INTERRUPT_PENDING,
    smc_uart_fifo_integrity_fault_test_seq,
)
from smc_base_test import smc_base_test

# `uart_16550_main.rdl` IIR.INTERRUPT_ID: 0x7 is the FIFO Error Interrupt, and
# with the FIFOs enabled the register reads 0xCE while it is pending.
EXPECTED_ID = 0x7
EXPECTED_IIR = 0xCE


@pyuvm.test()
class smc_uart_fifo_integrity_fault_test(smc_base_test):
    """A flipped parity bit or pointer copy must reach err_o, IIR id 7 and the RAS bit."""

    required_evidence = ("CHK-UART-FIFO-INTG-REAL",)
    min_evidence = 1

    auto_protocol_vip = False

    async def run_scenario(self) -> None:
        assert ID_FIFO_ERROR == EXPECTED_ID and IIR_FIFO_ERROR_PENDING == EXPECTED_IIR, (
            f"the sequence expects id 0x{ID_FIFO_ERROR:x} / IIR 0x{IIR_FIFO_ERROR_PENDING:02x}, "
            f"the RDL gives 0x{EXPECTED_ID:x} / 0x{EXPECTED_IIR:02x}"
        )
        seq = smc_uart_fifo_integrity_fault_test_seq("uart_fifo_integrity_fault_seq")
        await self.start_seq(seq, self.env.sys_axi_agent.sequencer)
        # Gate on the measured values, not on the sequence having run.
        assert seq.iir_enabled == EXPECTED_IIR, (
            f"parity fault under IER.EFEI read IIR {seq.iir_enabled!r}, expected 0x{EXPECTED_IIR:02x}"
        )
        assert seq.iir_masked is not None and (seq.iir_masked & IIR_INTERRUPT_PENDING) != 0, (
            f"IIR {seq.iir_masked!r} reported a pending source with IER.EFEI clear"
        )
        assert seq.iir_reread == (EXPECTED_IIR, EXPECTED_IIR), (
            f"IIR re-reads {seq.iir_reread} did not keep id 0x{EXPECTED_ID:x} pending"
        )
        assert seq.err_after_pop == 0, "err_o stayed high after the faulted entry popped"
        assert seq.err_pointer_fault == 1, "the pointer-copy fault did not raise err_o"
        assert seq.err_after_fifo_reset == 0, "err_o stayed high after FCR.XMIT_FIFO_RESET"
