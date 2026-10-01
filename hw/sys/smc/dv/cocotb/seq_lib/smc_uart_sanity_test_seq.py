# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0→3 and UART1→2 RX match. Requires +smc_uart_cross_3to0."""

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
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")

_INTR_RDR = 0x2
_IER_BASIC = IER_ERBFI | IER_ETBEI | IER_ELSI | IER_EDSSI
_PAIRS = ((0, 3, 0xA5), (1, 2, 0xB6))


def _regs(idx: int) -> dict[str, int]:
    return {
        "ctrl": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
            idx,
        ),
        "rbr": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", idx
        ),
        "ier": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", idx
        ),
        "iir": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", idx
        ),
        "lcr": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR", idx
        ),
        "mcr": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR", idx
        ),
    }


def _iir_id(iir: int) -> int:
    return (int(iir) & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


def _iir_pending(iir: int) -> bool:
    return (int(iir) & IIR_INTERRUPT_PENDING) == 0


class smc_uart_sanity_test_seq(SmcCsrSeq):
    """Pad-cross UART byte exchange on pairs 0→3 and 1→2."""

    def __init__(self, name: str = "smc_uart_sanity_test_seq") -> None:
        super().__init__(name)
        self.pairs_ok: int = 0

    async def _setup(self, idx: int) -> None:
        r = _regs(idx)
        await self.csr_write(f"U{idx}_EN", r["ctrl"], UART_EN)
        await self.csr_write(f"U{idx}_MCR", r["mcr"], MCR_RTS)
        await self.csr_write(f"U{idx}_DLAB", r["lcr"], LCR_WLS | LCR_DLAB)
        await self.csr_write(f"U{idx}_DLL", r["rbr"], 1)
        await self.csr_write(f"U{idx}_DLH", r["ier"], 0)
        await self.csr_write(f"U{idx}_LCR", r["lcr"], LCR_WLS)
        await self.csr_write(f"U{idx}_IER", r["ier"], _IER_BASIC)
        await self.csr_write(f"U{idx}_FCR", r["iir"], FCR_FIFO_ENABLE)

    async def _exchange(self, ctrl: int, tgt: int, data: int) -> None:
        c = _regs(ctrl)
        t = _regs(tgt)
        await self.csr_write(f"TX_{ctrl}_{tgt}", c["rbr"], data)
        iir = 0
        for _ in range(4096):
            iir = await self.csr_read(f"IIR_{ctrl}_{tgt}", t["iir"])
            if _iir_pending(iir) and _iir_id(iir) == _INTR_RDR:
                break
            await Timer(100, unit="ns")
        else:
            raise AssertionError(f"UART{ctrl}->UART{tgt}: RDR missing IIR=0x{iir:08x}")
        rx = int(await self.csr_read(f"RX_{ctrl}_{tgt}", t["rbr"])) & 0xFF
        if rx != data:
            raise AssertionError(f"UART{ctrl}->UART{tgt}: got 0x{rx:02x} want 0x{data:02x}")
        cocotb.log.info("CHK-UART-SANITY: UART%d->UART%d data=0x%02x", ctrl, tgt, data)

    async def body(self) -> None:
        if "smc_uart_cross_3to0" not in cocotb.plusargs:
            raise AssertionError("smc_uart_sanity_test requires +smc_uart_cross_3to0")
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        for idx in (0, 1, 2, 3):
            await self._setup(idx)
        for ctrl, tgt, data in _PAIRS:
            await self._exchange(ctrl, tgt, data)
            self.pairs_ok += 1
        cocotb.log.info("CHK-UART-SANITY-BASIC: pairs=%d", self.pairs_ok)
