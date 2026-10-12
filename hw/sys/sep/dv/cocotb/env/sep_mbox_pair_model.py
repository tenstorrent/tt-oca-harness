# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Golden model of the SEP AXI-Lite mailboxes: both ports, both FIFOs, the lines.

Written from the specification text, never from the RTL or a DUT read:

* ``hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc`` ("Paired FIFOs",
  "Interrupts", "Clock and Reset"): mailbox ``m`` holds FIFO A and FIFO B, each
  ``MAILBOX_DEPTH`` (8) entries of 64 bits. The outbound port writes A and
  reads B; the inbound port writes B and reads A. Each port has its own
  ``WIRQT``, ``RIRQT``, ``IRQS``, ``IRQEN`` and ``IRQP``; its line is the OR
  of ``IRQP = IRQS & IRQEN``. ``IRQS.wtirq`` sets while the occupancy of the
  port's write FIFO is strictly above ``WIRQT``, ``IRQS.rtirq`` while the
  occupancy of its read FIFO is strictly above ``RIRQT``, ``IRQS.eirq`` on a
  full-FIFO write or an empty-FIFO read. A cause bit latches until the
  write-one-to-clear and sets again after it while its condition holds. A
  ``WIRQT`` or ``RIRQT`` write of ``MAILBOX_DEPTH`` or more is clamped to
  ``MAILBOX_DEPTH - 1``: the register holds and reads back the clamped value
  (``axil_mailbox.adoc`` WIRQT/RIRQT: "it gets reduced to MailboxDepth - 1"). Reset
  empties both FIFOs and clears thresholds, error flags, ``IRQS`` and ``IRQEN``.
* ``hw/ip/axi_lite_mailbox_unit/doc/interface.adoc`` ("Access Results"): an
  empty read answers SLVERR with 0xFEEDDEAD on the low 32 bits and sets
  ``ERROR_FLAGS.read_error``; a full write answers SLVERR, discards the word
  and sets ``ERROR_FLAGS.write_error``; an ``ERROR_FLAGS`` read returns and
  clears the flags; a write to a read-only register answers SLVERR and changes
  nothing; a ``WRITE_DATA`` read answers OKAY with 0xFEEDC0DE on the low 32
  bits; ``CTRL`` reads 0.
* ``hw/sys/sep/doc/mailbox.adoc``: a 32-bit ``WRITE_DATA`` store pushes one
  entry whose bytes outside the strobe are zero.
