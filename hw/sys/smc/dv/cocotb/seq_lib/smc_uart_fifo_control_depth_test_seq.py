# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 FIFO enable change, depth, trigger field composition and receive order over SEP_IN.

Spec sources: hw/ip/uart/uart_16550/doc/{architecture,index}.adoc, hw/sys/smc/doc/periphs.adoc,
hw/ip/uart/uart_16550/regs/uart_16550_main{,_wo}.rdl, doc/programmer/src/smc-programming.adoc.
"""

from __future__ import annotations

import os
import random

import cocotb
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from .smc_addr_map import CLOCK_GATE_CONTROL, UART_CG_EN, uart_16550_main_u32
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_log_engine_utils import (
    DLL_OFFSET,
    DLM_OFFSET,
    FCR_FIFO_ENABLE,
    FCR_OFFSET,
    FCR_RCVR_FIFO_RESET,
    FCR_RCVR_TRIGGER_SHIFT,
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
    RBR_DATA,
    THR_OFFSET,
    WLS_8_BITS,
    arm_uart,
    restore_uart,
    uart_base,
    uart_reg,
)

UART = 0
LSR_OE = uart_16550_main_u32("UART_16550_MAIN__LSR__OE_bm")
ECR_MS2B_SHIFT = uart_16550_main_u32("UART_16550_MAIN__ECR__RCVR_TRIGGER_MS2B_bp")
FCR_RESETS = FCR_RCVR_FIFO_RESET | FCR_XMIT_FIFO_RESET

# uart_16550_main.rdl IIR.INTERRUPT_ID: 0x2 is Received Data Ready, 0x6 Reception Timeout.
ID_RDR = 0x2
ID_RX_TIMEOUT = 0x6
DIVISOR_FAST = 1
DIVISOR_SLOW = 8
# uart_16550/doc/interface.adoc: 16x oversampling, 8N1 frame = 10 bits.
OVERSAMPLE = 16
FRAME_BITS = 10
FIFO_DEPTH = 32

# Drawn trigger leg (RAND-REP), run inside S7: the trigger level is drawn among the five
# encodings at or below the 32-deep receive FIFO (smc-programming.adoc, UART Receive FIFO
# levels: codes 0 to 4 = 1, 4, 8, 14 and 32 characters, code = {ECR.RCVR_TRIGGER_MS2B,
# FCR.RCVR_TRIGGER}), the fill count in [level + 1, 32] below level 32 so that the compares
# below, at and above the level all run (32 at level 32, the only occupancy at the level,
# where nothing lies above it), and the read gap (full drain, or a partial drain before the
# refill). ID 2 is pending while the occupancy is at or above the level
# (uart_16550/doc/architecture.adoc, service table: drain RBR below the trigger to clear it).
# After a full drain neither ID 2 nor the receive timeout ID 6 can be pending (the same table:
# the timeout needs data in the FIFO), so that IIR read is compared; after a partial drain the
# timeout source can preempt ID 2, so that read and the one after the refill are printed.
TRIGGER_LEVELS = (1, 4, 8, 14, 32)
GAPS = ("full", "partial")
POLL_LIMIT_TEMT = 20_000
POLL_LIMIT_DR = 4_000
DRAIN_LIMIT = 40

OLD_CHARS = (0x11, 0x22, 0x33)
BACKLOG_CHARS = tuple(0xA1 + i for i in range(8))
HELD_CHAR = 0x5A
NEXT_CHAR = 0xC3
NONFIFO_CHAR = 0x6B
ORDER_CHARS = (0x3E, 0x5D, 0x7C, 0x9B, 0xBA)
EMPTY_NEXT_CHAR = 0xE7
SAME_CHARS = (0x81, 0x82, 0x83, 0x84)

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9")
CHECKERS = (
    ("CHK-UART-FIFO-ENABLE-CHANGE", "S2"),
    ("CHK-UART-FIFO-DEPTH-32", "S3"),
    ("CHK-UART-FIFO-ENABLE-SAME", "S4"),
    ("CHK-UART-RESET-BITS-NOFIFO", "S5"),
    ("CHK-UART-TRIG-NONFIFO", "S6"),
    ("CHK-UART-TRIG-COMPOSE", "S7"),
    ("CHK-UART-RX-ORDER", "S8"),
    ("CHK-UART-RBR-EMPTY", "S8"),
    ("CHK-TIMEOUT-PATHS", "S9"),
)


def depth_chars(base: int) -> list[int]:
    """Thirty-two distinct characters starting from ``base``."""
    return [(base + 5 * i) & 0xFF for i in range(FIFO_DEPTH)]


def iir_text(iir: int) -> str:
    if iir & IIR_PENDING:
        return f"0x{iir:08x}(none)"
    return f"0x{iir:08x}(id{(iir & IIR_ID) >> IIR_ID_SHIFT:x})"


def rdr_pending(iir: int) -> bool:
    return not iir & IIR_PENDING and (iir & IIR_ID) >> IIR_ID_SHIFT == ID_RDR


def rx_pending(iir: int) -> bool:
    """Is a receive source (ID 2 or the receive timeout ID 6) the pending interrupt?"""
    return not iir & IIR_PENDING and (iir & IIR_ID) >> IIR_ID_SHIFT in (ID_RDR, ID_RX_TIMEOUT)


class smc_uart_fifo_control_depth_test_seq(SmcCsrSeq):
    """FIFO_ENABLE change, depth, non-FIFO trigger, trigger composition and read order."""

    def __init__(self, name: str = "smc_uart_fifo_control_depth_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int]] = []
        self.chk_marks: list[tuple[str, int]] = []
        self.waits: dict[str, list] = {}
        self.divisor = DIVISOR_FAST
        self.lsr_seen = 0
        self.seed = int(os.environ.get("RANDOM_SEED", "1"), 0)
        rng = random.Random(self.seed)
        self.code = rng.randrange(len(TRIGGER_LEVELS))
        self.level = TRIGGER_LEVELS[self.code]
        if self.level < FIFO_DEPTH:
            self.fill = rng.randint(self.level + 1, FIFO_DEPTH)
        else:
            self.fill = FIFO_DEPTH
        self.gap = rng.choice(GAPS)
        self.drain_part = rng.randint(1, self.fill - 1) if self.gap == "partial" else self.fill
        cocotb.log.info(
            "RAND-SEED: %d; RAND-DRAW: trigger code %d (level %d characters), fill %d, "
            "read gap %s (drain %d of %d before the refill)",
            self.seed,
            self.code,
            self.level,
            self.fill,
            self.gap,
            self.drain_part,
            self.fill,
        )
        base = uart_base(UART)
        self.thr = base + THR_OFFSET
        self.fcr = base + FCR_OFFSET
        self.r = {k: uart_reg(UART, k.upper()) for k in ("rbr", "ier", "iir", "lcr", "lsr", "ecr")}

    def _step(self, step_id: str) -> None:
        self.stamps.append((step_id, int(get_sim_time("ps"))))

    def _chk(self, chk_id: str, step_id: str, text: str, *args) -> None:
        assert self.stamps and self.stamps[-1][0] == step_id, (
            f"{chk_id} printed before its step {step_id} completed; stamps {self.stamps}"
        )
        self.chk_marks.append((chk_id, len(self.stamps)))
        cocotb.log.info("%s: " + text, chk_id, *args)

    def _pad(self) -> str:
        dut = cocotb.top
        assert hasattr(dut, "tb_uart0_tx_from_dut"), "tb_uart0_tx_from_dut is not exported"
        sig = dut.tb_uart0_tx_from_dut.value
        assert sig.is_resolvable, f"UART0 TX pad is unresolved ({sig})"
        return f"tx{int(sig)}"

    async def _lsr(self, tag: str) -> int:
        return await self.csr_read(tag, self.r["lsr"])

    async def _iir(self, tag: str) -> int:
        return await self.csr_read(tag, self.r["iir"])

    async def _poll_lsr(self, name: str, mask: int, limit: int) -> int:
        """Read LSR until ``mask`` is set; raise with the last LSR, IIR and pad state."""
        lsr = 0
        for _ in range(limit):
            lsr = await self._lsr(f"{name}_LSR")
            self.lsr_seen |= lsr
            self.waits[name] = [f"{limit}polls", f"lsr=0x{lsr:08x},{self._pad()}"]
            if lsr & mask:
                return lsr
        iir = await self._iir(f"{name}_IIR_EXPIRED")
        raise AssertionError(
            f"{name}: LSR mask 0x{mask:x} not set within {limit} polls; last lsr=0x{lsr:08x} "
            f"iir={iir_text(iir)} pad={self._pad()}"
        )

    async def _wait_temt(self, name: str) -> int:
        return await self._poll_lsr(f"TEMT_{name}", LSR_TEMT, POLL_LIMIT_TEMT)

    async def _wait_dr(self, name: str) -> int:
        return await self._poll_lsr(f"DR_{name}", LSR_DR, POLL_LIMIT_DR)

    async def _send(self, tag: str, chars) -> None:
        for i, ch in enumerate(chars):
            await self.csr_write(f"{tag}_THR{i}", self.thr, ch)

    async def _loop_chars(self, tag: str, chars) -> int:
        """Write ``chars`` to THR and wait until the receiver holds them."""
        await self._send(tag, chars)
        await self._wait_temt(tag)
        return await self._wait_dr(tag)

    async def _rbr(self, tag: str) -> int:
        return (await self.csr_read(tag, self.r["rbr"])) & RBR_DATA

    async def _set_divisor(self, tag: str, divisor: int) -> None:
        base = uart_base(UART)
        await self.csr_write(f"{tag}_LCR_DLAB", self.r["lcr"], LCR_DLAB)
        await self.csr_write(f"{tag}_DLL", base + DLL_OFFSET, divisor)
        await self.csr_write(f"{tag}_DLM", base + DLM_OFFSET, 0)
        await self.csr_write(f"{tag}_LCR", self.r["lcr"], WLS_8_BITS & LCR_WLS)
        self.divisor = divisor

    async def _fcr(self, tag: str, trigger: int, enable: bool, resets: bool) -> None:
        value = (trigger << FCR_RCVR_TRIGGER_SHIFT) | (FCR_FIFO_ENABLE if enable else 0)
        await self.csr_write(tag, self.fcr, value | (FCR_RESETS if resets else 0))

    async def _drain(self, tag: str) -> list[int]:
        """Read RBR while LSR.DR is set; bounded, the DR flag must clear."""
        got = []
        for _ in range(DRAIN_LIMIT):
            if not await self._lsr(f"{tag}_LSR") & LSR_DR:
                self.waits[f"DRAIN_{tag}"] = [f"{DRAIN_LIMIT}reads", f"chars={got}"]
                return got
            got.append(await self._rbr(f"{tag}_RBR"))
        raise AssertionError(
            f"{tag}: LSR.DR still set after {DRAIN_LIMIT} reads, characters read {got}"
        )

    async def _tolerant(self, tag: str, op: SmcSysAxiOp, addr: int, data: int = 0):
        """One access whose response code is recorded rather than required."""
        item = SmcSysAxiItem(f"{op.value}_{tag}")
        item.op = op
        item.addr = addr
        item.length = 4
        item.wdata = data
        item.allow_error = True
        await self.start_item(item)
        await self.finish_item(item)
        self.accesses += 1
        return item

    async def _s1(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        self.cg = cg
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await arm_uart(self, UART)
        await self.csr_write("IER_ERBFI", self.r["ier"], IER_ERBFI)
        await self.csr_write("ECR_0", self.r["ecr"], 0)
        await self._fcr("FCR_RESET", 0, True, True)
        await self._lsr("LSR_S1")
        self._step("S1")

    async def _s2(self) -> None:
        await self._loop_chars("S2_OLD", OLD_CHARS)
        await self._set_divisor("S2_SLOW", DIVISOR_SLOW)
        await self._send("S2_BACKLOG", BACKLOG_CHARS)
        before = await self._lsr("S2_LSR_BEFORE")
        assert before & LSR_DR and not before & LSR_THRE, (
            f"S2: before the change LSR=0x{before:08x}, expected DR=1 and THRE=0 with data buffered"
        )
        await self._fcr("S2_FCR_OFF", 0, False, False)
        await self._fcr("S2_FCR_ON", 0, True, False)
        after = await self._lsr("S2_LSR_AFTER")
        assert not after & LSR_DR and after & LSR_THRE, (
            f"S2: after FIFO_ENABLE 0 then 1 LSR=0x{after:08x}, expected DR=0 and THRE=1"
        )
        await self._wait_temt("S2_CHANGE")
        await ClockCycles(cocotb.top.clk_periph, OVERSAMPLE * FRAME_BITS * (self.divisor + 1))
        late = await self._lsr("S2_LSR_LATE")
        iir = await self._iir("S2_IIR")
        assert late & LSR_THRE, f"S2: a frame after TEMT LSR=0x{late:08x}, expected THRE=1"
        read = await self._drain("S2_DRAIN")
        assert read in ([], [BACKLOG_CHARS[0]]), (
            f"S2: characters {read} readable after the change; only the frame already in the "
            f"shift register ({BACKLOG_CHARS[0]:#x}) may arrive, never an old or queued character"
        )
        self._step("S2")
        self._chk(
            "CHK-UART-FIFO-ENABLE-CHANGE",
            "S2",
            "before FIFO_ENABLE 0 then 1 LSR=0x%08x (DR=1, THRE=0, %d backlog writes); after it "
            "LSR=0x%08x (DR=0, THRE=1); TEMT followed and a frame later LSR=0x%08x (THRE=1); "
            "IIR %s; characters readable %s, none old or queued, only the frame already "
            "shifting at the change may arrive (allowance not specified, measured)",
            before,
            len(BACKLOG_CHARS),
            after,
            late,
            iir_text(iir),
            [f"0x{c:02x}" for c in read],
        )

    async def _s3(self) -> None:
        chars = depth_chars(0x31)
        self.lsr_seen = 0
        await self._send("S3_FILL", chars)
        busy = await self._lsr("S3_LSR_BUSY")
        assert not busy & LSR_THRE, f"S3: THRE set after 32 unpolled writes (LSR=0x{busy:08x})"
        await self._wait_temt("S3_32")
        full = await self._wait_dr("S3_32")
        assert not full & LSR_OE and not self.lsr_seen & LSR_OE, (
            f"S3: overrun during 32 characters (LSR=0x{full:08x}, seen=0x{self.lsr_seen:08x})"
        )
        got = [await self._rbr(f"S3_RBR{i}") for i in range(FIFO_DEPTH)]
        assert got == chars, f"S3: read {got}, expected {chars}"
        tail = await self._lsr("S3_LSR_TAIL")
        assert not tail & (LSR_OE | LSR_DR) and not self.lsr_seen & LSR_OE, (
            f"S3: after the 32 reads LSR=0x{tail:08x}, seen=0x{self.lsr_seen:08x}"
        )
        over = [(0x91 + 5 * i) & 0xFF for i in range(FIFO_DEPTH + 1)]
        self.lsr_seen = 0
        await self._send("S3_OVER", over)
        await self._wait_temt("S3_OVER")
        await ClockCycles(cocotb.top.clk_periph, OVERSAMPLE * FRAME_BITS * (self.divisor + 1))
        self.lsr_seen |= await self._lsr("S3_LSR_OVER")
        assert self.lsr_seen & LSR_OE, (
            f"S3: no overrun after {len(over)} characters with no RBR read "
            f"(seen=0x{self.lsr_seen:08x}), a {FIFO_DEPTH}-deep receive FIFO must overrun"
        )
        kept = [await self._rbr(f"S3_OVER_RBR{i}") for i in range(FIFO_DEPTH)]
        assert kept == over[:FIFO_DEPTH], f"S3: overrun read {kept}, expected {over[:FIFO_DEPTH]}"
        left = await self._lsr("S3_LSR_OVER_TAIL")
        assert not left & LSR_DR, f"S3: DR still set after {FIFO_DEPTH} reads (LSR=0x{left:08x})"
        seen_over = self.lsr_seen
        await self._send("S3_FILL2", chars)
        item = await self._tolerant("S3_THR33", SmcSysAxiOp.WRITE, self.thr, 0x7E)
        thre33 = await self._lsr("S3_LSR_33")
        await self._wait_temt("S3_33")
        await self._wait_dr("S3_33")
        extra = await self._drain("S3_DRAIN")
        flags = await self._lsr("S3_LSR_FLAGS")
        self._step("S3")
        self._chk(
            "CHK-UART-FIFO-DEPTH-32",
            "S3",
            "32 unpolled THR writes left LSR.THRE=0 (LSR=0x%08x), all 32 were received and the "
            "32 RBR reads equal the written sequence in order with LSR.OE clear (LSR=0x%08x); 33 "
            "characters sent with no RBR read set LSR.OE (seen 0x%08x) and exactly the first 32 "
            "were read with LSR.DR=0 after them (LSR=0x%08x), a 32-entry receive FIFO that drops "
            "the new character on overrun; a "
            "33rd THR write after 32 writes completed with resp=%s, LSR=0x%08x, then %d "
            "characters were readable with LSR=0x%08x (not specified, measured)",
            busy,
            full,
            seen_over,
            left,
            item.resp_code,
            thre33,
            len(extra),
            flags,
        )

    async def _s4(self) -> None:
        await self._set_divisor("S4_FAST", DIVISOR_FAST)
        await self._loop_chars("S4", SAME_CHARS)
        await self._fcr("S4_FCR_ON1", 0, True, False)
        mid = await self._lsr("S4_LSR_MID")
        await self._fcr("S4_FCR_ON2", 0, True, False)
        got = await self._drain("S4_DRAIN")
        final = await self._lsr("S4_LSR_FINAL")
        assert got in ([], list(SAME_CHARS)) and not final & LSR_DR, (
            f"S4: readable {got}, expected none or {list(SAME_CHARS)}; final LSR=0x{final:08x}"
        )
        self._step("S4")
        self._chk(
            "CHK-UART-FIFO-ENABLE-SAME",
            "S4",
            "after %d characters were held a second FIFO_ENABLE=1 write completed; LSR after the "
            "first write 0x%08x; %d of %d characters were still readable %s, each read preceded "
            "by LSR.DR=1 and LSR.DR=0 after the last (LSR=0x%08x) (not specified, measured)",
            len(SAME_CHARS),
            mid,
            len(got),
            len(SAME_CHARS),
            [f"0x{c:02x}" for c in got],
            final,
        )

    async def _s5(self) -> None:
        await self._fcr("S5_FCR_OFF", 0, False, False)
        await self._drain("S5_CLEAR")
        await self._loop_chars("S5_HELD", (HELD_CHAR,))
        await self._fcr("S5_FCR_RESETS", 0, False, True)
        lsr = await self._lsr("S5_LSR")
        kept = None
        if lsr & LSR_DR:
            kept = await self._rbr("S5_RBR")
            assert kept == HELD_CHAR, f"S5: the held character read back as 0x{kept:02x}"
        after = await self._lsr("S5_LSR_AFTER")
        assert not after & LSR_DR, f"S5: LSR.DR still set after the read (0x{after:08x})"
        await self._loop_chars("S5_NEXT", (NEXT_CHAR,))
        got = await self._rbr("S5_RBR_NEXT")
        assert got == NEXT_CHAR, f"S5: next character read 0x{got:02x}, not 0x{NEXT_CHAR:02x}"
        self._step("S5")
        self._chk(
            "CHK-UART-RESET-BITS-NOFIFO",
            "S5",
            "FCR written with FIFO_ENABLE clear and both reset bits completed; the held character "
            "%s (LSR=0x%08x, DR consistent with RBR); the next character read back intact as "
            "0x%02x (not specified, measured)",
            "survived" if kept is not None else "did not survive",
            lsr,
            got,
        )

    async def _s6(self) -> None:
        await self.csr_write("S6_ECR", self.r["ecr"], 1 << ECR_MS2B_SHIFT)
        seen = []
        for trigger in (3, 1):
            await self._fcr(f"S6_FCR{trigger}", trigger, False, False)
            await self._loop_chars(f"S6_T{trigger}", (NONFIFO_CHAR,))
            iir = await self._iir(f"S6_IIR{trigger}")
            lsr = await self._lsr(f"S6_LSR{trigger}")
            assert rdr_pending(iir) and lsr & LSR_DR, (
                f"S6: FCR trigger {trigger}: IIR={iir_text(iir)} LSR=0x{lsr:08x}, expected ID 2 "
                f"pending and DR=1 with the FIFOs off"
            )
            got = await self._rbr(f"S6_RBR{trigger}")
            assert got == NONFIFO_CHAR, f"S6: read 0x{got:02x}, not 0x{NONFIFO_CHAR:02x}"
            seen.append((trigger, iir, lsr))
        self._step("S6")
        self._chk(
            "CHK-UART-TRIG-NONFIFO",
            "S6",
            "with the FIFOs off and ECR=1 one character made IIR report pending ID 2 and LSR.DR "
            "read 1 for FCR trigger field %s (IIR %s, LSR %s)",
            "/".join(str(t) for t, _, _ in seen),
            "/".join(iir_text(i) for _, i, _ in seen),
            "/".join(f"0x{lsr:08x}" for _, _, lsr in seen),
        )

    async def _onset(self, label: str, ecr: int, trigger: int) -> int | None:
        """Loop characters one at a time; return the occupancy at which IIR first reports ID 2."""
        await self.csr_write(f"S7_{label}_ECR", self.r["ecr"], ecr << ECR_MS2B_SHIFT)
        await self._fcr(f"S7_{label}_FCR", trigger, True, True)
        onset = None
        for n, ch in enumerate(depth_chars(0x40), start=1):
            await self._loop_chars(f"S7_{label}", (ch,))
            iir = await self._iir(f"S7_{label}_IIR{n}")
            if rdr_pending(iir):
                onset = n
                break
        await self._drain(f"S7_{label}_DRAIN")
        return onset

    async def _drawn_trigger(self) -> str:
        """Fill the receive FIFO to the drawn count under the drawn level; compare IIR per char.

        Below the level no received-data interrupt (ID 2) is pending; at the level and above it
        one is (architecture.adoc service table: ID 2 is cleared by draining RBR below the
        trigger). Then the drawn read gap: a full drain, after which neither ID 2 nor the receive
        timeout ID 6 may be pending (compared), or a partial one, after which the interrupt is
        printed; a one-character refill with its interrupt printed, and a final drain.
        """
        label = "DRAWN"
        await self.csr_write(f"S7_{label}_ECR", self.r["ecr"], (self.code >> 2) << ECR_MS2B_SHIFT)
        await self._fcr(f"S7_{label}_FCR", self.code & 3, True, True)
        at_level = None
        below = above = 0
        for n, ch in enumerate(depth_chars(0x60)[: self.fill], start=1):
            await self._loop_chars(f"S7_{label}", (ch,))
            iir = await self._iir(f"S7_{label}_IIR{n}")
            pending = rdr_pending(iir)
            if n < self.level:
                assert not pending, (
                    f"S7 drawn: ID 2 pending at occupancy {n} below the level {self.level} "
                    f"(IIR {iir_text(iir)})"
                )
                below += 1
            elif n > self.level:
                assert pending, (
                    f"S7 drawn: no ID 2 pending at occupancy {n} above the level {self.level} "
                    f"(IIR {iir_text(iir)})"
                )
                above += 1
            else:
                assert pending, (
                    f"S7 drawn: no ID 2 pending at occupancy {n}, the level {self.level} "
                    f"(IIR {iir_text(iir)})"
                )
                at_level = iir_text(iir)
        assert at_level is not None, (
            f"S7 drawn: fill {self.fill} below the level {self.level}, no compare at it"
        )
        # Below level 32 the fill is drawn above the level, so a compare above it ran.
        assert self.level == FIFO_DEPTH or above > 0, (
            f"S7 drawn: fill {self.fill} at or below the level {self.level}, no compare above it"
        )
        drained = []
        for i in range(self.drain_part):
            drained.append(await self._rbr(f"S7_{label}_RBR{i}"))
        after_gap = await self._iir(f"S7_{label}_IIR_GAP")
        if self.gap == "full":
            # Occupancy 0: the service table lets neither ID 2 nor the timeout stay pending.
            assert not rx_pending(after_gap), (
                f"S7 drawn: a receive interrupt pending after the full drain of {self.fill} "
                f"characters (IIR {iir_text(after_gap)})"
            )
        await self._loop_chars(f"S7_{label}_REFILL", (0xD5,))
        after_refill = await self._iir(f"S7_{label}_IIR_REFILL")
        rest = await self._drain(f"S7_{label}_DRAIN")
        want = depth_chars(0x60)[: self.fill] + [0xD5]
        assert drained + rest == want, f"S7 drawn: read {drained + rest}, expected {want} in order"
        gap_note = "compared: no ID 2 or ID 6" if self.gap == "full" else "printed"
        return (
            f"drawn=seed {self.seed} level {self.level} (code {self.code}) fill {self.fill}: "
            f"ID 2 absent at {below} occupancies below the level, present at the level "
            f"({at_level}) and at {above} above it (compared); "
            f"read gap "
            f"{self.gap}: {self.drain_part} of {self.fill} drained, IIR after the gap "
            f"{iir_text(after_gap)} ({gap_note}), after a one-character refill "
            f"{iir_text(after_refill)} (printed); every character read back in order"
        )

    async def _s7(self) -> None:
        a = await self._onset("A", 1, 0)
        b = await self._onset("B", 1, 1)
        c = await self._onset("C", 1, 0)
        d = await self._onset("D", 0, 0)
        drawn = await self._drawn_trigger()
        await self._fcr("S7_FCR_CLR", 0, True, True)
        self._step("S7")
        assert a is not None, "S7 A: no ID 2 within 32 characters at ECR=1 FCR field 0"
        assert b is None, f"S7 B: ID 2 first at occupancy {b} within 32 characters at ECR=1 FCR 1"
        assert c == a, f"S7: onset(C)={c} differs from onset(A)={a}"
        assert d is not None and d < a, f"S7: onset(D)={d} not below onset(A)={a}"
        text = {k: "none within 32" if v is None else str(v) for k, v in zip("ABCD", (a, b, c, d))}
        self._chk(
            "CHK-UART-TRIG-COMPOSE",
            "S7",
            "ID-2 onset occupancy per {ECR, FCR[7:6]} state: A (ECR=1, FCR=0) %s; B (ECR=1, FCR=1) "
            "%s; C (FCR back to 0, ECR=1) %s; D (ECR=0, FCR=0) %s; onset(A)==onset(C), no ID 2 "
            "in B while A has one, onset(D)<onset(A); exact values measured only "
            "(not specified, measured); %s",
            text["A"],
            text["B"],
            text["C"],
            text["D"],
            drawn,
        )

    async def _s8(self) -> None:
        await self._loop_chars("S8", ORDER_CHARS)
        flags = []
        for i, ch in enumerate(ORDER_CHARS):
            lsr = await self._lsr(f"S8_LSR{i}")
            assert lsr & LSR_DR, f"S8: DR clear before read {i} (LSR=0x{lsr:08x})"
            got = await self._rbr(f"S8_RBR{i}")
            assert got == ch, f"S8: read {i} returned 0x{got:02x}, expected 0x{ch:02x}"
            post = await self._lsr(f"S8_LSR_POST{i}")
            last = i == len(ORDER_CHARS) - 1
            assert bool(post & LSR_DR) is not last, (
                f"S8: after read {i} LSR=0x{post:08x}, DR expected {0 if last else 1}"
            )
            flags.append(int(bool(post & LSR_DR)))
        before = await self._lsr("S8_LSR_EMPTY_BEFORE")
        assert not before & LSR_DR, f"S8: receive buffer not empty (LSR=0x{before:08x})"
        item = await self._tolerant("S8_RBR_EMPTY", SmcSysAxiOp.READ, self.r["rbr"])
        after = await self._lsr("S8_LSR_EMPTY_AFTER")
        await self._loop_chars("S8_NEXT", (EMPTY_NEXT_CHAR,))
        lsr = await self._lsr("S8_LSR_NEXT")
        assert lsr & LSR_DR, f"S8: DR clear after the next character (LSR=0x{lsr:08x})"
        got = await self._rbr("S8_RBR_NEXT")
        assert got == EMPTY_NEXT_CHAR, f"S8: next character read 0x{got:02x}"
        self._step("S8")
        self._chk(
            "CHK-UART-RX-ORDER",
            "S8",
            "five looped characters read from RBR in arrival order %s with LSR.DR after each "
            "read %s (last 0)",
            [f"0x{c:02x}" for c in ORDER_CHARS],
            flags,
        )
        self._chk(
            "CHK-UART-RBR-EMPTY",
            "S8",
            "an RBR read with the receive buffer empty completed with resp=%s data=0x%08x, LSR "
            "before 0x%08x after 0x%08x; the character looped afterwards was received intact as "
            "0x%02x with DR=1 (LSR=0x%08x) (not specified, measured)",
            item.resp_code,
            item.rdata,
            before,
            after,
            got,
            lsr,
        )

    def _s9(self) -> None:
        self._step("S9")
        bound = self.env.cfg.axi_timeout_ns
        parts = " ".join(f"{n}={b} last={s}" for n, (b, s) in self.waits.items())
        self._chk(
            "CHK-TIMEOUT-PATHS",
            "S9",
            "%d bounded waits, each raising AssertionError on expiry (LSR polls with the last LSR, "
            "IIR and pad state, drain loops with the characters read, SEP_IN access with the "
            "driver's own timeout): SEP_IN_AXI=%dns %s",
            len(self.waits) + 1,
            bound,
            parts,
        )

    async def body(self) -> None:
        await self._s1()
        await self._s2()
        await self._s3()
        await self._s4()
        await self._s5()
        await self._s6()
        await self._s7()
        await self._s8()
        await restore_uart(self, UART)
        await self.csr_write("UART_REGATE", CLOCK_GATE_CONTROL, self.cg)
        self._s9()
        ids = [s for s, _ in self.stamps]
        assert ids == list(STEPS), f"step order {ids}, expected {list(STEPS)}"
        times = [t for _, t in self.stamps]
        assert all(b > a for a, b in zip(times, times[1:])), f"stamps not increasing: {times}"
        marks = [c for c, _ in self.chk_marks]
        assert marks == [c for c, _ in CHECKERS], f"checker order {marks}"
        for (chk, step), (_, n) in zip(CHECKERS, self.chk_marks):
            assert self.stamps[n - 1][0] == step, f"{chk} printed after {self.stamps[n - 1][0]}"
        cocotb.log.info(
            "CHK-NONVAC: ordered fence MODE_CHANGE < DEPTH_32 < SAME_ENABLE < RESET_BITS_NOFIFO < "
            "NONFIFO_TRIGGER < TRIGGER_COMPOSE < RX_ORDER < EMPTY_READ; checker lines %s; "
            "stamps %s",
            ",".join(marks),
            ",".join(f"{s}={t}" for s, t in self.stamps),
        )
