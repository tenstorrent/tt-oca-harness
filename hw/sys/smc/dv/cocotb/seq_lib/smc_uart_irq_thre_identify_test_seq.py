# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 transmitter-empty interrupt lifecycle and IIR service ordering.

Spec sources: hw/ip/uart/uart_16550/doc/architecture.adoc (Interrupt Priority and Service),
hw/ip/uart/uart_16550/regs/uart_16550_main.rdl (IER, IIR, LSR, MCR, ITR).
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import UART_CG_EN, smc_addr, uart_16550_main_u32
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    DLL_OFFSET,
    DLM_OFFSET,
    FCR_FIFO_ENABLE,
    FCR_OFFSET,
    FCR_RCVR_FIFO_RESET,
    FCR_XMIT_FIFO_RESET,
    IER_ERBFI,
    IIR_ID,
    IIR_ID_SHIFT,
    IIR_PENDING,
    LCR_DLAB,
    LCR_WLS,
    LSR_DR,
    LSR_TEMT,
    LSR_THRE,
    MCR_DTR,
    MCR_LOOP,
    THR_OFFSET,
    UART_EN,
    WLS_8_BITS,
    uart_base,
    uart_reg,
    wrap_ctrl_reg,
)

WRAP = 0
DIVISOR = 8
FRAME_BITS = 10
OVERSAMPLE = 16
FRAME_CLOCKS = FRAME_BITS * OVERSAMPLE * (DIVISOR + 1)
BREAK_CLOCKS = 2 * FRAME_CLOCKS
IRQ_EDGE_LIMIT = 64
POLL_LIMIT = 800
IIR_POLL_LIMIT = 800
ARM_POLL_LIMIT = 16
SERVICE_LIMIT = 8
RBR_DRAIN_LIMIT = 8
MASK_SAMPLES = 8

IER_ETBEI = uart_16550_main_u32("UART_16550_MAIN__IER__ETBEI_bm")
IER_ELSI = uart_16550_main_u32("UART_16550_MAIN__IER__ELSI_bm")
IER_EDSSI = uart_16550_main_u32("UART_16550_MAIN__IER__EDSSI_bm")
ITR_TRBFI = uart_16550_main_u32("UART_16550_MAIN__ITR__TRBFI_bm")
LCR_SET_BREAK = uart_16550_main_u32("UART_16550_MAIN__LCR__SET_BREAK_bm")
LSR_BI = uart_16550_main_u32("UART_16550_MAIN__LSR__BI_bm")
LSR_ERRORS = LSR_BI | sum(
    uart_16550_main_u32(f"UART_16550_MAIN__LSR__{f}_bm") for f in ("FE", "PE", "OE")
)
CLOCK_GATE_CONTROL = smc_addr("SMC_TOP_SMC_BASE_CONFIG_CLOCK_GATE_CONTROL_BASE_ADDR")

# uart_16550_main.rdl IIR.INTERRUPT_ID encodings.
ID_MODEM = 0x0
ID_THRE = 0x1
ID_RDR = 0x2
ID_LSR = 0x3

CHAR_A, CHAR_B, CHAR_C, CHAR_D = 0x41, 0x42, 0x43, 0x44
CHAR_E, CHAR_F, CHAR_G, CHAR_H, CHAR_Y = 0x45, 0x46, 0x47, 0x48, 0x59
CHAR_X = 0x58
CHAR_Z = 0x5A

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")
CHECKERS = (
    ("CHK-UART-THRE-RAISE", "S2"),
    ("CHK-UART-THRE-WRITE-CLEARS", "S3"),
    ("CHK-UART-THRE-IIR-CLEAR", "S4"),
    ("CHK-UART-THRE-REARM", "S5"),
    ("CHK-UART-THRE-MASK", "S6"),
    ("CHK-UART-THRE-ETBEI-EMPTY", "S7"),
    ("CHK-UART-LSR-THRE-STICKY", "S8"),
    ("CHK-UART-ID-ORDER", "S9"),
    ("CHK-UART-ID-SERVICE-LOOP", "S9"),
    ("CHK-UART-ID-IIR-SIDE-EFFECT", "S10"),
)
FENCE_TERMS = (
    "THRE_RAISED",
    "WRITE_CLEARS",
    "IIR_CLEARS",
    "REARMED",
    "MASKED",
    "ETBEI_EMPTY",
    "LSR_THRE",
    "ORDER",
    "SERVICE_LOOP",
    "NO_SIDE_EFFECT",
)