* ``hw/ip/axi_lite_mailbox_unit/regs/gen/adoc/axil_mailbox.adoc``: the
  ``STATUS`` fields ``empty`` (read FIFO), ``full`` (write FIFO),
  ``write_level_above_thresh`` and ``read_level_above_thresh``; the ``CTRL``
  fields ``wflush`` (the port's write FIFO) and ``rflush`` (its read FIFO).
  Register offsets, field masks, the threshold field width and the read-only
  registers come from the generated register export (``env/sep_mbox_golden.py``,
  ``sep_reg_meta``).

The model holds stimulus only. A caller updates it with every access it
issues, and compares DUT reads against :meth:`MboxPair.status`,
:meth:`MboxPair.reg` and the line methods. The high 32 bits of an empty read
or of a ``WRITE_DATA`` read are not stated, so the model returns None for them.
A 32-bit push at one half makes one entry whose other half is 0.

Usage::

    mbx = MboxSystem()
    resp = mbx[3].push("in", 0x1234)        # an inbound push to mailbox 3
    exp_vec = mbx.in_lines()                # expected probe bits [7:0]
    exp_count = mbx.out_count()             # expected popcount of the SMC port
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from sep_mbox_golden import (
    CTRL_WFLUSH,
    ERR_READ,
    ERR_WRITE,
    IRQ_EIRQ,
    IRQ_RTIRQ,
    IRQ_WTIRQ,
    MAILBOX_DEPTH,
    READ_EMPTY_SENTINEL,
    ST_EMPTY,
    ST_FULL,
    ST_RLVL_ABOVE,
    ST_WLVL_ABOVE,
    WRITE_DATA_RD_SENTINEL,
)
from sep_reg_meta import AXIL_MAILBOX_OUTBOUND_0 as _MBX
from sep_reg_meta import indexed_block_count, register_fields

# Mailbox count from the RDL mailbox array (generated register header).
NUM_MAILBOXES = indexed_block_count("AXIL_MAILBOX_OUTBOUND_MAILBOX")
PORTS = ("out", "in")
WRITE_FIFO = {"out": "A", "in": "B"}
READ_FIFO = {"out": "B", "in": "A"}
IRQ_ALL = IRQ_WTIRQ | IRQ_RTIRQ | IRQ_EIRQ
CTRL_RFLUSH = _MBX.field_mask("CTRL", "rflush")
THRESH_MASK = _MBX.field_mask("WIRQT", "wirqt")
assert THRESH_MASK == _MBX.field_mask("RIRQT", "rirqt")
MASK32 = 0xFFFF_FFFF
MASK64 = (1 << 64) - 1
OKAY = "OKAY"
SLVERR = "SLVERR"
MBX_REGS = (
    "WRITE_DATA",
    "READ_DATA",
    "STATUS",
    "ERROR_FLAGS",
    "WIRQT",
    "RIRQT",
    "IRQS",
    "IRQEN",
    "IRQP",
    "CTRL",
)
# Registers whose every RDL field is read-only.
RO_REGS = tuple(
    r for r in MBX_REGS if all(f.access == "read-only" for f in register_fields(_MBX.addr(r))[1])
)


def clamp(thresh: int) -> int:
    """The effective threshold: a value of MAILBOX_DEPTH or more acts as DEPTH - 1."""
    return min(thresh & THRESH_MASK, MAILBOX_DEPTH - 1)


@dataclass
class Entry:
    """One FIFO entry: the low and high 32-bit halves."""

    lo: int | None
    hi: int | None

    @property
    def full(self) -> bool:
        return self.lo is not None and self.hi is not None

    def word(self) -> int | None:
        if self.lo is None or self.hi is None:
            return None
        return (self.hi << 32) | self.lo


@dataclass
class PortRegs:
    wirqt: int = 0
    rirqt: int = 0
    irqen: int = 0
    irqs: int = 0
    err: int = 0


@dataclass
class MboxPair:
    """Mailbox ``m``: FIFO A, FIFO B and the registers of both ports."""

    m: int
    fifo: dict = field(default_factory=lambda: {"A": deque(), "B": deque()})
    regs: dict = field(default_factory=lambda: {p: PortRegs() for p in PORTS})

    # ---- state ----
    def reset(self) -> None:
        """SEP reset: both FIFOs empty; every port register 0."""
        for q in self.fifo.values():
            q.clear()
        for p in PORTS:
            self.regs[p] = PortRegs()

    def occ(self, fifo: str) -> int:
        return len(self.fifo[fifo])

    def write_occ(self, port: str) -> int:
        return self.occ(WRITE_FIFO[port])

    def read_occ(self, port: str) -> int:
        return self.occ(READ_FIFO[port])

    def _cond(self, port: str) -> int:
        r = self.regs[port]
        c = 0
        if self.write_occ(port) > clamp(r.wirqt):
            c |= IRQ_WTIRQ
        if self.read_occ(port) > clamp(r.rirqt):
            c |= IRQ_RTIRQ
        return c

    def _settle(self) -> None:
        for p in PORTS:
            self.regs[p].irqs |= self._cond(p)

    # ---- accesses ----
    def push(self, port: str, data: int, *, half: int | None = None) -> str:
        """``WRITE_DATA`` write on ``port``. ``half`` None is a 64-bit full-strobe
        store; 0 or 1 is a 32-bit store at that half. Returns the response."""
        q = self.fifo[WRITE_FIFO[port]]
        if len(q) >= MAILBOX_DEPTH:
            self.regs[port].err |= ERR_WRITE
            self.regs[port].irqs |= IRQ_EIRQ
            self._settle()
            return SLVERR
        if half is None:
            q.append(Entry(data & MASK32, (data >> 32) & MASK32))
        elif half == 0:
            q.append(Entry(data & MASK32, 0))
        else:
            q.append(Entry(0, data & MASK32))
        self._settle()
        return OKAY

    def pop(self, port: str, *, half: int | None = None) -> tuple[str, int | None, Entry | None]:
        """``READ_DATA`` read on ``port``. Returns (response, expected data, entry).

        The expected data is the 64-bit word for a 64-bit read of a full entry,
        the 32-bit half for a 32-bit read, and None where the value is not
        stated. An empty read returns the low-32 sentinel only.
        """
        q = self.fifo[READ_FIFO[port]]
        if not q:
            self.regs[port].err |= ERR_READ
            self.regs[port].irqs |= IRQ_EIRQ
            self._settle()
            return SLVERR, READ_EMPTY_SENTINEL, None
        e = q.popleft()
        self._settle()
        if half is None:
            return OKAY, e.word(), e
        return OKAY, (e.lo if half == 0 else e.hi), e

    def flush(self, port: str, bits: int) -> None:
        """``CTRL`` write: ``wflush`` empties the port's write FIFO, ``rflush`` its read FIFO."""
        if bits & CTRL_WFLUSH:
            self.fifo[WRITE_FIFO[port]].clear()
        if bits & CTRL_RFLUSH:
            self.fifo[READ_FIFO[port]].clear()
        self._settle()

    def write_reg(self, port: str, name: str, value: int) -> str:
        """Register write other than ``WRITE_DATA``. Returns the response."""
        r = self.regs[port]
        if name == "WIRQT":
            r.wirqt = clamp(value)
        elif name == "RIRQT":
            r.rirqt = clamp(value)
        elif name == "IRQEN":
            r.irqen = value & IRQ_ALL
        elif name == "IRQS":
            r.irqs &= ~(value & IRQ_ALL)
        elif name == "CTRL":
            self.flush(port, value)
            return OKAY
        elif name in RO_REGS:
            return SLVERR
        else:
            raise KeyError(f"no mailbox register {name}")
        self._settle()
        return OKAY

    def read_reg(self, port: str, name: str) -> tuple[str, int | None]:
        """Register read other than ``READ_DATA``. ``ERROR_FLAGS`` clears on read."""
        r = self.regs[port]
        if name == "STATUS":
            return OKAY, self.status(port)
        if name == "ERROR_FLAGS":
            v, r.err = r.err, 0
            return OKAY, v
        if name == "WRITE_DATA":
            return OKAY, WRITE_DATA_RD_SENTINEL
        if name == "CTRL":
            return OKAY, 0
        return OKAY, self.reg(port, name)

    # ---- expected values ----
    def status(self, port: str) -> int:
        r = self.regs[port]
        v = 0
        if self.read_occ(port) == 0:
            v |= ST_EMPTY
        if self.write_occ(port) >= MAILBOX_DEPTH:
            v |= ST_FULL
        if self.write_occ(port) > clamp(r.wirqt):
            v |= ST_WLVL_ABOVE
        if self.read_occ(port) > clamp(r.rirqt):
            v |= ST_RLVL_ABOVE
        return v

    def reg(self, port: str, name: str) -> int:
        """The expected field value of WIRQT, RIRQT, IRQEN, IRQS or IRQP."""
        r = self.regs[port]
        return {
            "WIRQT": r.wirqt,
            "RIRQT": r.rirqt,
            "IRQEN": r.irqen,
            "IRQS": r.irqs,
            "IRQP": r.irqs & r.irqen,
        }[name]

    def error_flags(self, port: str) -> int:
        """The flags an ``ERROR_FLAGS`` read would return, without clearing them."""
        return self.regs[port].err

    def line(self, port: str) -> int:
        """The level of the port's interrupt line."""
        return int(bool(self.reg(port, "IRQP")))


class MboxSystem:
    """The eight mailboxes. Index with the mailbox number."""

    def __init__(self, n: int = NUM_MAILBOXES) -> None:
        self.pairs = [MboxPair(m) for m in range(n)]

    def __getitem__(self, m: int) -> MboxPair:
        return self.pairs[m]

    def reset(self) -> None:
        for p in self.pairs:
            p.reset()

    def in_lines(self) -> int:
        """Expected ``sep_internal_interrupts_probe_o[7:0]``: bit m is the inbound line of m."""
        return sum(p.line("in") << p.m for p in self.pairs)

    def out_lines(self) -> list[int]:
        """The outbound line of each mailbox. No port-bit map is stated, so a
        caller grades the SMC port as a set (``out_count``)."""
        return [p.line("out") for p in self.pairs]

    def out_count(self) -> int:
        """Expected number of high bits of ``smc_mailbox_interrupt_o``."""
        return sum(self.out_lines())


def popcount(v: int) -> int:
    return bin(v).count("1")


def _selftest() -> None:
    s = MboxSystem()
    p = s[2]
    # Threshold 0 detects one queued word; IRQEN gates the line.
    p.write_reg("out", "WIRQT", 0)
    assert p.push("out", 0x1111_2222_3333_4444) == OKAY
    assert p.status("out") & ST_WLVL_ABOVE and p.status("out") & ST_EMPTY  # out reads B
    assert p.status("in") & ST_EMPTY == 0  # inbound reads FIFO A
    assert p.reg("out", "IRQS") == IRQ_WTIRQ and p.line("out") == 0
    p.write_reg("out", "IRQEN", IRQ_WTIRQ)
    assert p.line("out") == 1 and s.out_count() == 1 and s.in_lines() == 0
    # The latch holds below the threshold until the acknowledge.
    resp, data, _ = p.pop("in")
    assert resp == OKAY and data == 0x1111_2222_3333_4444
    assert p.occ("A") == 0 and p.reg("out", "IRQS") == IRQ_WTIRQ
    p.write_reg("out", "IRQS", IRQ_WTIRQ)
    assert p.reg("out", "IRQS") == 0 and p.line("out") == 0
    # Acknowledge while still above the threshold re-reads 1.
    p.push("out", 1)
    p.push("out", 2)
    p.write_reg("out", "IRQS", IRQ_WTIRQ)
    assert p.reg("out", "IRQS") == IRQ_WTIRQ
    # Clamp: 255 acts as 7; fires at 8 and not at 7.
    q = s[5]
    q.write_reg("in", "WIRQT", 255)
    assert q.reg("in", "WIRQT") == MAILBOX_DEPTH - 1
    for i in range(7):
        q.push("in", i + 1)
    assert not q.status("in") & ST_WLVL_ABOVE
    q.push("in", 8)
    assert q.status("in") & ST_WLVL_ABOVE and q.status("in") & ST_FULL
    # Full write and empty read.
    assert q.push("in", 9) == SLVERR and q.occ("B") == 8
    assert q.read_reg("in", "ERROR_FLAGS") == (OKAY, ERR_WRITE)
    assert q.read_reg("in", "ERROR_FLAGS") == (OKAY, 0)
    assert q.reg("in", "IRQS") & IRQ_EIRQ
    assert q.pop("in")[0] == SLVERR  # inbound reads FIFO A, which is empty
    assert q.read_reg("in", "ERROR_FLAGS")[1] == ERR_READ
    # Read-only write changes nothing; flush empties exactly one FIFO.
    before = q.status("out")
    assert q.write_reg("out", "STATUS", 0xF) == SLVERR and q.status("out") == before
    q.push("out", 0xAB)
    q.write_reg("in", "CTRL", CTRL_WFLUSH)  # inbound wflush discards FIFO B
    assert q.occ("B") == 0 and q.occ("A") == 1
    # A 32-bit push zeroes the other half.
    r = s[7]
    r.push("out", 0xCAFE, half=1)
    resp, data, e = r.pop("in")
    assert resp == OKAY and data == 0xCAFE << 32 and e is not None and e.lo == 0
    assert RO_REGS == ("READ_DATA", "STATUS", "ERROR_FLAGS", "IRQP")
    # Reset.
    s.reset()
    assert all(x.status(pt) == ST_EMPTY for x in s.pairs for pt in PORTS)
    assert s.in_lines() == 0 and s.out_count() == 0


if __name__ == "__main__":
    _selftest()
    print("sep_mbox_pair_model self-test PASS")
