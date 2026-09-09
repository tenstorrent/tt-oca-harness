# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""U4-1: DUT UART0 TX capture (THR -> pad12 -> OcahUartConsole sink)."""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles

from .smc_addr_map import UART_CG_EN, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_uart_protocol_vip import SmcUartVip, SmcUartVipError

# UART_LOG_ENGINE_WRAP_0 (PeakRDL)
UART_LOG_ENGINE_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
    0,
)
UART0_THR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", 0
)  # also THR / DLL (DLAB)
UART0_IER = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", 0)
UART0_LCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR", 0)
UART0_LSR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", 0)

CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

UART_EN = 0x1
LCR_DLAB = 0x80
LCR_8N1 = 0x03  # WLS=8, no parity, 1 stop
TX_BYTE = 0xA5
BAUD = 115200


class smc_uart_loopback_test_seq(SmcCsrSeq):
    """Program UART0 16550 and capture one DUT TX byte on pad 12."""

    def __init__(self, name: str = "smc_uart_loopback_test_seq") -> None:
        super().__init__(name)
        self.captured: int | None = None
        self.divisor: int = 0

    async def body(self) -> None:
        # start_seq assigns seq.cfg = env.cfg (includes randomized periph period).
        periph_ns = int(getattr(self.cfg, "periph_clk_period_ns", 10) or 10)
        # Baud generator divides by (divisor + 1); divisor 0 disables TX/RX.
        self.divisor = max(1, int(round(1.0 / ((periph_ns * 1e-9) * 16 * BAUD))) - 1)
        cocotb.log.info(
            "UART DUT TX: periph_clk=%dns baud=%d divisor=%d",
            periph_ns,
            BAUD,
            self.divisor,
        )

        cg = await self.csr_read("UART_CG_SAVE", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART_EN", UART_LOG_ENGINE_CTRL, UART_EN)

        # Baud + 8N1 via DLAB.
        await self.csr_write("UART0_LCR_DLAB", UART0_LCR, LCR_8N1 | LCR_DLAB)
        await self.csr_write("UART0_DLL", UART0_THR, self.divisor & 0xFF)
        await self.csr_write("UART0_DLM", UART0_IER, (self.divisor >> 8) & 0xFF)
        await self.csr_write("UART0_LCR_8N1", UART0_LCR, LCR_8N1)

        # Allow divisor reload to settle.
        await ClockCycles(cocotb.top.clk_smc_i, max(64, self.divisor * 16))

        try:
            vip = SmcUartVip(baud=BAUD)
        except SmcUartVipError as exc:
            raise AssertionError(f"UART VIP bind failed: {exc}") from exc

        await self.csr_write("UART0_THR", UART0_THR, TX_BYTE)
        # One 8N1 frame ~= 87 us @ 115200; allow generous margin.
        self.captured = await vip.capture_frame(timeout_us=5000)
        assert self.captured == TX_BYTE, (
            f"DUT UART0 TX mismatch: got 0x{self.captured:02X}, "
            f"expected 0x{TX_BYTE:02X} (divisor={self.divisor})"
        )
        cocotb.log.info(
            "UART DUT TX OK: THR 0x%02X captured on pad12 @ %d baud",
            self.captured,
            BAUD,
        )

        await self.csr_write("UART_CG_RESTORE", CLOCK_GATE_CONTROL, cg)