def _pending(iir: int) -> bool:
    return (iir & IIR_PENDING) == 0


def _id(iir: int) -> int:
    return (iir & IIR_ID) >> IIR_ID_SHIFT


def _text(iir: int) -> str:
    return f"ID 0x{_id(iir):x}" if _pending(iir) else "no interrupt pending"


class smc_uart_irq_thre_identify_test_seq(SmcCsrSeq):
    """THRE interrupt raise, clear, re-arm, mask and IIR priority ordering on UART0."""

    def __init__(self, name: str = "smc_uart_irq_thre_identify_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.waits: dict[str, list] = {}
        self.last_lsr = -1
        self.last_iir = -1
        self.base = uart_base(WRAP)
        self.thr = self.base + THR_OFFSET
        self.ier = uart_reg(WRAP, "IER")
        self.iir = uart_reg(WRAP, "IIR")
        self.lcr = uart_reg(WRAP, "LCR")
        self.mcr = uart_reg(WRAP, "MCR")
        self.lsr = uart_reg(WRAP, "LSR")
        self.msr = uart_reg(WRAP, "MSR")
        self.rbr = uart_reg(WRAP, "RBR")
        self.itr = uart_reg(WRAP, "ITR")
        self.dut = cocotb.top

    def _step(self, step_id: str) -> None:
        self.stamps.append((step_id, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step_id: str, text: str, *args) -> None:
        assert self.stamps and self.stamps[-1][0] == step_id, (
            f"{chk_id} printed before its step {step_id} completed; stamps {self.stamps}"
        )
        self.chk_marks.append((chk_id, len(self.stamps)))
        cocotb.log.info("%s: " + text, chk_id, *args)

    def _wait(self, name: str, bound: str) -> None:
        self.waits.setdefault(name, [bound, "not reached"])

    def _end(self, name: str, state: str) -> None:
        self.waits[name][1] = state

    def _irq(self) -> int:
        value = self.dut.uart_interrupt.value
        assert value.is_resolvable, "uart_interrupt is X/Z"
        return int(value) & 1

    def _state(self) -> str:
        tx = "n/a"
        if hasattr(self.dut, "tb_uart0_tx_from_dut"):
            raw = self.dut.tb_uart0_tx_from_dut.value
            assert raw.is_resolvable, "tb_uart0_tx_from_dut is X/Z"
            tx = str(int(raw))
        return (
            f"last LSR=0x{self.last_lsr:x} last IIR=0x{self.last_iir:x} "
            f"uart_interrupt={self._irq()} uart0_tx_pad={tx}"
        )

    async def _rd_lsr(self, label: str) -> int:
        self.last_lsr = await self.csr_read(label, self.lsr)
        return self.last_lsr

    async def _rd_iir(self, label: str) -> int:
        self.last_iir = await self.csr_read(label, self.iir)
        return self.last_iir

    async def _wait_lsr(self, label: str, mask: int) -> int:
        name = f"lsr_{label}"
        self._wait(name, f"{POLL_LIMIT}_reads")
        for _ in range(POLL_LIMIT):
            lsr = await self._rd_lsr(f"{label}_LSR")
            if lsr & mask == mask:
                self._end(name, f"LSR=0x{lsr:x}")
                return lsr
        raise AssertionError(f"{label}: LSR mask 0x{mask:x} never set; {self._state()}")

    async def _wait_irq(self, label: str, want: int) -> int:
        name = "irq_edge"
        self._wait(name, f"{IRQ_EDGE_LIMIT}_clk_periph_edges")
        for n in range(IRQ_EDGE_LIMIT):
            if self._irq() == want:
                self._end(name, f"uart_interrupt={want} after {n} edges")
                return n
            await RisingEdge(self.dut.clk_periph)
        raise AssertionError(f"{label}: uart_interrupt never read {want}; {self._state()}")

    async def _await_pending(self, label: str, limit: int, name: str) -> int:
        self._wait(name, f"{limit}_reads")
        for n in range(limit):
            iir = await self._rd_iir(f"{label}_IIR")
            if _pending(iir):
                self._end(name, f"IIR=0x{iir:x} after {n + 1} reads")
                return iir
        raise AssertionError(f"{label}: no interrupt reported; {self._state()}")

    async def _expect_thre(self, label: str) -> int:
        iir = await self._await_pending(label, IIR_POLL_LIMIT, "iir_pending")
        assert _id(iir) == ID_THRE, f"{label}: IIR=0x{iir:x} is {_text(iir)}, not ID 1"
        return iir

    async def _send(self, label: str, char: int) -> None:
        await self.csr_write(label, self.thr, char)

    async def _drain_tx(self, label: str) -> None:
        await self._wait_lsr(label, LSR_TEMT | LSR_THRE | LSR_DR)

    async def _drain_rbr(self, label: str) -> None:
        name = "rbr_drain"
        self._wait(name, f"{RBR_DRAIN_LIMIT}_reads")
        for n in range(RBR_DRAIN_LIMIT):
            lsr = await self._rd_lsr(f"{label}_LSR")
            if not lsr & LSR_DR:
                self._end(name, f"LSR=0x{lsr:x} after {n} RBR reads")
                return
            await self.csr_read(f"{label}_RBR", self.rbr)
        raise AssertionError(f"{label}: RBR never emptied; {self._state()}")

    async def _s1(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        self.cg = cg
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self.csr_write("UART_EN", wrap_ctrl_reg(WRAP), UART_EN)
        await self.csr_write("LCR_DLAB", self.lcr, LCR_DLAB)
        await self.csr_write("DLL", self.base + DLL_OFFSET, DIVISOR)
        await self.csr_write("DLM", self.base + DLM_OFFSET, 0)
        await self.csr_write("LCR_8N1", self.lcr, WLS_8_BITS & LCR_WLS)
        await self.csr_write("MCR_LOOP", self.mcr, MCR_LOOP)
        fcr = FCR_FIFO_ENABLE | FCR_RCVR_FIFO_RESET | FCR_XMIT_FIFO_RESET
        await self.csr_write("FCR", self.base + FCR_OFFSET, fcr)
        await self.csr_write("IER", self.ier, 0)
        await self.csr_read("MCR_RB", self.mcr, expected=MCR_LOOP)
        await self._drain_rbr("S1")
        await self.csr_read("MSR_CLR", self.msr)
        assert self._irq() == 0, f"uart_interrupt high after arming; {self._state()}"
        self._step("S1")

    async def _s2(self) -> None:
        await self.csr_write("S2_IER", self.ier, IER_ETBEI)
        await self._send("S2_THR", CHAR_A)
        await self._drain_tx("S2")
        await self._wait_irq("S2_IRQ", 1)
        iir = await self._expect_thre("S2")
        self._step("S2")
        self._chk(
            "CHK-UART-THRE-RAISE",
            "S2",
            "after the character 0x%02x drained (LSR=0x%x) with ETBEI set uart_interrupt read 1 "
            "and IIR=0x%x reported %s",
            CHAR_A,
            self.last_lsr,
            iir,
            _text(iir),
        )

    async def _irq_probe(self, samples: list, stop: list) -> None:
        while not stop:
            await RisingEdge(self.dut.clk_periph)
            samples.append((int(get_sim_time("ps")), self._irq()))

    async def _s3(self) -> None:
        await self._send("S3_THR_B", CHAR_B)
        await self._drain_tx("S3_B")
        edges_high = await self._wait_irq("S3_HIGH", 1)
        samples: list[tuple[int, int]] = []
        stop: list[int] = []
        probe = cocotb.start_soon(self._irq_probe(samples, stop))
        t_write = int(get_sim_time("ps"))
        await self._send("S3_THR_C", CHAR_C)
        self._wait("irq_fall", f"{IRQ_EDGE_LIMIT}_clk_periph_edges")

        def fall() -> tuple[int, int] | None:
            for (_, prev), (t, cur) in zip(samples, samples[1:]):
                if prev == 1 and cur == 0 and t > t_write:
                    return t, next((t2 for t2, v in samples if t2 > t and v == 1), -1)
            return None

        for _ in range(IRQ_EDGE_LIMIT):
            if fall() is not None:
                break
            await RisingEdge(self.dut.clk_periph)
        found = fall()
        stop.append(1)
        await probe
        assert found is not None, (
            f"S3: uart_interrupt never fell after the THR write; samples {samples[-8:]}; "
            f"{self._state()}"
        )
        t_fall, t_rise = found
        self._end("irq_fall", f"fell at {t_fall}ps, next high at {t_rise}ps")
        lsr = await self._rd_lsr("S3_LSR_BUSY")
        assert not lsr & LSR_TEMT, (
            f"S3: the character had drained (LSR=0x{lsr:x}) after uart_interrupt fell; "
            f"{self._state()}"
        )
        await self._drain_tx("S3_C")
        self._step("S3")
        self._chk(
            "CHK-UART-THRE-WRITE-CLEARS",
            "S3",
            "uart_interrupt read 1 with ID 1 pending (after %d clk_periph edges) and fell %d ps "
            "after the THR write of 0x%02x (next high at %d ps, %d ps after the fall) while "
            "the character was still transmitting (LSR=0x%x, TEMT clear)",
            edges_high,
            t_fall - t_write,
            CHAR_C,
            t_rise,
            t_rise - t_fall if t_rise >= 0 else -1,
            lsr,
        )

    async def _s4(self) -> None:
        first = await self._expect_thre("S4_FIRST")
        second = await self._rd_iir("S4_SECOND_IIR")
        assert not _pending(second), (
            f"S4: IIR=0x{second:x} ({_text(second)}) after the read that showed ID 1; the "
            f"second read must report pending 1"
        )
        await self._send("S4_THR_D", CHAR_D)
        await self._drain_tx("S4_D")
        await self._drain_rbr("S4")
        await self.csr_write("S4_IER", self.ier, IER_ETBEI | IER_ERBFI)
        await self.csr_write("S4_ITR", self.itr, ITR_TRBFI)
        high = await self._rd_iir("S4_HIGH_IIR")
        assert _pending(high) and _id(high) == ID_RDR, (
            f"S4: IIR=0x{high:x} is {_text(high)} with ITR.TRBFI forced and ID 1 pending; "
            f"ID 2 was required first"
        )
        await self.csr_write("S4_ITR_CLR", self.itr, 0)
        await self.csr_write("S4_IER_ETBEI", self.ier, IER_ETBEI)
        low = await self._rd_iir("S4_LOW_IIR")
        assert _pending(low) and _id(low) == ID_THRE, (
            f"S4: IIR=0x{low:x} is {_text(low)} after the higher source was cleared; ID 1 was lost"
        )
        self._step("S4")
        self._chk(
            "CHK-UART-THRE-IIR-CLEAR",
            "S4",
            "IIR=0x%x showed %s then IIR=0x%x showed %s (cleared by the read); with ITR.TRBFI "
            "forced IIR=0x%x showed %s, ID 1 stayed pending and IIR=0x%x showed %s once the "
            "forced source was cleared",
            first,
            _text(first),
            second,
            _text(second),
            high,
            _text(high),
            low,
            _text(low),
        )

    async def _s5(self) -> None:
        await self._send("S5_THR", CHAR_E)
        await self._drain_tx("S5")
        iir = await self._expect_thre("S5")
        self._step("S5")
        self._chk(
            "CHK-UART-THRE-REARM",
            "S5",
            "after the clear the character 0x%02x drained (LSR=0x%x) and IIR=0x%x reported %s "
            "again",
            CHAR_E,
            self.last_lsr,
            iir,
            _text(iir),
        )

    async def _s6(self) -> None:
        await self.csr_write("S6_IER", self.ier, 0)
        await self._drain_rbr("S6")
        await self._send("S6_THR", CHAR_F)
        await self._drain_tx("S6")
        samples = []
        for n in range(MASK_SAMPLES):
            iir = await self._rd_iir(f"S6_{n}")
            assert not (_pending(iir) and _id(iir) == ID_THRE), (
                f"S6: IIR=0x{iir:x} reported ID 1 with ETBEI clear (sample {n}); {self._state()}"
            )
            samples.append(f"0x{iir:x}")
        lsr = await self._rd_lsr("S6_LSR")
        assert lsr & LSR_THRE, f"S6: LSR=0x{lsr:x} has THRE clear with the buffer drained"
        self._step("S6")
        self._chk(
            "CHK-UART-THRE-MASK",
            "S6",
            "with ETBEI clear and the buffer drained %d IIR samples [%s] never reported ID 1 "
            "and LSR=0x%x read THRE=1",
            MASK_SAMPLES,
            ",".join(samples),
            lsr,
        )

    async def _s7(self) -> None:
        await self._drain_rbr("S7")
        lsr_pre = await self._rd_lsr("S7_LSR_PRE")
        assert lsr_pre & LSR_THRE, f"S7: LSR=0x{lsr_pre:x} has THRE clear with an empty buffer"
        await self.csr_write("S7_IER", self.ier, IER_ETBEI)
        reported = None
        for n in range(ARM_POLL_LIMIT):
            iir = await self._rd_iir(f"S7_FIRST_{n}")
            if _pending(iir):
                reported = (n + 1, iir)
                break
        self._wait("etbei_empty_probe", f"{ARM_POLL_LIMIT}_reads")
        again = await self._rd_iir("S7_AGAIN")
        lsr = await self._rd_lsr("S7_LSR")
        self._end(
            "etbei_empty_probe",
            f"ID 1 reported={reported is not None} again=0x{again:x} LSR=0x{lsr:x}",
        )
        assert lsr & LSR_THRE, f"S7: LSR=0x{lsr:x} has THRE clear with an empty buffer"
        if reported is None:
            assert not _pending(again), (
                f"S7: IIR=0x{again:x} reported {_text(again)} after reads that reported none"
            )
            shown = f"no ID 1 within {ARM_POLL_LIMIT} IIR reads"
        else:
            reads, iir = reported
            assert _id(iir) == ID_THRE, f"S7: IIR=0x{iir:x} reported {_text(iir)}, not ID 1"
            assert not (_pending(again) and _id(again) == ID_THRE), (
                f"S7: IIR=0x{again:x} reported ID 1 again after the read that cleared it"
            )
            shown = f"ID 1 reported on IIR read {reads} (IIR=0x{iir:x}) and cleared by it"
        self._step("S7")
        self._chk(
            "CHK-UART-THRE-ETBEI-EMPTY",
            "S7",
            "with ETBEI set on an already empty buffer and LSR=0x%x read before and 0x%x after: "
            "%s, the next IIR read 0x%x; owner answer pending",
            lsr_pre,
            lsr,
            shown,
            again,
        )

    async def _s8(self) -> None:
        await self._send("S8_THR", CHAR_G)
        lsr_set = await self._wait_lsr("S8", LSR_TEMT | LSR_THRE | LSR_DR)
        iir = await self._expect_thre("S8")
        lsr = await self._rd_lsr("S8_LSR_AFTER")
        assert lsr & LSR_THRE and lsr & LSR_TEMT, (
            f"S8: LSR=0x{lsr:x} after the THRE interrupt was cleared by the IIR read; THRE "
            f"must stay 1 with the buffer empty"
        )
        self._step("S8")
        self._chk(
            "CHK-UART-LSR-THRE-STICKY",
            "S8",
            "LSR=0x%x read THRE=1 with ID 1 pending (IIR=0x%x); after the IIR read cleared it "
            "LSR=0x%x still read THRE=1 and TEMT=1",
            lsr_set,
            iir,
            lsr,
        )

    async def _clear_line_status(self) -> None:
        name = "line_status_clear"
        self._wait(name, f"{RBR_DRAIN_LIMIT}_LSR_reads")
        for n in range(RBR_DRAIN_LIMIT):
            lsr = await self._rd_lsr("S9_SVC_LSR")
            if not lsr & LSR_ERRORS:
                self._end(name, f"LSR=0x{lsr:x} after {n + 1} reads")
                return
            if lsr & LSR_DR:
                await self.csr_read("S9_SVC_RBR_ERR", self.rbr)
        raise AssertionError(f"S9: line status errors never cleared; {self._state()}")

    async def _service(self) -> list[int]:
        visited: list[int] = []
        self._wait("service_loop", f"{SERVICE_LIMIT}_iir_reads")
        for n in range(SERVICE_LIMIT):
            iir = self.last_iir if n == 0 else await self._rd_iir(f"S9_SVC_{n}")
            if not _pending(iir):
                self._end("service_loop", f"pending reads 1 after {len(visited)} sources")
                return visited
            ident = _id(iir)
            visited.append(ident)
            if ident == ID_RDR:
                await self.csr_read("S9_SVC_RBR", self.rbr)
                await self._drain_rbr("S9_SVC")
            elif ident == ID_LSR:
                await self._clear_line_status()
            elif ident == ID_MODEM:
                await self.csr_read("S9_SVC_MSR", self.msr)
        raise AssertionError(f"S9: service loop did not end in {SERVICE_LIMIT} reads {visited}")

    async def _s9(self) -> None:
        await self._drain_rbr("S9_PRE")
        await self.csr_write("S9_IER", self.ier, IER_ETBEI | IER_ERBFI)
        await self._send("S9_THR", CHAR_H)
        await self._wait_lsr("S9", LSR_TEMT | LSR_THRE | LSR_DR)
        both = await self._rd_iir("S9_BOTH_IIR")
        assert _pending(both) and _id(both) == ID_RDR, (
            f"S9: IIR=0x{both:x} is {_text(both)} with received data and THRE pending; "
            f"ID 2 was required first"
        )
        got = (await self.csr_read("S9_RBR", self.rbr)) & 0xFF
        assert got == CHAR_H, f"S9: RBR read 0x{got:02x}, not 0x{CHAR_H:02x}"
        lower = await self._rd_iir("S9_LOWER_IIR")
        assert _pending(lower) and _id(lower) == ID_THRE, (
            f"S9: IIR=0x{lower:x} is {_text(lower)} after the received character was read; "
            f"ID 1 was lost"
        )

        await self._drain_rbr("S9_Q")
        await self.csr_write("S9_IER4", self.ier, IER_ETBEI | IER_ERBFI | IER_ELSI | IER_EDSSI)
        await self.csr_write("S9_MCR_DTR", self.mcr, MCR_LOOP | MCR_DTR)
        await self._send("S9_THR_X", CHAR_X)
        await self._wait_lsr("S9_X", LSR_TEMT | LSR_THRE | LSR_DR)
        await self.csr_read("S9_RBR_X", self.rbr)
        await self.csr_write("S9_BREAK_ON", self.lcr, (WLS_8_BITS & LCR_WLS) | LCR_SET_BREAK)
        await ClockCycles(self.dut.clk_periph, BREAK_CLOCKS)
        await self.csr_write("S9_BREAK_OFF", self.lcr, WLS_8_BITS & LCR_WLS)
        await self._send("S9_THR_Z", CHAR_Z)
        await ClockCycles(self.dut.clk_periph, 2 * FRAME_CLOCKS)
        first = await self._rd_iir("S9_LINE_IIR")
        assert _pending(first) and _id(first) == ID_LSR, (
            f"S9: IIR=0x{first:x} is {_text(first)} with modem, line, received-data and THRE "
            f"pending; ID 3 was required first; {self._state()}"
        )
        visited = await self._service()
        assert visited == [ID_LSR, ID_RDR, ID_THRE, ID_MODEM], (
            f"S9: service loop visited IDs {visited}, required [3, 2, 1, 0] once each"
        )
        self._step("S9")
        self._chk(
            "CHK-UART-ID-ORDER",
            "S9",
            "with received data and THRE pending IIR=0x%x showed %s, RBR read 0x%02x, and "
            "IIR=0x%x then showed %s",
            both,
            _text(both),
            got,
            lower,
            _text(lower),
        )
        self._chk(
            "CHK-UART-ID-SERVICE-LOOP",
            "S9",
            "with modem, line, received-data and THRE sources pending (break LSR.BI mask 0x%x) "
            "servicing by IIR visited IDs %s once each and pending then read 1",
            LSR_BI,
            ",".join(f"0x{i:x}" for i in visited),
        )

    async def _s10(self) -> None:
        await self.csr_write("S10_MCR", self.mcr, MCR_LOOP)
        await self.csr_read("S10_MSR_CLR", self.msr)
        await self._drain_rbr("S10_Q")
        await self._send("S10_THR", CHAR_Y)
        await self._wait_lsr("S10", LSR_TEMT | LSR_THRE | LSR_DR)
        first = await self._rd_iir("S10_FIRST_IIR")
        second = await self._rd_iir("S10_SECOND_IIR")
        for iir in (first, second):
            assert _pending(iir) and _id(iir) == ID_RDR, (
                f"S10: IIR=0x{iir:x} is {_text(iir)} with received data and THRE pending; "
                f"ID 2 was required"
            )
        got = (await self.csr_read("S10_RBR", self.rbr)) & 0xFF
        assert got == CHAR_Y, f"S10: RBR read 0x{got:02x}, not 0x{CHAR_Y:02x}"
        after = await self._rd_iir("S10_AFTER_IIR")
        assert not (_pending(after) and _id(after) == ID_RDR), (
            f"S10: IIR=0x{after:x} still reports ID 2 after the RBR read"
        )
        await self._rd_iir("S10_QUIESCE_IIR")
        self._step("S10")
        self._chk(
            "CHK-UART-ID-IIR-SIDE-EFFECT",
            "S10",
            "two IIR reads 0x%x and 0x%x both showed ID 2, and after the RBR read (0x%02x) "
            "IIR=0x%x showed %s",
            first,
            second,
            got,
            after,
            _text(after),
        )

    async def _s11(self) -> None:
        await self.csr_write("S11_IER_OFF", self.ier, 0)
        await self._drain_rbr("S11")
        await self.csr_write("S11_MCR_OFF", self.mcr, 0)
        await self.csr_write("S11_REGATE", CLOCK_GATE_CONTROL, self.cg)
        self._wait("sep_in_access", f"{self.cfg.axi_timeout_ns}ns_driver_bound")
        self._end("sep_in_access", "every access completed")
        self._step("S11")
        text = " ".join(f"{n}={b} last={s}" for n, (b, s) in self.waits.items())
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits: %s; every expiry raises AssertionError with "
            "the last LSR, IIR and pad state",
            len(self.waits),
            text,
        )

    async def body(self) -> None:
        assert hasattr(self.dut, "uart_interrupt"), "tb_top has no uart_interrupt net"
        assert hasattr(self.dut, "clk_periph"), "tb_top has no clk_periph net"
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        await self._s7()
        await self._s8()
        await self._s9()
        await self._s10()
        await self._s11()

        ids = [s for s, _ in self.stamps]
        assert ids == list(STEPS), f"step order {ids}, expected {list(STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = [c for c, _ in self.chk_marks]
        assert marks == [c for c, _ in CHECKERS], f"checker order {marks}"
        for (chk, step), (_, n) in zip(CHECKERS, self.chk_marks):
            assert self.stamps[n - 1][0] == step, f"{chk} printed after {self.stamps[n - 1][0]}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence %s; checker lines %s; stamps %s",
            " < ".join(FENCE_TERMS),
            ",".join(marks),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )
