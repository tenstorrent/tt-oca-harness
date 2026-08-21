# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART/SPI/log-engine representative CSR precheck."""

from __future__ import annotations

from .smc_addr_map import smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

# Reset content, identical on Verilator and VCS. Most values are RDL reset
# constants (uart_16550_main.rdl / log_engine.rdl):
#   UART_IIR=0x01 (INTERRUPT_PENDING reset 0x1), LSR=0x60 (THRE|TEMT reset),
#   UART_LOG_ENGINE_CTRL / LOG_ENGINE CTRL & INTR_STATUS = 0 -> G3 spec-anchored.
# EXCEPTION (regression-lock, NOT RDL-traceable): UART_MSR=0x11 -- every MSR
# field's RDL reset is 0x0; the 0x11 (DCTS|CTS) is driven by the tied modem-
# status HW inputs (cts_ni ...), so it locks observed HW behaviour, not a spec
# reset.
UART_LOG_READS = [
    ("UART_LOG_ENGINE_CTRL", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
        0), 0x0),
    ("UART_IIR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", 0), 0x1),
    ("UART_LSR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", 0),
     0x0000_0060),
    ("UART_MSR", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR", 0),
     0x0000_0011),  # regression-lock (tied modem HW, RDL=0)
    ("LOG_ENGINE_CTRL", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_CTRL_BASE_ADDR",
        0), 0x0),
    ("LOG_ENGINE_INTR_STATUS", smc_indexed_addr(
        "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_LOG_ENGINE_INTR_STATUS_BASE_ADDR",
        0), 0x0),
]


class smc_uart_spi_log_engine_test_seq(SmcCsrSeq):
    """Use UART/log-engine CSRs as the low-speed peripheral representative."""

    def __init__(self, name: str = "smc_uart_spi_log_engine_test_seq") -> None:
        super().__init__(name)

    async def body(self) -> None:
        await self.csr_read_many(UART_LOG_READS)
        assert self.accesses == len(UART_LOG_READS), "UART/log CSR precheck mismatch"
