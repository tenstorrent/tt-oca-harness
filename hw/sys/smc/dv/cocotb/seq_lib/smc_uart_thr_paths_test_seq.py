# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""UART0 transmit-holding and receive paths that only unusual programming reaches.

Every UART leaf programs a non-zero divisor before it writes `THR`, writes
whole words, and leaves the trigger level on a documented code. Four other
programmings, each in `MCR.LOOP` so the character comes back through UART0's
own receiver and no pad carries it (`uart_16550_main.rdl`: "the transmitter
is internally connected to the receiver"):

* **A character written before the divisor.** With the divisor latches at 0
  the baud generator does not run, so a character written to `THR` has to
  wait there: `LSR.THRE` clear, nothing received. A second write while it
  waits finds `THR` occupied. Once the divisor is programmed exactly one
  character must arrive; which of the two is recorded, since no document
  says whether the second write replaces the first or is dropped. The FIFOs
  are off for this leg, with `FCR.DMA_MODE_SELECT` set, a DMA mode the RDL
  ties to FIFO operation.
* **A byte write to the wrong lane.** `THR` holds its character in bits
  [7:0]; a write that enables only the lane above carries no character, so
  nothing may be transmitted, and a following whole write must be.
* **A character left unread with the FIFOs off.** The character sits in
  `RBR` for well over the four character times of the reception timeout.
  What `IIR` then reports is recorded; the character must still read back
  intact.
* **A trigger level the RDL does not list.** `ECR.RCVR_TRIGGER_MS2B` and
  `FCR.RCVR_TRIGGER` together select a level, and the RDL lists codes up to
  0xB. Code 0xC is programmed with the FIFOs on; the character must be
  received intact, and what `IIR` shows is recorded.
* **A character cut off.** The divisor is taken to 0 part-way through a
  character, which stops the baud generator under the transmitter. What LSR
  then shows and how much of the cut character arrives are recorded, since no
  document says; once the divisor is restored, a following character must read
  back intact.
"""

from __future__ import annotations

import cocotb
from cocotb.triggers import Timer

from .smc_addr_map import UART_CG_EN, smc_indexed_addr
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_uart_rbr_error_path_test_seq import (
    _UART_H,
    _UART_WO_H,
    CLOCK_GATE_CONTROL,
    ECR_TRIGGER_MS2B_BP,
    FCR_FIFO_ENABLE,
    IER_ERBFI,
    IIR_INTERRUPT_ID,
    IIR_INTERRUPT_ID_BP,
    IIR_INTERRUPT_PENDING,
    LCR_DLAB,
    LSR_DR,
    UART_EN,
    WLS_8,
    _field_mask,
    _uart_reg,
)

UART = 0
MCR_LOOP = _field_mask(_UART_H, "UART_16550_MAIN__MCR__LOOP_bm")
LSR_THRE = _field_mask(_UART_H, "UART_16550_MAIN__LSR__THRE_bm")
LSR_TEMT = _field_mask(_UART_H, "UART_16550_MAIN__LSR__TEMT_bm")
FCR_DMA_MODE = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__DMA_MODE_SELECT_bm")
FCR_RESETS = _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__RCVR_FIFO_RESET_bm") | (
    _field_mask(_UART_WO_H, "UART_16550_MAIN_WO__FCR__XMIT_FIFO_RESET_bm")
)
#: ECR.RCVR_TRIGGER_MS2B = 3 with FCR.RCVR_TRIGGER = 0: code 0xC, past the
#: last level `uart_16550_main.rdl` lists (0xB).
UNLISTED_MS2B = 0x3

FIRST_BYTE = 0x5A
SECOND_BYTE = 0xA5
LANE_BYTE = 0x3C
WHOLE_BYTE = 0xC3
UNREAD_BYTE = 0x96
UNLISTED_BYTE = 0x69
DIVISOR = 1
#: A divisor slow enough that a character spans microseconds, and how far into
#: one the divisor is taken away.
SLOW_DIVISOR = 16
CUT_AFTER_NS = 5_000
CUT_BYTE = 0x3F
#: Long enough for several characters at the divisor above.
CHAR_WAIT_NS = 20_000
POLL_LIMIT = 400
POLL_NS = 100


class smc_uart_thr_paths_test_seq(SmcCsrSeq):
    """Hold, misroute and park characters in UART0, and program an unlisted level."""

    def __init__(self, name: str = "smc_uart_thr_paths_test_seq") -> None:
        super().__init__(name)
        self.r = {
            "ctrl": smc_indexed_addr(
                "SMC_TOP_SMC_UART_WRAP_UART_LOG_ENGINE_WRAP_UART_LOG_ENGINE_CTRL_CTRL_BASE_ADDR",
                UART,
            ),
            **{k: _uart_reg(k.upper(), UART) for k in ("rbr", "ier", "iir", "lcr", "mcr", "lsr")},
            "ecr": _uart_reg("ECR", UART),
        }
        self.kept_byte = -1
        self.unread_iir = -1
        self.unlisted_iir = -1

    async def _setup(self, tag: str, divisor: int, fcr: int, ecr: int = 0) -> None:
        r = self.r
        await self.csr_write(f"{tag}_EN", r["ctrl"], UART_EN)
        await self.csr_write(f"{tag}_MCR", r["mcr"], MCR_LOOP)
        await self.csr_write(f"{tag}_LCR_DLAB", r["lcr"], WLS_8 | LCR_DLAB)
        await self.csr_write(f"{tag}_DLL", r["rbr"], divisor)
        await self.csr_write(f"{tag}_DLH", r["ier"], 0)
        await self.csr_write(f"{tag}_LCR", r["lcr"], WLS_8)
        await self.csr_write(f"{tag}_ECR", r["ecr"], ecr)
        await self.csr_write(f"{tag}_FCR", r["iir"], fcr | FCR_RESETS)
        await self.csr_write(f"{tag}_IER", r["ier"], IER_ERBFI)
        for _ in range(4):
            lsr = await self.csr_read(f"{tag}_LSR_CLR", r["lsr"])
            if not lsr & LSR_DR:
                break
            await self.csr_read(f"{tag}_RBR_CLR", r["rbr"])
        await self.csr_read(f"{tag}_IIR_CLR", r["iir"])

    async def _set_divisor(self, tag: str, divisor: int) -> None:
        r = self.r
        await self.csr_write(f"{tag}_LCR_DLAB", r["lcr"], WLS_8 | LCR_DLAB)
        await self.csr_write(f"{tag}_DLL", r["rbr"], divisor)
        await self.csr_write(f"{tag}_LCR", r["lcr"], WLS_8)

    async def _await_dr(self, tag: str) -> int:
        lsr = 0
        for _ in range(POLL_LIMIT):
            lsr = await self.csr_read(f"{tag}_LSR", self.r["lsr"])
            if lsr & LSR_DR:
                return lsr
            await Timer(POLL_NS, unit="ns")
        raise AssertionError(f"{tag}: no character was received (LSR=0x{lsr:08x})")

    async def _hold_leg(self) -> None:
        tag = "HOLD"
        r = self.r
        await self._setup(tag, 0, FCR_DMA_MODE)
        await self.csr_write(f"{tag}_THR1", r["rbr"], FIRST_BYTE)
        await Timer(CHAR_WAIT_NS, unit="ns")
        lsr = await self.csr_read(f"{tag}_LSR_HELD", r["lsr"])
        assert not lsr & LSR_THRE and not lsr & LSR_DR, (
            f"{tag}: with the divisor at 0, LSR=0x{lsr:08x}; the character has to wait in THR "
            f"and nothing can be received"
        )
        await self.csr_write(f"{tag}_THR2", r["rbr"], SECOND_BYTE)
        await self._set_divisor(tag, DIVISOR)
        await self._await_dr(tag)
        self.kept_byte = (await self.csr_read(f"{tag}_RBR", r["rbr"])) & 0xFF
        await Timer(CHAR_WAIT_NS, unit="ns")
        lsr = await self.csr_read(f"{tag}_LSR_AFTER", r["lsr"])
        assert self.kept_byte in (FIRST_BYTE, SECOND_BYTE) and not lsr & LSR_DR, (
            f"{tag}: received 0x{self.kept_byte:02x}, then LSR=0x{lsr:08x}; exactly one of "
            f"0x{FIRST_BYTE:02x} and 0x{SECOND_BYTE:02x} has to arrive"
        )
        assert lsr & LSR_TEMT, f"{tag}: the transmitter is not empty afterwards (0x{lsr:08x})"
        which = "the first" if self.kept_byte == FIRST_BYTE else "the second"
        cocotb.log.info(
            "CHK-UART-THR-HOLD: with the divisor at 0 a character waited in THR with THRE "
            "clear and nothing received; a second write found THR occupied, and once the "
            "divisor was set exactly one character arrived, %s (0x%02x)",
            which,
            self.kept_byte,
        )

    async def _lane_leg(self) -> None:
        tag = "LANE"
        r = self.r
        await self._setup(tag, DIVISOR, FCR_FIFO_ENABLE)
        await self.csr_write(f"{tag}_THR_LANE1", r["rbr"] + 1, LANE_BYTE, length=1)
        await Timer(CHAR_WAIT_NS, unit="ns")
        lsr = await self.csr_read(f"{tag}_LSR_NONE", r["lsr"])
        assert not lsr & LSR_DR and lsr & LSR_TEMT, (
            f"{tag}: a write enabling only the lane above THR's character left LSR=0x{lsr:08x}; "
            f"nothing may be transmitted"
        )
        await self.csr_write(f"{tag}_THR_WHOLE", r["rbr"], WHOLE_BYTE)
        await self._await_dr(tag)
        got = (await self.csr_read(f"{tag}_RBR", r["rbr"])) & 0xFF
        assert got == WHOLE_BYTE, f"{tag}: received 0x{got:02x}, not 0x{WHOLE_BYTE:02x}"
        cocotb.log.info(
            "CHK-UART-THR-LANE: a byte write to the lane above THR's character transmitted "
            "nothing, and the whole write after it arrived as 0x%02x",
            WHOLE_BYTE,
        )

    async def _unread_leg(self) -> None:
        tag = "UNREAD"
        r = self.r
        await self._setup(tag, DIVISOR, 0)
        await self.csr_write(f"{tag}_THR", r["rbr"], UNREAD_BYTE)
        await self._await_dr(tag)
        await Timer(4 * CHAR_WAIT_NS, unit="ns")
        self.unread_iir = await self.csr_read(f"{tag}_IIR", r["iir"])
        got = (await self.csr_read(f"{tag}_RBR", r["rbr"])) & 0xFF
        assert got == UNREAD_BYTE, (
            f"{tag}: a character left in RBR with the FIFOs off read back 0x{got:02x}, not "
            f"0x{UNREAD_BYTE:02x}"
        )

    async def _unlisted_leg(self) -> None:
        tag = "UNLISTED"
        r = self.r
        await self._setup(tag, DIVISOR, FCR_FIFO_ENABLE, ecr=UNLISTED_MS2B << ECR_TRIGGER_MS2B_BP)
        await self.csr_write(f"{tag}_THR", r["rbr"], UNLISTED_BYTE)
        await self._await_dr(tag)
        self.unlisted_iir = await self.csr_read(f"{tag}_IIR", r["iir"])
        got = (await self.csr_read(f"{tag}_RBR", r["rbr"])) & 0xFF
        assert got == UNLISTED_BYTE, (
            f"{tag}: with trigger code 0xC a character read back 0x{got:02x}, not "
            f"0x{UNLISTED_BYTE:02x}"
        )
        await self.csr_write(f"{tag}_ECR_OFF", r["ecr"], 0)

    async def _cut_leg(self) -> None:
        """Take the divisor to 0 while a character is on the wire, then send another."""
        tag = "CUT"
        r = self.r
        await self._setup(tag, SLOW_DIVISOR, FCR_FIFO_ENABLE)
        await self.csr_write(f"{tag}_THR", r["rbr"], CUT_BYTE)
        await Timer(CUT_AFTER_NS, unit="ns")
        await self._set_divisor(f"{tag}_STOP", 0)
        await Timer(CHAR_WAIT_NS, unit="ns")
        stalled = await self.csr_read(f"{tag}_LSR_STALLED", r["lsr"])
        await self._set_divisor(f"{tag}_RESUME", SLOW_DIVISOR)
        await Timer(8 * CUT_AFTER_NS, unit="ns")
        stray = 0
        for _ in range(4):
            lsr = await self.csr_read(f"{tag}_LSR_DRAIN", r["lsr"])
            if not lsr & LSR_DR:
                break
            await self.csr_read(f"{tag}_RBR_DRAIN", r["rbr"])
            stray += 1
        await self._set_divisor(f"{tag}_FAST", DIVISOR)
        await self.csr_write(f"{tag}_THR_NEXT", r["rbr"], WHOLE_BYTE)
        await self._await_dr(f"{tag}_NEXT")
        got = (await self.csr_read(f"{tag}_RBR_NEXT", r["rbr"])) & 0xFF
        assert got == WHOLE_BYTE, (
            f"{tag}: after the interrupted character the next one read back 0x{got:02x}, "
            f"not 0x{WHOLE_BYTE:02x}"
        )
        cocotb.log.info(
            "CHK-UART-TX-CUT: with the divisor taken to 0 part-way through a character LSR "
            "read 0x%08x; once the divisor was restored %d character(s) arrived for it, and "
            "the next character read back intact",
            stalled,
            stray,
        )

    @staticmethod
    def _iir_text(iir: int) -> str:
        if iir & IIR_INTERRUPT_PENDING:
            return "no interrupt pending"
        return f"interrupt ID 0x{(iir & IIR_INTERRUPT_ID) >> IIR_INTERRUPT_ID_BP:x}"

    async def body(self) -> None:
        cg = await self.csr_read("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL)
        await self.csr_write("UART_UNGATE", CLOCK_GATE_CONTROL, cg & ~UART_CG_EN)
        await self._hold_leg()
        await self._lane_leg()
        await self._unread_leg()
        await self._unlisted_leg()
        await self._cut_leg()
        cocotb.log.info(
            "CHK-UART-RBR-PARKED: a character left unread in RBR with the FIFOs off for four "
            "times the reception timeout read back intact (IIR showed %s), and one received "
            "with the unlisted trigger code 0xC read back intact (IIR showed %s)",
            self._iir_text(self.unread_iir),
            self._iir_text(self.unlisted_iir),
        )
        await self.csr_write("MCR_OFF", self.r["mcr"], 0)
        await self.csr_write("UART_REGATE", CLOCK_GATE_CONTROL, cg)
