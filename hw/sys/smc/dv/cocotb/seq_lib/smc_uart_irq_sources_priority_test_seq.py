# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 IER/ITR: FIFO_ERROR > LSR > TIMEOUT > RDR > THRE > MODEM."""

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
    _REPO / "hw" / "ip" / "uart" / "uart_log_engine_wrap" / "regs" / "gen" / "c"
    / "uart_log_engine_ctrl.h"
)

UART_CTRL = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
    0,
)
UART_RBR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_RBR_BASE_ADDR", 0
)
UART_IER = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IER_BASE_ADDR", 0
)
UART_IIR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_IIR_BASE_ADDR", 0
)
UART_LCR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LCR_BASE_ADDR", 0
)
UART_MCR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MCR_BASE_ADDR", 0
)
UART_LSR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LSR_BASE_ADDR", 0
)
UART_MSR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR", 0
)
UART_ITR = smc_indexed_addr(
    "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR", 0
)
CLOCK_GATE_CONTROL = smc_addr(
    "SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR"
)

UART_EN = _field_mask(_UART_CTRL_H, "UART_LOG_ENGINE_CTRL__CTRL__UART_EN_bm")
FCR_FIFO_ENABLE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__FIFO_ENABLE_bm")
IER_ERBFI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ERBFI_bm")
IER_ETBEI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ETBEI_bm")
IER_ELSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__ELSI_bm")
IER_EDSSI = _field_mask(_UART_H, "UART_16550_MAIN__IER__EDSSI_bm")
IER_EFEI = _field_mask(_UART_H, "UART_16550_MAIN__IER__EFEI_bm")
ITR_TRBFI = _field_mask(_UART_H, "UART_16550_MAIN__ITR__TRBFI_bm")
ITR_TTBEI = _field_mask(_UART_H, "UART_16550_MAIN__ITR__TTBEI_bm")
ITR_TLSI = _field_mask(_UART_H, "UART_16550_MAIN__ITR__TLSI_bm")
ITR_TDSSI = _field_mask(_UART_H, "UART_16550_MAIN__ITR__TDSSI_bm")
ITR_TFEI = _field_mask(_UART_H, "UART_16550_MAIN__ITR__TFEI_bm")
ITR_TRTI = _field_mask(_UART_H, "UART_16550_MAIN__ITR__TRTI_bm")
IIR_INTERRUPT_PENDING = _field_mask(
    _UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm"
)
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
MCR_DTR = _field_mask(_UART_H, "UART_16550_MAIN__MCR__DTR_bm")
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")

_INTR_MODEM = 0x0
_INTR_THRE = 0x1
_INTR_RDR = 0x2
_INTR_LSR = 0x3
_INTR_TIMEOUT = 0x6
_INTR_FIFO_ERR = 0x7


