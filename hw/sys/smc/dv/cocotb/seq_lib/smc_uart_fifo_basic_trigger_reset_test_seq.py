# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 MCR.LOOP: RCVR trigger then RX/TX FIFO reset clears LSR.DR / THRE."""

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
FCR_RCVR_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_FIFO_RESET_bm")
FCR_XMIT_FIFO_RESET = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__XMIT_FIFO_RESET_bm")
FCR_RCVR_TRIGGER_BP = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_TRIGGER_bp")
IIR_INTERRUPT_PENDING = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
IER_ERBFI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ERBFI_bm")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_THRE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__THRE_bm")
LSR_TEMT = _field_mask(_UART_H, "UART_16550_MAIN__LSR__TEMT_bm")

# 16550 IntrID encodings (IIR[3:1])
_INTR_ID_RDR = 0x2
_INTR_ID_CHAR_TIMEOUT = 0x6
_TRIG_1B = 0
_TRIG_4B = 1


def _iir_id(iir: int) -> int:
    return (int(iir) & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


def _iir_pending(iir: int) -> bool:
    # Active-low: 0 means an interrupt is pending.
    return (int(iir) & IIR_INTERRUPT_PENDING) == 0


class smc_uart_fifo_basic_trigger_reset_test_seq(SmcCsrSeq):
    """UART0 loopback FIFO trigger + reset proof."""

    def __init__(self, name: str = "smc_uart_fifo_basic_trigger_reset_test_seq") -> None:
        super().__init__(name)
        self.trigger_1b_ok: bool = False
        self.trigger_4b_ok: bool = False
        self.reset_ok: bool = False

    async def _write_fcr(self, value: int) -> None:
        await self.csr_write("UART0_FCR", UART_IIR, value)

    async def _fifo_set_trigger(self, trigger_cfg: int) -> None:
        fcr = FCR_FIFO_ENABLE | ((trigger_cfg & 0x3) << FCR_RCVR_TRIGGER_BP)
        await self._write_fcr(fcr)

    async def _fifo_reset(self, *, rx: bool, tx: bool) -> None:
        fcr = FCR_FIFO_ENABLE
        if rx:
            fcr |= FCR_RCVR_FIFO_RESET
        if tx:
            fcr |= FCR_XMIT_FIFO_RESET
        await self._write_fcr(fcr)

    async def _init_loopback(self) -> None:
        await self.csr_write("UART_EN", UART_CTRL, UART_EN)
        # Divisor=1 (fast loopback), 8N1, LOOP+RTS, ERBFI.
        await self.csr_write("LCR_DLAB", UART_LCR, LCR_WLS | LCR_DLAB)
        await self.csr_write("DLL", UART_RBR, 1)
        await self.csr_write("DLH", UART_IER, 0)
        await self.csr_write("LCR_8N1", UART_LCR, LCR_WLS)
        await self.csr_write("MCR_LOOP", UART_MCR, MCR_LOOP | MCR_RTS)
        await self.csr_write("IER_ERBFI", UART_IER, IER_ERBFI)

    async def _wait_iir_id(self, label: str, expect_id: int, iters: int = 256) -> int:
        iir = 0
        for _ in range(iters):
            iir = await self.csr_read(f"{label}_IIR", UART_IIR)
            if _iir_pending(iir) and _iir_id(iir) == expect_id:
                return iir
            await Timer(1, units="us")
        raise AssertionError(
            f"{label}: IIR id=0x{expect_id:x} not seen last=0x{iir:08x} "
            f"pending={_iir_pending(iir)} id=0x{_iir_id(iir):x}"
        )

    async def _test_rx_trigger(self, label: str, trig_cfg: int, depth: int) -> None:
        await self._fifo_reset(rx=True, tx=True)
        await self._fifo_set_trigger(trig_cfg)
        await self.csr_read(f"{label}_LSR_CLR", UART_LSR)
        await self.csr_read(f"{label}_IIR_CLR", UART_IIR)

        for i in range(1, depth + 2):
            await self.csr_write(f"{label}_THR_{i}", UART_RBR, 0x30 + i)

        await self._wait_iir_id(f"{label}_TO", _INTR_ID_CHAR_TIMEOUT)
        cocotb.log.info(
            "CHK-UART-FIFO-TRIG-%s: RECEPTION_TIMEOUT after %d writes (thresh=%d)",
            label,
            depth + 1,
            depth,
        )
        await self.csr_read(f"{label}_RBR_POP", UART_RBR)
        await self._wait_iir_id(f"{label}_RDR", _INTR_ID_RDR)
        cocotb.log.info(
            "CHK-UART-FIFO-TRIG-%s: RECEIVED_DATA_READY after timeout clear",
            label,
        )

    async def _test_fifo_reset(self) -> None:
        await self._fifo_reset(rx=True, tx=True)
        await self._fifo_set_trigger(_TRIG_1B)
        for i in range(4):
            await self.csr_write(f"RST_THR_{i}", UART_RBR, 0x40 + i)

        lsr = 0
        for _ in range(512):
            lsr = await self.csr_read("RST_TEMT_WAIT", UART_LSR)
            if lsr & LSR_TEMT:
                break
            await Timer(1, units="us")
        else:
            raise AssertionError(f"TEMT not set before RX reset LSR=0x{lsr:08x}")

        lsr = 0
        for _ in range(512):
            lsr = await self.csr_read("RST_DR_WAIT", UART_LSR)
            if lsr & LSR_DR:
                break
            await Timer(1, units="us")
        else:
            raise AssertionError(f"LSR.DR=0 before RX reset LSR=0x{lsr:08x}")
        lsr = await self.csr_read("RST_DR_PRE", UART_LSR)
        if not (lsr & LSR_DR):
            raise AssertionError(f"LSR.DR cleared before RX reset LSR=0x{lsr:08x}")
        await self._fifo_reset(rx=True, tx=False)
        lsr = await self.csr_read("RST_DR_POST", UART_LSR)
        if lsr & LSR_DR:
            raise AssertionError(f"LSR.DR still set after RX reset LSR=0x{lsr:08x}")
        iir = await self.csr_read("RST_IIR_POST", UART_IIR)
        if _iir_pending(iir) and _iir_id(iir) == _INTR_ID_RDR:
            raise AssertionError(f"RDR still pending after RX reset IIR=0x{iir:08x}")
        cocotb.log.info("CHK-UART-FIFO-RST-RX: DR cleared after RCVR_FIFO_RESET")

        # Slow divisor so TX FIFO holds data for THRE==0 sample.
        await self.csr_write("LCR_DLAB_SLOW", UART_LCR, LCR_WLS | LCR_DLAB)
        await self.csr_write("DLL_SLOW", UART_RBR, 32)
        await self.csr_write("DLH_SLOW", UART_IER, 0)
        await self.csr_write("LCR_8N1_SLOW", UART_LCR, LCR_WLS)
        await self.csr_write("IER_ERBFI_SLOW", UART_IER, IER_ERBFI)

        saw_thre0 = False
        for i in range(16):
            await self.csr_write(f"TX_FILL_{i}", UART_RBR, 0x50 + i)
            lsr = await self.csr_read(f"TX_LSR_{i}", UART_LSR)
            if not (lsr & LSR_THRE):
                saw_thre0 = True
                break
        if not saw_thre0:
            raise AssertionError(f"THRE never 0 before TX reset LSR=0x{lsr:08x}")
        lsr = await self.csr_read("TX_THRE_PRE", UART_LSR)
        if lsr & LSR_THRE:
            raise AssertionError(f"THRE set before TX reset LSR=0x{lsr:08x}")
        await self._fifo_reset(rx=False, tx=True)
        lsr = await self.csr_read("TX_THRE_POST", UART_LSR)
        if not (lsr & LSR_THRE):
            raise AssertionError(f"THRE not set after TX reset LSR=0x{lsr:08x}")
        for _ in range(4096):
            lsr = await self.csr_read("TX_TEMT_POST", UART_LSR)
            if lsr & LSR_TEMT:
                break
            await Timer(1, units="us")
        else:
            raise AssertionError(f"TEMT not set after TX reset LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-FIFO-RST-TX: THRE+TEMT after XMIT_FIFO_RESET")

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self._init_loopback()

        await self._test_rx_trigger("1B", _TRIG_1B, 1)
        self.trigger_1b_ok = True
        await self._test_rx_trigger("4B", _TRIG_4B, 4)
        self.trigger_4b_ok = True
        await self._test_fifo_reset()
        self.reset_ok = True
        cocotb.log.info(
            "CHK-UART-FIFO-BASIC: trigger1=%s trigger4=%s reset=%s",
            self.trigger_1b_ok,
            self.trigger_4b_ok,
            self.reset_ok,
        )
