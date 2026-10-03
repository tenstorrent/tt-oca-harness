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
UART_MSR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_MSR_BASE_ADDR", 0)
UART_ITR = smc_indexed_addr("SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_ITR_BASE_ADDR", 0)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

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
IIR_INTERRUPT_PENDING = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_PENDING_bm")
IIR_INTERRUPT_ID = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bm")
IIR_INTERRUPT_ID_BP = _field_mask(_UART_H, "UART_16550_MAIN__IIR__INTERRUPT_ID_bp")
LCR_DLAB = _field_mask(_UART_H, "UART_16550_MAIN__LCR__DLAB_bm")
LCR_WLS = _field_mask(_UART_H, "UART_16550_MAIN__LCR__WLS_bm")
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
MCR_RTS = _field_mask(_UART_H, "UART_16550_MAIN__MCR__RTS_bm")
MCR_DTR = _field_mask(_UART_H, "UART_16550_MAIN__MCR__DTR_bm")
MCR_OUT1 = _field_mask(_UART_H, "UART_16550_MAIN__MCR__OUT1_bm")
MCR_OUT2 = _field_mask(_UART_H, "UART_16550_MAIN__MCR__OUT2_bm")
MSR_DCTS = _field_mask(_UART_H, "UART_16550_MAIN__MSR__DCTS_bm")
MSR_DDSR = _field_mask(_UART_H, "UART_16550_MAIN__MSR__DDSR_bm")
MSR_TERI = _field_mask(_UART_H, "UART_16550_MAIN__MSR__TERI_bm")
MSR_DDCD = _field_mask(_UART_H, "UART_16550_MAIN__MSR__DDCD_bm")
MSR_DELTAS = MSR_DCTS | MSR_DDSR | MSR_TERI | MSR_DDCD
LSR_DR = _field_mask(_UART_H, "UART_16550_MAIN__LSR__DR_bm")

# IIR.INTERRUPT_ID encodings AND their priority ranking. Both come from the
# authoritative register description, `hw/ip/uart/uart_16550/regs/
# uart_16550_main.rdl` reg IIR, field INTERRUPT_ID[3:1], which lists:
#
#     * `0x7` - FIFO Error Interrupt                         (priority 0)
#     * `0x3` - Receiver Line Status Interrupt               (priority 1)
#     * `0x6` - Reception Timeout Interrupt                  (priority 2)
#     * `0x2` - Received Data Ready Interrupt                (priority 3)
#     * `0x1` - Transmitter Holding Register Empty Interrupt (priority 4)
#     * `0x0` - Modem Status Interrupt                       (priority 5)
#
# Lower number = higher priority. The priority table below is DERIVED from this
# ranking rather than written out per pair, so the expected winner of every
# contest traces to the register description and not to the RTL's encoder.
_INTR_MODEM = 0x0
_INTR_THRE = 0x1
_INTR_RDR = 0x2
_INTR_LSR = 0x3
_INTR_TIMEOUT = 0x6
_INTR_FIFO_ERR = 0x7

_IIR_PRIORITY = {
    _INTR_FIFO_ERR: 0,
    _INTR_LSR: 1,
    _INTR_TIMEOUT: 2,
    _INTR_RDR: 3,
    _INTR_THRE: 4,
    _INTR_MODEM: 5,
}


def _rdl_priority_winner(*ids: int) -> int:
    """The highest-priority id among ``ids`` per the RDL ranking above."""
    return min(ids, key=lambda i: _IIR_PRIORITY[i])


