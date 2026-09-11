# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 MCR.LOOP sweep of baud × WLS/STB/parity; RX matches TX masked to word length."""

from __future__ import annotations

from pathlib import Path

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import UART_CG_EN, _field_mask, smc_addr, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq

_REPO = Path(__file__).resolve().parents[6]
_UART_H = _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_main.h"
_UART_WO_H = (
    _REPO / "hw" / "ip" / "uart" / "uart_16550" / "regs" / "gen" / "c" / "uart_16550_main_wo.h"
)
_UART_CTRL_H = (
    _REPO
    / "hw"
    / "ip"
    / "uart"
    / "uart_log_engine_wrap"
    / "regs"
    / "gen"
    / "c"
    / "uart_log_engine_ctrl.h"
)

UART_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
    0,
)
UART_RBR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", 0)
UART_IER = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", 0)
UART_IIR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", 0)
UART_LCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR", 0)
UART_MCR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR", 0)
UART_LSR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", 0)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
FCR_FIFO_ENABLE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
IER_ERBFI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ERBFI_bm")
IER_ETBEI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ETBEI_bm")
IER_ELSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ELSI_bm")
IER_EDSSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__EDSSI_bm")
IIR_INTERRUPT_PENDING = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS_BM = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
LCR_WLS_BP = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bp")
LCR_STB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__STB_bm")
LCR_PEN = _field_mask(_UART_H, "UART_16550_MAIN__LCR__PEN_bm")
LCR_EPS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__EPS_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_PE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__PE_bm")
LSR_FE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__FE_bm")
LSR_BI = _field_mask(_UART_H, "UART_16550_MAIN__LSR__BI_bm")

_INTR_RDR = 0x2
_IER_BASIC = IER_ERBFI | IER_ETBEI | IER_ELSI | IER_EDSSI
_DIVISORS = (1, 8)
# (wls, stb, pen, eps); stick parity excluded.
_FRAME_CFGS = (
    (0, 0, 0, 0),
    (0, 1, 0, 0),
    (0, 0, 1, 0),
    (0, 1, 1, 1),
    (1, 0, 0, 0),
    (1, 1, 0, 0),
    (1, 0, 1, 0),
    (1, 1, 1, 1),
    (2, 0, 0, 0),
    (2, 1, 0, 0),
    (2, 0, 1, 0),
    (2, 1, 1, 1),
    (3, 0, 0, 0),
    (3, 1, 0, 0),
    (3, 0, 1, 0),
    (3, 0, 1, 1),
)
_TX_BYTE = 0x5A


def _iir_id(iir: int) -> int:
    return (int(iir) & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


def _iir_pending(iir: int) -> bool:
    return (int(iir) & IIR_INTERRUPT_PENDING) == 0


class smc_uart_baud_word_parity_format_test_seq(SmcCsrSeq):
    """UART0 loopback baud/word/parity format sweep."""

    def __init__(self, name: str = "smc_uart_baud_word_parity_format_test_seq") -> None:
        super().__init__(name)
        self.combos_ok: int = 0

    async def _program(self, divisor: int, wls: int, stb: int, pen: int, eps: int) -> None:
        await self.csr_write("MCR_LOOP", UART_MCR, MCR_LOOP | MCR_RTS)
        await self.csr_write("LCR_DLAB", UART_LCR, LCR_DLAB)
        await self.csr_write("DLL", UART_RBR, divisor & 0xFF)
        await self.csr_write("DLH", UART_IER, (divisor >> 8) & 0xFF)
        lcr = ((wls & 0x3) << LCR_WLS_BP) & LCR_WLS_BM
        if stb:
            lcr |= LCR_STB
        if pen:
            lcr |= LCR_PEN
        if eps:
            lcr |= LCR_EPS
        await self.csr_write("LCR_FMT", UART_LCR, lcr)
        await self.csr_write("IER", UART_IER, _IER_BASIC)
        await self.csr_write("FCR", UART_IIR, FCR_FIFO_ENABLE)

    async def _exchange(
        self, label: str, divisor: int, wls: int, stb: int, pen: int, eps: int
    ) -> None:
        await self._program(divisor, wls, stb, pen, eps)
        word_mask = (1 << (5 + wls)) - 1
        expected = _TX_BYTE & word_mask
        await self.csr_write(f"{label}_THR", UART_RBR, _TX_BYTE)

        iir = 0
        for _ in range(4096):
            iir = await self.csr_read(f"{label}_IIR", UART_IIR)
            if _iir_pending(iir) and _iir_id(iir) == _INTR_RDR:
                break
            await Timer(100, units="ns")
        else:
            raise AssertionError(
                f"{label}: RDR not seen IIR=0x{iir:08x} "
                f"div={divisor} wls={wls} stb={stb} pen={pen} eps={eps}"
            )

        lsr = await self.csr_read(f"{label}_LSR", UART_LSR)
        if lsr & (LSR_PE | LSR_FE | LSR_BI):
            raise AssertionError(f"{label}: unexpected err LSR=0x{lsr:08x} div={divisor} wls={wls}")
        if not (lsr & LSR_DR):
            raise AssertionError(f"{label}: LSR.DR=0 before RBR read")
        rx = await self.csr_read(f"{label}_RBR", UART_RBR)
        rx_b = int(rx) & 0xFF
        if rx_b != expected:
            raise AssertionError(
                f"{label}: RX 0x{rx_b:02x} != expected 0x{expected:02x} "
                f"(tx=0x{_TX_BYTE:02x} mask=0x{word_mask:02x})"
            )
        cocotb.log.info(
            "CHK-UART-BAUD-FMT: div=%d wls=%d stb=%d pen=%d eps=%d rx=0x%02x",
            divisor,
            wls,
            stb,
            pen,
            eps,
            rx_b,
        )

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART_EN", UART_CTRL, UART_EN)

        for divisor in _DIVISORS:
            for wls, stb, pen, eps in _FRAME_CFGS:
                label = f"D{divisor}_W{wls}_S{stb}_P{pen}{eps}"
                await self._exchange(label, divisor, wls, stb, pen, eps)
                self.combos_ok += 1

        expect = len(_DIVISORS) * len(_FRAME_CFGS)
        if self.combos_ok != expect:
            raise AssertionError(f"combo count {self.combos_ok} != {expect}")
        cocotb.log.info("CHK-UART-BAUD-BASIC: combos=%d (div×frame)", self.combos_ok)
