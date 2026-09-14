# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 parity mismatch, RX overrun, and break/framing. Requires +smc_uart_cross_3to0."""

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
LCR_PEN = _field_mask(_UART_H, "UART_16550_MAIN__LCR__PEN_bm")
LCR_EPS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__EPS_bm")
LCR_SET_BREAK = _field_mask(_UART_H, "UART_16550_MAIN__LCR__SET_BREAK_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")
LSR_OE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__OE_bm")
LSR_PE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__PE_bm")
LSR_FE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__FE_bm")
LSR_BI = _field_mask(_UART_H, "UART_16550_MAIN__LSR__BI_bm")

_INTR_RDR = 0x2
_INTR_LSR = 0x3
_FIFO_DEPTH = 32
_IER_BASIC = IER_ERBFI | IER_ETBEI | IER_ELSI | IER_EDSSI


def _uart_regs(idx: int) -> dict[str, int]:
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
        "lsr": smc_indexed_addr(
            "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", idx
        ),
    }


def _iir_id(iir: int) -> int:
    return (int(iir) & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


def _iir_pending(iir: int) -> bool:
    return (int(iir) & IIR_INTERRUPT_PENDING) == 0


class smc_uart_error_conditions_test_seq(SmcCsrSeq):
    """UART0/3 parity, UART0 overrun, UART0 break/framing."""

    def __init__(self, name: str = "smc_uart_error_conditions_test_seq") -> None:
        super().__init__(name)
        self.parity_ok: bool = False
        self.overrun_ok: bool = False
        self.break_ok: bool = False

    async def _enable(self, idx: int) -> None:
        r = _uart_regs(idx)
        await self.csr_write(f"UART{idx}_EN", r["ctrl"], UART_EN)

    async def _clear_status(self, r: dict[str, int], tag: str) -> None:
        await self.csr_read(f"{tag}_LSR", r["lsr"])
        await self.csr_read(f"{tag}_IIR", r["iir"])
        await self.csr_read(f"{tag}_RBR", r["rbr"])

    async def _program_format(
        self,
        r: dict[str, int],
        tag: str,
        *,
        divisor: int = 1,
        pen: bool = False,
        eps: bool = False,
        loop: bool = False,
    ) -> None:
        await self.csr_write(f"{tag}_MCR", r["mcr"], MCR_RTS | (MCR_LOOP if loop else 0))
        await self.csr_write(f"{tag}_LCR_DLAB", r["lcr"], LCR_WLS | LCR_DLAB)
        await self.csr_write(f"{tag}_DLL", r["rbr"], divisor & 0xFF)
        await self.csr_write(f"{tag}_DLH", r["ier"], (divisor >> 8) & 0xFF)
        lcr = LCR_WLS
        if pen:
            lcr |= LCR_PEN
        if eps:
            lcr |= LCR_EPS
        await self.csr_write(f"{tag}_LCR", r["lcr"], lcr)
        await self.csr_write(f"{tag}_IER", r["ier"], _IER_BASIC)
        await self.csr_write(f"{tag}_FCR", r["iir"], FCR_FIFO_ENABLE)

    async def _wait_iir_id(
        self, r: dict[str, int], tag: str, expect: int, iters: int = 512
    ) -> bool:
        for _ in range(iters):
            iir = await self.csr_read(f"{tag}_IIR", r["iir"])
            if _iir_pending(iir) and _iir_id(iir) == expect:
                return True
            await Timer(100, units="ns")
        return False

    async def _test_parity(self) -> None:
        if "smc_uart_cross_3to0" not in cocotb.plusargs:
            raise AssertionError(
                "smc_uart_error_conditions_test parity requires +smc_uart_cross_3to0"
            )
        ctrl = _uart_regs(3)
        tgt = _uart_regs(0)
        await self._enable(3)
        await self._enable(0)
        # UART3 odd, UART0 even → PE on UART0.
        await self._program_format(ctrl, "C3", pen=True, eps=False)
        await self._program_format(tgt, "T0", pen=True, eps=True)
        await self._clear_status(ctrl, "C3")
        await self._clear_status(tgt, "T0")

        for i, tx in enumerate((0x00, 0xFF, 0x55, 0xAA)):
            await self.csr_write(f"PE_TX_{i}", ctrl["rbr"], tx)
            saw_pe = False
            saw_lsr_irq = False
            for _ in range(512):
                lsr = await self.csr_read(f"PE_LSR_{i}", tgt["lsr"])
                if lsr & LSR_PE:
                    saw_pe = True
                iir = await self.csr_read(f"PE_IIR_{i}", tgt["iir"])
                if _iir_pending(iir) and _iir_id(iir) == _INTR_LSR:
                    saw_lsr_irq = True
                if saw_pe and saw_lsr_irq:
                    break
                await Timer(100, units="ns")
            if not saw_pe:
                raise AssertionError(f"parity PE not seen for byte 0x{tx:02x}")
            if not saw_lsr_irq:
                raise AssertionError(f"parity LSR IRQ not seen for byte 0x{tx:02x}")
            await self.csr_read(f"PE_POP_{i}", tgt["rbr"])
        cocotb.log.info("CHK-UART-ERR-PE: mismatch PE + LSR IRQ on UART0")

        # Matching even parity: no PE/FE/BI.
        await self._program_format(ctrl, "C3E", pen=True, eps=True)
        await self._program_format(tgt, "T0E", pen=True, eps=True)
        await self._clear_status(ctrl, "C3E")
        await self._clear_status(tgt, "T0E")
        for i, tx in enumerate((0x00, 0xFF, 0x55, 0xAA)):
            await self.csr_write(f"OK_TX_{i}", ctrl["rbr"], tx)
            if not await self._wait_iir_id(tgt, f"OK_RDR_{i}", _INTR_RDR, 64):
                raise AssertionError(f"matched parity missing RDR for 0x{tx:02x}")
            lsr = await self.csr_read(f"OK_LSR_{i}", tgt["lsr"])
            if lsr & (LSR_PE | LSR_FE | LSR_BI):
                raise AssertionError(f"matched parity unexpected err LSR=0x{lsr:08x}")
            await self.csr_read(f"OK_POP_{i}", tgt["rbr"])
        cocotb.log.info("CHK-UART-ERR-PE-NEG: matched even parity clean")

    async def _test_overrun(self) -> None:
        r = _uart_regs(0)
        await self._enable(0)
        await self._program_format(r, "OE", loop=True)
        await self._clear_status(r, "OE")

        # Below-threshold control for the OE claim below: one byte cannot
        # overflow a FIFO of _FIFO_DEPTH, so DR must set and OE must stay clear.
        # It puts OE=0 in the run alongside the OE=1 the overflow leg produces,
        # which a bit stuck at 1 or a constant LSR read cannot do.
        await self.csr_write("OE_NEG_THR", r["rbr"], 0x5A)
        if not await self._wait_iir_id(r, "OE_NEG_RDR", _INTR_RDR, 512):
            raise AssertionError("single byte produced no RDR interrupt")
        lsr = await self.csr_read("OE_NEG_LSR", r["lsr"])
        if not lsr & LSR_DR:
            raise AssertionError(f"single byte left LSR.DR clear LSR=0x{lsr:08x}")
        if lsr & LSR_OE:
            raise AssertionError(f"single byte set LSR.OE LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-ERR-OE-NEG: one byte -> LSR.DR=1 LSR.OE=0 (LSR=0x%08x)", lsr)
        await self._clear_status(r, "OE")

        total = _FIFO_DEPTH + 4
        for i in range(total):
            await self.csr_write(f"OE_THR_{i}", r["rbr"], 0x20 + (i & 0x3F))
            if not await self._wait_iir_id(r, f"OE_RDR_{i}", _INTR_RDR, 512):
                raise AssertionError(f"overrun path missing RDR after write {i}")
        saw_oe = False
        for _ in range(1024):
            lsr = await self.csr_read("OE_POLL", r["lsr"])
            if lsr & LSR_OE:
                saw_oe = True
                break
            await Timer(100, units="ns")
        if not saw_oe:
            raise AssertionError("LSR.OE never set after FIFO overflow")
        if not await self._wait_iir_id(r, "OE_LSR", _INTR_LSR, 32):
            raise AssertionError("overrun missing LSR interrupt")
        for _ in range(64):
            lsr = await self.csr_read("OE_DRAIN_LSR", r["lsr"])
            if not (lsr & LSR_DR):
                break
            await self.csr_read("OE_DRAIN_RBR", r["rbr"])
        lsr = await self.csr_read("OE_POST", r["lsr"])
        if lsr & LSR_OE:
            raise AssertionError(f"LSR.OE sticky after drain LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-ERR-OE: overrun OE + LSR IRQ then clear")

    async def _test_break(self) -> None:
        r = _uart_regs(0)
        await self._enable(0)
        await self._program_format(r, "BRK", loop=True)
        await self._clear_status(r, "BRK")
        lsr = await self.csr_read("BRK_PRE", r["lsr"])
        if lsr & (LSR_FE | LSR_BI):
            raise AssertionError(f"FE/BI set before break LSR=0x{lsr:08x}")
        await self.csr_write("BRK_SET", r["lcr"], LCR_WLS | LCR_SET_BREAK)
        saw_bi = False
        for _ in range(128):
            lsr = await self.csr_read("BRK_POLL", r["lsr"])
            if lsr & LSR_BI:
                saw_bi = True
                break
            await Timer(1, units="us")
        if not saw_bi:
            raise AssertionError("LSR.BI never set under SET_BREAK loopback")
        if not await self._wait_iir_id(r, "BRK_LSR", _INTR_LSR, 32):
            raise AssertionError("break missing LSR interrupt")
        await self.csr_write("BRK_CLR", r["lcr"], LCR_WLS)
        lsr = 0
        for _ in range(256):
            lsr = await self.csr_read("BRK_CLR_LSR", r["lsr"])
            await self.csr_read("BRK_CLR_RBR", r["rbr"])
            await self.csr_read("BRK_CLR_IIR", r["iir"])
            if not (lsr & (LSR_FE | LSR_BI)):
                break
            await Timer(100, units="ns")
        else:
            raise AssertionError(f"FE/BI sticky after break clear LSR=0x{lsr:08x}")
        lsr = await self.csr_read("BRK_POST", r["lsr"])
        if lsr & (LSR_FE | LSR_BI):
            raise AssertionError(f"FE/BI reappeared after clear LSR=0x{lsr:08x}")
        cocotb.log.info("CHK-UART-ERR-BI: SET_BREAK BI + LSR IRQ then clear")

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)

        await self._test_parity()
        self.parity_ok = True
        await self._test_overrun()
        self.overrun_ok = True
        await self._test_break()
        self.break_ok = True
        cocotb.log.info(
            "CHK-UART-ERR-BASIC: pe=%s oe=%s bi=%s",
            self.parity_ok,
            self.overrun_ok,
            self.break_ok,
        )