def _iir_id(iir: int) -> int:
    return (int(iir) & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP


def _iir_pending(iir: int) -> bool:
    return (int(iir) & IIR_INTERRUPT_PENDING) == 0


class smc_uart_irq_sources_priority_test_seq(SmcCsrSeq):
    """UART0 IRQ source mapping, clear paths, and priority."""

    def __init__(self, name: str = "smc_uart_irq_sources_priority_test_seq") -> None:
        super().__init__(name)
        self.gating_ok: bool = False
        self.clear_ok: bool = False
        self.priority_ok: bool = False
        # Measured results the test module gates on.
        # name -> (gated id or None, mapped id)
        self.gate_map_ids: dict[str, tuple[int | None, int]] = {}
        # name -> (winner id observed, winner id the RDL ranking requires)
        self.priority_ids: dict[str, tuple[int, int]] = {}
        self.single_deltas: dict[str, int] = {}

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
            await Timer(100, unit="ns")
        return iir

    async def _expect_id(self, label: str, expect: int, iters: int = 64) -> int:
        """Return the MEASURED IIR id so tokens and gates carry real values."""
        iir = await self._poll_iir(label, iters)
        if not _iir_pending(iir) or _iir_id(iir) != expect:
            raise AssertionError(
                f"{label}: expect ID=0x{expect:x} pending "
                f"got IIR=0x{iir:08x} pending={_iir_pending(iir)} "
                f"id=0x{_iir_id(iir):x}"
            )
        return _iir_id(iir)

    async def _expect_not_id(self, label: str, forbidden: int) -> int | None:
        # Do not early-return on any pending IIR: 16550 reports only the
        # highest-priority source, so a leftover higher ID must not hide a
        # gated forbidden that later becomes visible.
        last: int | None = None
        for _ in range(8):
            iir = await self.csr_read(f"{label}_IIR", UART_IIR)
            if _iir_pending(iir) and _iir_id(iir) == forbidden:
                raise AssertionError(
                    f"{label}: gated source ID=0x{forbidden:x} still pending IIR=0x{iir:08x}"
                )
            last = _iir_id(iir) if _iir_pending(iir) else None
            await Timer(100, unit="ns")
        return last

    async def _fail_if_id_still_pending(self, label: str, expect_id: int) -> None:
        iir = await self.csr_read(f"{label}_POST", UART_IIR)
        if _iir_pending(iir) and _iir_id(iir) == expect_id:
            raise AssertionError(
                f"{label}: ID=0x{expect_id:x} still pending after clear IIR=0x{iir:08x}"
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
            gated_id = await self._expect_not_id(f"{name}_GATED", expect)
            await self.csr_write(f"{name}_ITR1", UART_ITR, 0)
            await self.csr_write(f"{name}_IER1", UART_IER, ier_bit)
            await self.csr_write(f"{name}_ITR_MAP", UART_ITR, itr_bit)
            mapped_id = await self._expect_id(f"{name}_MAP", expect)
            await self.csr_write(f"{name}_ITR_CLR", UART_ITR, 0)
            self.gate_map_ids[name] = (gated_id, mapped_id)
            cocotb.log.info(
                "CHK-UART-IRQ-GATE-%s: with the IER enable clear the forced "
                "source did not reach IIR (last pending id=%s); with the enable "
                "set the same ITR force produced IIR id=0x%x, the encoding "
                "uart_16550_main.rdl IIR.INTERRUPT_ID gives this source",
                name,
                "none" if gated_id is None else f"0x{gated_id:x}",
                mapped_id,
            )

        # Reception Timeout. uart_16550_main.rdl's IER declares exactly five
        # enables (ERBFI/ETBEI/ELSI/EDSSI/EFEI) and NONE of them is a Reception
        # Timeout enable, so the register description supports no gated-negative
        # leg for this source and none is claimed. What IS spec-stated is
        # ITR.TRTI: "Test Reception Timeout Interrupt. Writing a `1` forces the
        # interrupt and writing `0` releases it." Both directions are checked.
        await self.csr_write("TO_IER", UART_IER, IER_ERBFI)
        await self.csr_write("TO_ITR", UART_ITR, ITR_TRTI)
        to_id = await self._expect_id("TO_MAP", _INTR_TIMEOUT)
        await self.csr_write("TO_ITR_CLR", UART_ITR, 0)
        released_id = await self._expect_not_id("TO_RELEASED", _INTR_TIMEOUT)
        self.gate_map_ids["TIMEOUT"] = (released_id, to_id)
        cocotb.log.info(
            "CHK-UART-IRQ-MAP-TIMEOUT: ITR.TRTI=1 forced IIR id=0x%x (the "
            "Reception Timeout encoding in uart_16550_main.rdl) and writing 0 "
            "released it (last pending id=%s). Named MAP, not GATE: the RDL's "
            "IER has no Reception Timeout enable, so this source has no "
            "IER-gated negative leg to run",
            to_id,
            "none" if released_id is None else f"0x{released_id:x}",
        )

    async def _init_loopback_clear(self) -> None:
        await self.csr_write("ITR0", UART_ITR, 0)
        await self.csr_write("LCR_DLAB", UART_LCR, LCR_WLS | LCR_DLAB)
        # DLL/DLH/FCR are the write-only aliases of the RBR/IER/IIR addresses in
        # the 16550 map; the labels name both the register written and the symbol
        # addressed, so every register name in the kept log resolves to a symbol
        # in this file.
        await self.csr_write("DLL_via_UART_RBR", UART_RBR, 1)
        await self.csr_write("DLH_via_UART_IER", UART_IER, 0)
        await self.csr_write("LCR_8N1", UART_LCR, LCR_WLS)
        await self.csr_write("MCR_LOOP", UART_MCR, MCR_LOOP | MCR_RTS | MCR_DTR)
        await self.csr_write("FCR_EN_via_UART_IIR", UART_IIR, FCR_FIFO_ENABLE)

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
        await self._single_deltas()
        await self._clear_status()

    async def _single_deltas(self) -> None:
        """Each modem-status delta raised on its own, from one MCR output in loopback.

        The Programmer's Guide UART section (``doc/programmer/src/smc-programming.adoc``) has
        system loopback feed DSR from DTR, RI from OUT1 and DCD from OUT2. DDSR
        and DDCD mark any change and TERI only RI's trailing edge, so OUT1 is
        set first, which must raise no delta, and then cleared.
        """
        # (label, MCR bits set before the edge, MCR bits after it, the one delta)
        steps = (
            ("DDSR", MCR_DTR, 0, MSR_DDSR),
            ("TERI_RISE", 0, MCR_OUT1, 0),
            ("TERI", MCR_OUT1, 0, MSR_TERI),
            ("DDCD", 0, MCR_OUT2, MSR_DDCD),
        )
        base = MCR_LOOP | MCR_RTS
        for label, before, after, delta in steps:
            await self.csr_write(f"MSR1_{label}_SETUP", UART_MCR, base | before)
            await self.csr_read(f"MSR1_{label}_PRE", UART_MSR)
            await self.csr_write(f"MSR1_{label}_EDGE", UART_MCR, base | after)
            if delta:
                await self._expect_id(f"MSR1_{label}_NAT", _INTR_MODEM, iters=4096)
            msr = await self.csr_read(f"MSR1_{label}_POP", UART_MSR)
            assert msr & MSR_DELTAS == delta, (
                f"[{label}] MSR reads 0x{msr:02x} after changing MCR from 0x{base | before:02x} "
                f"to 0x{base | after:02x}; the deltas (mask 0x{MSR_DELTAS:x}) must be exactly "
                f"0x{delta:x}"
            )
            await self._fail_if_id_still_pending(f"MSR1_{label}_CLR", _INTR_MODEM)
            self.single_deltas[label] = msr
        cocotb.log.info(
            "CHK-UART-MSR-SINGLE-DELTA: in loopback, DTR alone raised only DDSR, OUT1's "
            "trailing edge alone only TERI (its rising edge none), and OUT2 alone only "
            "DDCD; each raised the modem interrupt and each MSR read cleared it (%s)",
            ", ".join(f"{k}=0x{v:02x}" for k, v in self.single_deltas.items()),
        )

    async def _test_priority(self) -> None:
        await self._clear_status()
        # (name, IER enables, ITR forces, the two contending IIR ids). The
        # expected winner is NOT written out per row: it is computed from the
        # RDL's priority ranking (_IIR_PRIORITY), so the golden traces to
        # uart_16550_main.rdl IIR.INTERRUPT_ID rather than to the RTL encoder.
        pairs = [
            ("LSR_vs_RDR", IER_ELSI | IER_ERBFI, ITR_TLSI | ITR_TRBFI, (_INTR_LSR, _INTR_RDR)),
            ("RDR_vs_THRE", IER_ERBFI | IER_ETBEI, ITR_TRBFI | ITR_TTBEI, (_INTR_RDR, _INTR_THRE)),
            (
                "THRE_vs_MODEM",
                IER_ETBEI | IER_EDSSI,
                ITR_TTBEI | ITR_TDSSI,
                (_INTR_THRE, _INTR_MODEM),
            ),
            ("TO_vs_RDR", IER_ERBFI, ITR_TRBFI | ITR_TRTI, (_INTR_TIMEOUT, _INTR_RDR)),
            ("FIFO_vs_LSR", IER_ELSI | IER_EFEI, ITR_TLSI | ITR_TFEI, (_INTR_FIFO_ERR, _INTR_LSR)),
        ]
        for name, ier, itr, contenders in pairs:
            expect = _rdl_priority_winner(*contenders)
            await self.csr_write(f"{name}_IER", UART_IER, ier)
            await self.csr_write(f"{name}_ITR", UART_ITR, itr)
            got = await self._expect_id(f"{name}_PRI", expect)
            await self.csr_write(f"{name}_ITR0", UART_ITR, 0)
            await self._clear_status()
            self.priority_ids[name] = (got, expect)
            cocotb.log.info(
                "CHK-UART-IRQ-PRI-%s: stimulus=itr_test_register (both sources "
                "forced through the 16550 Interrupt Test Register, not raised "
                "from natural line/FIFO conditions); contenders id=0x%x "
                "(priority %d) and id=0x%x (priority %d) per "
                "uart_16550_main.rdl IIR.INTERRUPT_ID; winner observed ID=0x%x, "
                "ranking requires 0x%x",
                name,
                contenders[0],
                _IIR_PRIORITY[contenders[0]],
                contenders[1],
                _IIR_PRIORITY[contenders[1]],
                got,
                expect,
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