def _iir_id(iir: int) -> int:
    return (int(iir) & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


def _iir_pending(iir: int) -> bool:
    return (int(iir) & IIR_INTERRUPT_PENDING) == 0


class smc_uart_irq_sources_priority_test_seq(SmcCsrSeq):
    """UART0 IRQ source mapping, clear paths, and priority."""

    def __init__(
        self, name: str = "smc_uart_irq_sources_priority_test_seq"
    ) -> None:
        super().__init__(name)
        self.gating_ok: bool = False
        self.clear_ok: bool = False
        self.priority_ok: bool = False

    async def _clear_status(self) -> None:
        await self.csr_write("IER_CLR", UART_IER, 0)
        await self.csr_write("ITR_CLR", UART_ITR, 0)
        await self.csr_read("LSR_CLR", UART_LSR)
        await self.csr_read("MSR_CLR", UART_MSR)
        for _ in range(8):
            iir = await self.csr_read("IIR_DRAIN", UART_IIR)
            if not _iir_pending(iir):
                break

    async def _poll_iir(self, label: str, iters: int = 64) -> int:
        iir = 0
        for _ in range(iters):
            iir = await self.csr_read(f"{label}_IIR", UART_IIR)
            if _iir_pending(iir):
                return iir
            await Timer(100, units="ns")
        return iir

    async def _expect_id(self, label: str, expect: int, iters: int = 64) -> None:
        iir = await self._poll_iir(label, iters)
        if not _iir_pending(iir) or _iir_id(iir) != expect:
            raise AssertionError(
                f"{label}: expect ID=0x{expect:x} pending "
                f"got IIR=0x{iir:08x} pending={_iir_pending(iir)} "
                f"id=0x{_iir_id(iir):x}"
            )

    async def _expect_not_id(self, label: str, forbidden: int) -> None:
        # Do not early-return on any pending IIR: 16550 reports only the
        # highest-priority source, so a leftover higher ID must not hide a
        # gated forbidden that later becomes visible.
        for _ in range(8):
            iir = await self.csr_read(f"{label}_IIR", UART_IIR)
            if _iir_pending(iir) and _iir_id(iir) == forbidden:
                raise AssertionError(
                    f"{label}: gated source ID=0x{forbidden:x} still pending "
                    f"IIR=0x{iir:08x}"
                )
            await Timer(100, units="ns")

    async def _fail_if_id_still_pending(self, label: str, expect_id: int) -> None:
        iir = await self.csr_read(f"{label}_POST", UART_IIR)
        if _iir_pending(iir) and _iir_id(iir) == expect_id:
            raise AssertionError(
                f"{label}: ID=0x{expect_id:x} still pending after clear "
                f"IIR=0x{iir:08x}"
            )

    async def _test_gating_mapping(self) -> None:
        await self._clear_status()

        cases = [
            ("MODEM", IER_EDSSI, ITR_TDSSI, _INTR_MODEM),
            ("THRE", IER_ETBEI, ITR_TTBEI, _INTR_THRE),
            ("RDR", IER_ERBFI, ITR_TRBFI, _INTR_RDR),
            ("LSR", IER_ELSI, ITR_TLSI, _INTR_LSR),
            ("FIFO", IER_EFEI, ITR_TFEI, _INTR_FIFO_ERR),
        ]
        for name, ier_bit, itr_bit, expect in cases:
            await self.csr_write(f"{name}_IER0", UART_IER, 0)
            await self.csr_write(f"{name}_ITR0", UART_ITR, 0)
            await self.csr_write(f"{name}_ITR_GATE", UART_ITR, itr_bit)
            await self._expect_not_id(f"{name}_GATED", expect)
            await self.csr_write(f"{name}_ITR1", UART_ITR, 0)
            await self.csr_write(f"{name}_IER1", UART_IER, ier_bit)
            await self.csr_write(f"{name}_ITR_MAP", UART_ITR, itr_bit)
            await self._expect_id(f"{name}_MAP", expect)
            await self.csr_write(f"{name}_ITR_CLR", UART_ITR, 0)
            cocotb.log.info(
                "CHK-UART-IRQ-GATE-%s: IER gate + ITR map ID=0x%x", name, expect
            )

        # Timeout maps with ERBFI; RTL bypasses IER for this source.
        await self.csr_write("TO_IER", UART_IER, IER_ERBFI)
        await self.csr_write("TO_ITR", UART_ITR, ITR_TRTI)
        await self._expect_id("TO_MAP", _INTR_TIMEOUT)
        await self.csr_write("TO_ITR_CLR", UART_ITR, 0)
        cocotb.log.info("CHK-UART-IRQ-GATE-TIMEOUT: ITR map ID=0x6")

    async def _init_loopback_clear(self) -> None:
        await self.csr_write("ITR0", UART_ITR, 0)
        await self.csr_write("LCR_DLAB", UART_LCR, LCR_WLS | LCR_DLAB)
        await self.csr_write("DLL", UART_RBR, 1)
        await self.csr_write("DLH", UART_IER, 0)
        await self.csr_write("LCR_8N1", UART_LCR, LCR_WLS)
        await self.csr_write("MCR_LOOP", UART_MCR, MCR_LOOP | MCR_RTS | MCR_DTR)
        await self.csr_write("FCR_EN", UART_IIR, FCR_FIFO_ENABLE)

    async def _test_clear(self) -> None:
        await self._clear_status()
        await self._init_loopback_clear()
        await self.csr_write("ITR_HOLD0", UART_ITR, 0)

        # RDR: natural RX via loopback; clear by RBR read.
        await self.csr_write("RDR_IER", UART_IER, IER_ERBFI)
        await self.csr_write("RDR_THR", UART_RBR, 0xA5)
        await self._expect_id("RDR_NAT", _INTR_RDR, iters=4096)
        await self.csr_read("RDR_POP", UART_RBR)
        await self._fail_if_id_still_pending("RDR_CLR", _INTR_RDR)
        cocotb.log.info("CHK-UART-IRQ-CLR-RDR: RBR read clears RDR")

        for _ in range(8):
            lsr = await self.csr_read("DRAIN_LSR", UART_LSR)
            if not (lsr & LSR_DR):
                break
            await self.csr_read("DRAIN_RBR", UART_RBR)

        # THRE: natural empty; clear by IIR read (16550 latch).
        await self.csr_write("THRE_IER", UART_IER, IER_ETBEI)
        await self._expect_id("THRE_NAT", _INTR_THRE, iters=4096)
        await self._fail_if_id_still_pending("THRE_CLR", _INTR_THRE)
        cocotb.log.info("CHK-UART-IRQ-CLR-THRE: IIR read clears THRE")
        await self.csr_write("THRE_IER0", UART_IER, 0)

        # MSR: toggle MCR in loopback; clear by MSR read.
        await self.csr_write("MSR_IER", UART_IER, IER_EDSSI)
        await self.csr_read("MSR_PRE", UART_MSR)
        mcr = await self.csr_read("MCR_PRE", UART_MCR)
        rts = 0 if (mcr & MCR_RTS) else MCR_RTS
        dtr = 0 if (mcr & MCR_DTR) else MCR_DTR
        await self.csr_write(
            "MCR_TOGGLE", UART_MCR, (mcr & ~(MCR_RTS | MCR_DTR)) | rts | dtr | MCR_LOOP
        )
        await self._expect_id("MSR_NAT", _INTR_MODEM, iters=4096)
        await self.csr_read("MSR_POP", UART_MSR)
        await self._fail_if_id_still_pending("MSR_CLR", _INTR_MODEM)
        cocotb.log.info("CHK-UART-IRQ-CLR-MSR: MSR read clears modem status")
        await self._clear_status()

    async def _test_priority(self) -> None:
        await self._clear_status()
        pairs = [
            ("LSR_vs_RDR", IER_ELSI | IER_ERBFI, ITR_TLSI | ITR_TRBFI, _INTR_LSR),
            ("RDR_vs_THRE", IER_ERBFI | IER_ETBEI, ITR_TRBFI | ITR_TTBEI, _INTR_RDR),
            ("THRE_vs_MODEM", IER_ETBEI | IER_EDSSI, ITR_TTBEI | ITR_TDSSI, _INTR_THRE),
            ("TO_vs_RDR", IER_ERBFI, ITR_TRBFI | ITR_TRTI, _INTR_TIMEOUT),
            ("FIFO_vs_LSR", IER_ELSI | IER_EFEI, ITR_TLSI | ITR_TFEI, _INTR_FIFO_ERR),
        ]
        for name, ier, itr, expect in pairs:
            await self.csr_write(f"{name}_IER", UART_IER, ier)
            await self.csr_write(f"{name}_ITR", UART_ITR, itr)
            await self._expect_id(f"{name}_PRI", expect)
            await self.csr_write(f"{name}_ITR0", UART_ITR, 0)
            await self._clear_status()
            cocotb.log.info(
                "CHK-UART-IRQ-PRI-%s: winner ID=0x%x", name, expect
            )

    async def body(self) -> None:
        cg = await self.csr_read("UART_CG", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART_EN", UART_CTRL, UART_EN)

        await self._test_gating_mapping()
        self.gating_ok = True
        await self._test_clear()
        self.clear_ok = True
        await self._test_priority()
        self.priority_ok = True
        cocotb.log.info(
            "CHK-UART-IRQ-BASIC: gating=%s clear=%s priority=%s",
            self.gating_ok,
            self.clear_ok,
            self.priority_ok,
        )
