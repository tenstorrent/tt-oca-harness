# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Mailbox access errors on both ports of the eight SEP mailboxes.

Contract (``hw/ip/axi_lite_mailbox_unit/doc/interface.adoc``, "Access
Results"; ``hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc``,
"Interrupts"; ``hw/ip/axi_lite_mailbox_unit/doc/memmap.adoc``, "Per-Mailbox
Register Map"; ``hw/sys/sep/regs/gen/adoc/memory_map.adoc``, SEP AXI-Lite
Mailbox Wrapper row; ``hw/ip/axi_lite_mailbox_unit/regs/gen/adoc/axil_mailbox.adoc``):

* K1: a ``READ_DATA`` read of an empty FIFO answers SLVERR with 0xFEEDDEAD on
  the low 32 bits and sets ``ERROR_FLAGS.read_error`` and ``IRQS.eirq``.
* K2: a ``WRITE_DATA`` write to a full FIFO answers SLVERR, discards the word
  and sets ``ERROR_FLAGS.write_error`` and ``IRQS.eirq``.
* K3: a write to ``READ_DATA``, ``STATUS``, ``ERROR_FLAGS`` or ``IRQP``
  answers SLVERR and changes nothing.
* K4 and K5: a 32-bit access inside an aperture from offset 0x50 up, or past
  the wrapper extent (0x10A0_7850 to 0x10A0_7FFF), answers SLVERR with data
  0x0 and changes no live register and no FIFO.
* K6 (control): the same hole access answers SLVERR with the window open and
  DECERR with the window closed.
* An ``ERROR_FLAGS`` read returns and clears the flags; ``IRQS.eirq`` stays
  set until its write-one-to-clear; two errors before one read show both
  flags; the error cause drives the line of its port only with
  ``IRQEN.eirq``, and the ``ERROR_FLAGS`` read does not drop the line.
* A ``WRITE_DATA`` read answers OKAY with 0xFEEDC0DE on the low 32 bits and
  moves no FIFO. A 32-bit read returns the lane that address bit 2 selects,
  so the leg reads both halves in a drawn order: the low half is graded and
  the high half is logged.

Expected values come from ``env/sep_mbox_pair_model.MboxSystem``, which holds
the stimulus only. The outbound port is driven by the CPU-LSU master and the
inbound port by the external SMN master through two inbound filter entries
over each whole 4 KiB pair (``allow_ns`` 0 and 1, ``src_id`` 0). The K4, K5,
K6 and ``WRITE_DATA`` read accesses go on the external master to either
aperture. The inbound line of mailbox ``m`` is bit ``m`` of
``sep_internal_interrupts_probe_o``; the outbound lines are graded as the
count of high bits of ``smc_mailbox_interrupt_o``.

Checks: CHK-ERR-RD, CHK-ERR-WR, CHK-RO, CHK-HOLE, CHK-EXTENT,
CHK-FLAGS-CLEAR, CHK-FLAGS-BOTH, CHK-ERR-LINE, CHK-WO-READ, CHK-TWIN.
Controls: CTL-RESP (K6), CTRL-MISSING when a K4/K5 live value reads 0.
Log only: the high 32 bits of the empty-read and ``WRITE_DATA`` read data,
and ``ERROR_FLAGS``/``IRQS`` after a hole access (``OBS-HOLE-FLAGS``).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``, RAND-REP:
every draw comes from ``SepSeededRng`` and the run seed. The base set (K1 to
K3 on both ports, K4 at 0x50, an interior word and 0x7F8 on both ports, K5
read and write, K6) runs on every seed; the seed draws the order, the extra
injections, mailboxes, offsets, halves, words and live values.
"""

from __future__ import annotations

from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, ReadOnly, RisingEdge
from env.sep_axi_agent import SepAxiOp
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_filter_model import FilterEntry
from env.sep_mbox_golden import (
    ERR_READ,
    ERR_WRITE,
    IRQ_EIRQ,
    IRQ_RTIRQ,
    IRQ_WTIRQ,
    MAILBOX_DEPTH,
    READ_EMPTY_SENTINEL,
    ST_EMPTY,
    WRITE_DATA_RD_SENTINEL,
)
from env.sep_mbox_pair_model import IRQ_ALL, MboxSystem, popcount
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AXIL_MAILBOX_OUTBOUND_0 as MBX_REGS
from sep_reg_meta import INBOUND_FILTER_CTRL_0, sep_addr_define
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_mailbox_iface_seq import SepMbox
from seq_lib.sep_mbox_port_ops import (
    RESP_DECERR,
    RESP_OKAY,
    RESP_SLVERR,
    SIZE_4B,
    port_base,
    ports,
    resp_name,
)

TEST = "sep_mailbox_access_error_inject_test"

M32 = 0xFFFF_FFFF
M64 = (1 << 64) - 1
PEER = {"out": "in", "in": "out"}
FIELD = {
    r: MBX_REGS.mask32(r) for r in ("STATUS", "IRQS", "IRQEN", "WIRQT", "RIRQT", "ERROR_FLAGS")
}
# Aperture, pair and wrapper-extent edges from the generated SEP address map.
# K4/K5 offsets step in 8-byte words, so the last word of a range starts 8 bytes
# before its end.
_MBX = "SEP_TOP_AXIL_MAILBOX"
_OUT0 = sep_addr_define(f"{_MBX}_OUTBOUND_MAILBOX_0_BASE_ADDR")
APERTURE_BYTES = sep_addr_define(f"{_MBX}_INBOUND_MAILBOX_0_BASE_ADDR") - _OUT0
HOLE_FIRST = sep_addr_define(f"{_MBX}_OUTBOUND_MAILBOX_0_SIZE")
HOLE_LAST = APERTURE_BYTES - 8
PAIR_BYTES = sep_addr_define(f"{_MBX}_OUTBOUND_MAILBOX_1_BASE_ADDR") - _OUT0
EXTENT_FIRST = sep_addr_define(f"{_MBX}_BASE_ADDR") + sep_addr_define(f"{_MBX}_SIZE")
EXTENT_LAST = sep_addr_define(f"{_MBX}_INBOUND_MAILBOX_7_BASE_ADDR") + APERTURE_BYTES - 8
RO_TARGETS = ("READ_DATA", "STATUS", "ERROR_FLAGS", "IRQP")
QUIET_CLKS = 32
# IRQS threshold causes (wtirq, rtirq) and FILTER_CONFIG.entry_enabled, from the RDL.
IRQS_THR = IRQ_WTIRQ | IRQ_RTIRQ
FILT_ENTRY_ENABLED = INBOUND_FILTER_CTRL_0.field_mask("FILTER_CONFIG", "entry_enabled")


class Inj:
    """One injection of the list, every field drawn before the stimulus."""

    def __init__(self, kind: str, m: int, port: str, **kw) -> None:
        self.kind = kind
        self.m = m
        self.port = port
        self.op = kw.get("op", "rd")
        self.off = kw.get("off", 0)
        self.half = kw.get("half", 0)
        self.reg = kw.get("reg", "")
        self.value = kw.get("value", 0)
        self.prot1 = kw.get("prot1", 0)
        self.live: dict = kw.get("live", {})
        self.pre_words: tuple = kw.get("pre_words", ())
        self.word = kw.get("word", 0)
        self.extra = kw.get("extra", False)

    def addr(self) -> int:
        if self.kind == "K5":
            return self.off + 4 * self.half
        return port_base(self.m, self.port) + self.off + 4 * self.half

    def line(self) -> str:
        s = f"kind={self.kind} mbox={self.m} port={self.port} extra={int(self.extra)}"
        if self.kind in ("K4", "K5", "K6"):
            s += f" op={self.op} addr=0x{self.addr():08x} half={self.half} prot1={self.prot1}"
            if self.op == "wr":
                s += f" word=0x{self.word:08x}"
        if self.kind == "K3":
            s += f" reg={self.reg} value=0x{self.value:08x}"
        if self.live:
            s += " live=" + ",".join(f"{p}.{k}=0x{v:x}" for (p, k), v in sorted(self.live.items()))
            s += " pre_words=" + ",".join(f"0x{w:016x}" for w in self.pre_words)
        return s


@pyuvm.test()
class sep_mailbox_access_error_inject_test(sep_base_test):
    """Empty read, full write, read-only write, hole and extent, flags, WRITE_DATA read, error line."""

    required_evidence = (
        "CHK-ERR-RD",
        "CHK-ERR-WR",
        "CHK-RO",
        "CHK-HOLE",
        "CHK-EXTENT",
        "CHK-FLAGS-CLEAR",
        "CHK-FLAGS-BOTH",
        "CHK-ERR-LINE",
        "CHK-WO-READ",
        "CHK-TWIN",
    )

    # ------------------------------------------------------------------ log
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.seed, line)
        self.n_checks += 1

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctrl_missing(self, line: str) -> None:
        msg = f"CTRL-MISSING seed={self.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    # --------------------------------------------------------------- access
    async def _setup_push(self, m: int, port: str, data: int) -> None:
        resp = await self.ops[m].push(port, data)
        exp = self.mbx[m].push(port, data)
        if resp != RESP_OKAY or exp != "OKAY":
            raise AssertionError(
                f"MBX-SETUP FAIL: mbox={m} {port} push resp={resp_name(resp)} model={exp}"
            )

    async def _rd(self, m: int, port: str, reg: str) -> int:
        """Register read; the model applies the read (ERROR_FLAGS clears)."""
        data = await self.ops[m].rd_ok(port, reg)
        self.mbx[m].read_reg(port, reg)
        return int(data) & FIELD.get(reg, M32)

    async def _wr(self, m: int, port: str, reg: str, value: int) -> None:
        await self.ops[m].wr_ok(port, reg, value)
        self.mbx[m].write_reg(port, reg, value)

    async def _pop_cmp(self, m: int, port: str) -> tuple[int, int, int]:
        """64-bit pop; returns (resp, got, exp)."""
        resp, data = await self.ops[m].pop(port)
        _, exp, _ = self.mbx[m].pop(port)
        return resp, data & M64, exp if exp is not None else -1

    async def _clear_port(self, m: int, port: str) -> tuple[int, int]:
        """Clean-up: read ERROR_FLAGS (clears) and write IRQS 0x7. Returns the read values."""
        flags = await self._rd(m, port, "ERROR_FLAGS")
        irqs = await self._rd(m, port, "IRQS")
        await self._wr(m, port, "IRQS", IRQ_ALL)
        return flags, irqs

    async def _ext(
        self, inj: Inj, *, op: str | None = None, addr: int | None = None
    ) -> tuple[int, int]:
        """One 32-bit access on the external master."""
        op = op or inj.op
        a = inj.addr() if addr is None else addr
        o = self.ops[inj.m]
        if op == "rd":
            return await o.raw("in", SepAxiOp.READ, a, size=SIZE_4B, prot1=inj.prot1)
        return await o.raw("in", SepAxiOp.WRITE, a, wdata=inj.word, size=SIZE_4B, prot1=inj.prot1)

    async def _sample_lines(self) -> tuple[int, int]:
        """(probe [7:0], smc) on the last clock of a quiet window with no mailbox access."""
        dut: Any = cocotb.top
        await ClockCycles(dut.clk_i, QUIET_CLKS)
        await RisingEdge(dut.clk_i)
        await ReadOnly()
        probe = self.rd(dut.sep_internal_interrupts_probe_o, 0xFF) & 0xFF
        smc = self.rd(dut.smc_mailbox_interrupt_o) & 0xFF
        await RisingEdge(dut.clk_i)
        return probe, smc

    # ------------------------------------------------------------------ draws
    def _draw_live(self) -> tuple[dict, tuple]:
        live = {}
        for p in ("out", "in"):
            w = self.rng.randrange(1, 7)
            r = self.rng.choice([v for v in range(1, 7) if v != w])
            live[(p, "WIRQT")] = w
            live[(p, "RIRQT")] = r
            live[(p, "IRQEN")] = self.rng.randrange(1, 8)
        words = (self._word64(), self._word64())
        return live, words

    def _word64(self) -> int:
        while True:
            v = self.rng.getrandbits(64)
            if v and v not in self.used:
                self.used.add(v)
                return v

    def _k4_word(self, live: dict) -> int:
        bad8 = {v for (p, k), v in live.items() if k in ("WIRQT", "RIRQT")}
        bad3 = {v for (p, k), v in live.items() if k == "IRQEN"}
        while True:
            w = self.rng.getrandbits(32)
            if w and (w & 0xFF) not in bad8 and (w & 0x7) not in bad3:
                return w

    def _hole_off(self) -> int:
        return 8 * self.rng.randrange(HOLE_FIRST // 8, HOLE_LAST // 8 + 1)

    def _mk(self, kind: str, *, port: str | None = None, extra: bool = False, **kw) -> Inj:
        r = self.rng
        if kind in ("K5", "K6"):
            port = "in"
        if port is None:
            port = r.choice(["out", "in"])
        if kind == "K5":
            m = 7
        elif kind in ("K1", "K2", "K3") and port == "out":
            m = r.randrange(1, 8)
        else:
            m = r.randrange(0, 8)
        inj = Inj(kind, m, port, extra=extra, prot1=r.randrange(0, 2))
        if kind == "K3":
            inj.reg = r.choice(list(RO_TARGETS))
            inj.value = r.getrandbits(32) | 1
        if kind in ("K4", "K5", "K6"):
            inj.op = kw.get("op") or r.choice(["rd", "wr"])
            inj.half = r.randrange(0, 2)
            if kind == "K5":
                inj.off = 8 * r.randrange(EXTENT_FIRST // 8, EXTENT_LAST // 8 + 1)
            else:
                inj.off = kw.get("off", self._hole_off())
        if kind in ("K4", "K5"):
            inj.live, inj.pre_words = self._draw_live()
            inj.word = self._k4_word(inj.live)
        elif kind == "K6":
            inj.word = r.getrandbits(32) | 1
        return inj

    def _draw(self) -> None:
        r = self.rng
        base = []
        for k in ("K1", "K2", "K3"):
            for p in ("out", "in"):
                base.append(self._mk(k, port=p))
        interior = 8 * r.randrange(HOLE_FIRST // 8 + 1, HOLE_LAST // 8)
        for off in (HOLE_FIRST, interior, HOLE_LAST):
            for p in ("out", "in"):
                base.append(self._mk("K4", port=p, off=off))
        base.append(self._mk("K5", op="rd"))
        base.append(self._mk("K5", op="wr"))
        base.append(self._mk("K6"))
        n_extra = r.randrange(1, 5)
        for _ in range(n_extra):
            base.append(self._mk(r.choice(["K1", "K2", "K3", "K4", "K5", "K6"]), extra=True))
        r.shuffle(base)
        self.injections = base
        for i, inj in enumerate(base):
            self.logger.info("DRAW inj%d %s", i, inj.line())
        # Two-flag corner: any port but outbound mailbox 0.
        while True:
            m, p = r.randrange(0, 8), r.choice(["out", "in"])
            if (m, p) != (0, "out"):
                break
        self.both_port = (m, p)
        self.both_words = [self._word64() for _ in range(MAILBOX_DEPTH + 1)]
        self.line_mbox = r.randrange(0, 8)
        self.wo_first_half = {(m, p): r.randrange(0, 2) for m in range(8) for p in ("out", "in")}
        self.wo_words = {k: self._word64() for k in self.wo_first_half}
        self.logger.info(
            "DRAW n_extra=%d interior=0x%x both_mbox=%d both_port=%s line_mbox=%d",
            n_extra,
            interior,
            m,
            p,
            self.line_mbox,
        )
        self.logger.info(
            "DRAW wo_first_half=%s",
            ",".join(f"{mm}{pp}:{h}" for (mm, pp), h in sorted(self.wo_first_half.items())),
        )

    # ------------------------------------------------------------------ legs
    async def _flags_pre(self, chk: str, m: int, port: str) -> None:
        flags = await self._rd(m, port, "ERROR_FLAGS")
        irqs = await self._rd(m, port, "IRQS")
        if flags != 0 or irqs & IRQ_EIRQ:
            self._fail(
                chk,
                f"mbox={m} port={port} pre error_flags=0x{flags:x} irqs=0x{irqs:x} exp 0x0 and bit2=0",
            )

    async def _k1(self, inj: Inj) -> None:
        m, p = inj.m, inj.port
        mb = self.mbx[m]
        assert mb.read_occ(p) == 0, "test error: K1 needs an empty read FIFO"
        await self._flags_pre("CHK-FLAGS-CLEAR", m, p)
        resp, data = await self.ops[m].pop(p)
        mresp, _, _ = mb.pop(p)
        exp_irqs = mb.reg(p, "IRQS")
        first = await self._rd(m, p, "ERROR_FLAGS")
        irqs = await self._rd(m, p, "IRQS")
        lo, hi = data & M32, (data >> 32) & M32
        txt = (
            f"mbox={m} port={p} resp={resp_name(resp)} data=0x{lo:08X} data_hi=0x{hi:08x} "
            f"read_err={first & ERR_READ and 1} irqs=0x{irqs:x} exp_irqs=0x{exp_irqs:x}"
        )
        if (
            resp != RESP_SLVERR
            or mresp != "SLVERR"
            or lo != READ_EMPTY_SENTINEL
            or first != ERR_READ
            or irqs != exp_irqs
        ):
            self._fail("CHK-ERR-RD", txt)
        self._pass("CHK-ERR-RD", txt)
        second = await self._rd(m, p, "ERROR_FLAGS")
        irqs2 = await self._rd(m, p, "IRQS")
        await self._wr(m, p, "IRQS", IRQ_EIRQ)
        irqs3 = await self._rd(m, p, "IRQS")
        self._flags_clear("K1", m, p, first, ERR_READ, second, irqs2, irqs3)
        # Twin: a READ_DATA read with one entry present answers OKAY.
        w = self._word64()
        await self._setup_push(m, PEER[p], w)
        tresp, got, exp = await self._pop_cmp(m, p)
        self._twin(
            "K1",
            m,
            p,
            "READ_DATA",
            tresp,
            f"data=0x{got:016x} exp=0x{exp:016x}",
            got == exp,
        )

    def _flags_clear(self, kind, m, p, first, exp_first, second, irqs2, irqs3) -> None:
        txt = (
            f"kind={kind} mbox={m} port={p} first=0x{first:x} exp_first=0x{exp_first:x} second=0x{second:x} "
            f"irqs_bit2={(irqs2 >> 2) & 1} after_w1c={(irqs3 >> 2) & 1}"
        )
        if first != exp_first or second != 0 or not irqs2 & IRQ_EIRQ or irqs3 & IRQ_EIRQ:
            self._fail("CHK-FLAGS-CLEAR", txt)
        self._pass("CHK-FLAGS-CLEAR", txt)

    def _twin(self, kind, m, p, twin, resp, extra="", ok=True) -> None:
        txt = f"kind={kind} mbox={m} port={p} twin={twin} twin_resp={resp_name(resp)} {extra}".rstrip()
        if resp != RESP_OKAY or not ok:
            self._fail("CHK-TWIN", txt)
        self._pass("CHK-TWIN", txt)

    async def _k2(self, inj: Inj) -> None:
        m, p = inj.m, inj.port
        mb = self.mbx[m]
        assert mb.write_occ(p) == 0, "test error: K2 needs an empty write FIFO"
        await self._flags_pre("CHK-FLAGS-CLEAR", m, p)
        words = [self._word64() for _ in range(MAILBOX_DEPTH)]
        for w in words:
            await self._setup_push(m, p, w)
        ninth = self._word64()
        resp = await self.ops[m].push(p, ninth)
        mresp = mb.push(p, ninth)
        first = await self._rd(m, p, "ERROR_FLAGS")
        second = await self._rd(m, p, "ERROR_FLAGS")
        irqs2 = await self._rd(m, p, "IRQS")
        await self._wr(m, p, "IRQS", IRQ_EIRQ)
        irqs3 = await self._rd(m, p, "IRQS")
        pops = []
        for _ in range(MAILBOX_DEPTH):
            pops.append(await self._pop_cmp(m, PEER[p]))
        st = await self._rd(m, PEER[p], "STATUS")
        match = all(r == RESP_OKAY and g == w for (r, g, _), w in zip(pops, words))
        empty = int(bool(st & ST_EMPTY))
        txt = (
            f"mbox={m} port={p} resp={resp_name(resp)} occ={MAILBOX_DEPTH} next_pops_match={int(match)} "
            f"empty_after={empty} write_err={int(bool(first & ERR_WRITE))} ninth=0x{ninth:016x}"
        )
        if resp != RESP_SLVERR or mresp != "SLVERR" or not match or not empty or first != ERR_WRITE:
            self._fail("CHK-ERR-WR", txt)
        self._pass("CHK-ERR-WR", txt)
        self._flags_clear("K2", m, p, first, ERR_WRITE, second, irqs2, irqs3)
        w = self._word64()
        tresp = await self.ops[m].push(p, w)
        mb.push(p, w)
        _, got, exp = await self._pop_cmp(m, PEER[p])
        self._twin(
            "K2",
            m,
            p,
            "WRITE_DATA",
            tresp,
            f"drain=0x{got:016x} exp=0x{exp:016x}",
            got == exp,
        )

    async def _k3(self, inj: Inj) -> None:
        m, p = inj.m, inj.port
        mb = self.mbx[m]
        assert mb.read_occ(p) == 0, "test error: K3 arms with an empty read FIFO"
        await self._flags_pre("CHK-RO", m, p)
        aresp, _ = await self.ops[m].pop(p)
        mb.pop(p)
        if aresp != RESP_SLVERR:
            self._ctrl_missing(f"CHK-RO arm mbox={m} port={p} empty read resp={resp_name(aresp)}")
        w = self._word64()
        await self._setup_push(m, PEER[p], w)
        armed_irqs = await self._rd(m, p, "IRQS")
        st0 = await self._rd(m, p, "STATUS")
        resp = await self.ops[m].wr(p, inj.reg, inj.value)
        mresp = mb.write_reg(p, inj.reg, inj.value)
        flags = await self._rd(m, p, "ERROR_FLAGS")
        irqs = await self._rd(m, p, "IRQS")
        st1 = await self._rd(m, p, "STATUS")
        presp, got, exp = await self._pop_cmp(m, p)
        st2 = await self._rd(m, p, "STATUS")
        exp_armed = ERR_READ
        txt = (
            f"mbox={m} port={p} reg={inj.reg} value=0x{inj.value:08x} resp={resp_name(resp)} "
            f"armed_flags=0x{exp_armed:x} flags_after=0x{flags:x} armed_irqs=0x{armed_irqs:x} "
            f"irqs_after=0x{irqs:x} occ_before={0 if st0 & ST_EMPTY else 1} occ_after={0 if st1 & ST_EMPTY else 1} "
            f"status_before=0x{st0:x} status_after=0x{st1:x} pop=0x{got:016x} exp=0x{exp:016x} "
            f"empty_after_pop={int(bool(st2 & ST_EMPTY))}"
        )
        ok = (
            resp == RESP_SLVERR
            and mresp == "SLVERR"
            and flags == exp_armed
            and irqs == armed_irqs
            and armed_irqs & IRQ_EIRQ
            and st1 == st0
            and not st0 & ST_EMPTY
            and presp == RESP_OKAY
            and got == exp
            and st2 & ST_EMPTY
        )
        if not ok:
            self._fail("CHK-RO", txt)
        self._pass("CHK-RO", txt)
        await self._wr(m, p, "IRQS", IRQ_EIRQ)
        irqs3 = await self._rd(m, p, "IRQS")
        if irqs3 & IRQ_EIRQ:
            self._fail("CHK-RO", f"mbox={m} port={p} irqs bit2 after w1c=1")
        cur = mb.reg(p, "WIRQT")
        tresp = await self.ops[m].wr(p, "WIRQT", cur)
        mb.write_reg(p, "WIRQT", cur)
        self._twin("K3", m, p, "WIRQT", tresp, f"value=0x{cur:x}")

    async def _live_prestate(self, inj: Inj) -> dict:
        """Step 3: live values, one word per FIFO, the snapshot."""
        m = inj.m
        mb = self.mbx[m]
        for (p, reg), v in sorted(inj.live.items()):
            await self._wr(m, p, reg, v)
        snap = {}
        for (p, reg), v in sorted(inj.live.items()):
            got = await self._rd(m, p, reg)
            if got == 0:
                self._ctrl_missing(f"{inj.kind} mbox={m} {p}.{reg} reads 0 (wrote 0x{v:x})")
            snap[(p, reg)] = got
        assert mb.occ("A") == 0 and mb.occ("B") == 0, (
            "test error: K4/K5 pre-state needs empty FIFOs"
        )
        await self._setup_push(m, "out", inj.pre_words[0])
        await self._setup_push(m, "in", inj.pre_words[1])
        for p in ("out", "in"):
            snap[(p, "STATUS")] = await self._rd(m, p, "STATUS")
            snap[(p, "IRQS")] = (await self._rd(m, p, "IRQS")) & IRQS_THR
        return snap

    async def _k45(self, inj: Inj) -> None:
        m = inj.m
        mb = self.mbx[m]
        chk = "CHK-HOLE" if inj.kind == "K4" else "CHK-EXTENT"
        snap = await self._live_prestate(inj)
        # The snapshot must equal the model, so "unchanged" is also "as written".
        for (p, reg), v in snap.items():
            exp = mb.reg(p, reg) if reg not in ("STATUS", "IRQS") else None
            if reg == "STATUS":
                exp = mb.status(p)
            elif reg == "IRQS":
                exp = mb.reg(p, "IRQS") & IRQS_THR
            if v != exp:
                self._ctrl_missing(
                    f"{inj.kind} mbox={m} snapshot {p}.{reg}=0x{v:x} model=0x{exp:x}"
                )
        resp, data = await self._ext(inj)
        after = {}
        for p in ("out", "in"):
            for reg in ("WIRQT", "RIRQT", "IRQEN", "STATUS"):
                after[(p, reg)] = await self._rd(m, p, reg)
            after[(p, "IRQS")] = (await self._rd(m, p, "IRQS")) & IRQS_THR
        live_same = all(after[k] == snap[k] for k in snap if k[1] in ("WIRQT", "RIRQT", "IRQEN"))
        st_same = all(after[k] == snap[k] for k in snap if k[1] in ("STATUS", "IRQS"))
        pops = [await self._pop_cmp(m, "in"), await self._pop_cmp(m, "out")]
        pops_match = sum(
            1 for (r, g, e), w in zip(pops, inj.pre_words) if r == RESP_OKAY and g == w
        )
        st_out = await self._rd(m, "out", "STATUS")
        st_in = await self._rd(m, "in", "STATUS")
        empty_after = int(bool(st_out & ST_EMPTY and st_in & ST_EMPTY))
        # Twin on the same aperture and master.
        tresp, _ = await self._ext(
            inj, op="rd", addr=port_base(m, inj.port) + MBX_REGS.offset("STATUS")
        )
        diff = [
            f"{p}.{r}:0x{snap[(p, r)]:x}->0x{after[(p, r)]:x}"
            for (p, r) in snap
            if snap[(p, r)] != after[(p, r)]
        ]
        txt = (
            f"mbox={m} port={inj.port} addr=0x{inj.addr():08x} op={inj.op} resp={resp_name(resp)} "
            f"data=0x{data & M32:x} wirqt=0x{snap[('out', 'WIRQT')]:x}/0x{snap[('in', 'WIRQT')]:x} "
            f"rirqt=0x{snap[('out', 'RIRQT')]:x}/0x{snap[('in', 'RIRQT')]:x} "
            f"irqen=0x{snap[('out', 'IRQEN')]:x}/0x{snap[('in', 'IRQEN')]:x} live_regs_same={int(live_same)} "
            f"status_irqs_same={int(st_same)} pops_match={pops_match} empty_after={empty_after} "
            f"twin=STATUS twin_resp={resp_name(tresp)} diff={';'.join(diff) or '-'}"
        )
        data_ok = inj.op == "wr" or (data & M32) == 0
        ok = (
            resp == RESP_SLVERR
            and data_ok
            and live_same
            and st_same
            and pops_match == 2
            and empty_after
        )
        if not ok:
            self._fail(chk, txt)
        self._pass(chk, txt)
        self._twin(inj.kind, m, inj.port, "STATUS", tresp)
        # Not graded: the flag effect of a hole access. Clear it and log it.
        obs = []
        for p in ("out", "in"):
            flags, irqs = await self._clear_port(m, p)
            obs.append(f"{p}.error_flags=0x{flags:x} {p}.irqs=0x{irqs:x}")
        self.logger.info(
            "OBS-HOLE-FLAGS LOG seed=%d kind=%s mbox=%d %s",
            self.seed,
            inj.kind,
            m,
            " ".join(obs),
        )

    async def _k6(self, inj: Inj) -> None:
        m = inj.m
        close_graded_window(self.logger)
        resp_open, _ = await self._ext(inj)
        idx = (2 * m, 2 * m + 1)
        for i in idx:
            await self.bank.set_enabled(i, False)
        cfgs = []
        for i in idx:
            cfg, _, _ = await self.bank.read_entry(i)
            cfgs.append(f"entry{i}.entry_enabled={int(bool(cfg & FILT_ENTRY_ENABLED))}")
        resp_closed, _ = await self._ext(inj)
        for i in idx:
            await self.bank.set_enabled(i, True)
        txt = (
            f"mbox={m} addr=0x{inj.addr():08x} op={inj.op} resp_open={resp_name(resp_open)} "
            f"exp_open=SLVERR resp_closed={resp_name(resp_closed)} exp_closed=DECERR {' '.join(cfgs)}"
        )
        if resp_open != RESP_SLVERR or resp_closed != RESP_DECERR:
            self._fail("CTL-RESP", txt)
        self.logger.info("CTL-RESP LOG seed=%d %s", self.seed, txt)
        obs = []
        for p in ("out", "in"):
            flags, irqs = await self._clear_port(m, p)
            obs.append(f"{p}.error_flags=0x{flags:x} {p}.irqs=0x{irqs:x}")
        self.logger.info(
            "OBS-HOLE-FLAGS LOG seed=%d kind=K6 mbox=%d %s", self.seed, m, " ".join(obs)
        )
        open_graded_window(TEST, self.logger)
        tresp, _ = await self._ext(
            inj, op="rd", addr=port_base(m, "in") + MBX_REGS.offset("STATUS")
        )
        self._twin("K6", m, "in", "STATUS", tresp, "after=re_enable")

    async def _flags_both(self) -> None:
        m, p = self.both_port
        mb = self.mbx[m]
        assert mb.read_occ(p) == 0 and mb.write_occ(p) == 0
        await self._flags_pre("CHK-FLAGS-BOTH", m, p)
        r1, _ = await self.ops[m].pop(p)
        mb.pop(p)
        words = self.both_words
        for w in words[:MAILBOX_DEPTH]:
            await self._setup_push(m, p, w)
        r2 = await self.ops[m].push(p, words[MAILBOX_DEPTH])
        mb.push(p, words[MAILBOX_DEPTH])
        first = await self._rd(m, p, "ERROR_FLAGS")
        second = await self._rd(m, p, "ERROR_FLAGS")
        pops = [await self._pop_cmp(m, PEER[p]) for _ in range(MAILBOX_DEPTH)]
        await self._wr(m, p, "IRQS", IRQ_EIRQ)
        txt = (
            f"mbox={m} port={p} k1_resp={resp_name(r1)} k2_resp={resp_name(r2)} first=0x{first:x} "
            f"exp_first=0x{ERR_READ | ERR_WRITE:x} second=0x{second:x}"
        )
        if r1 != RESP_SLVERR or r2 != RESP_SLVERR or first != (ERR_READ | ERR_WRITE) or second != 0:
            self._fail("CHK-FLAGS-BOTH", txt)
        if not all(r == RESP_OKAY and g == w for (r, g, _), w in zip(pops, words)):
            self._fail("CHK-FLAGS-BOTH", txt + " drain_mismatch=1")
        self._pass("CHK-FLAGS-BOTH", txt)

    async def _err_line(self) -> None:
        m = self.line_mbox
        mb = self.mbx[m]
        for p in ("out", "in"):
            await self._wr(m, p, "IRQEN", 0)
            await self._wr(m, p, "IRQS", IRQ_ALL)
        assert mb.occ("A") == 0 and mb.occ("B") == 0
        for p in ("in", "out"):

            async def line_obs(tag: str) -> tuple[int, str]:
                probe, smc = await self._sample_lines()
                exp_probe = self.mbx.in_lines()
                exp_cnt = self.mbx.out_count()
                if probe != exp_probe or popcount(smc) != exp_cnt:
                    self._fail(
                        "CHK-ERR-LINE",
                        f"mbox={m} port={p} at={tag} probe=0x{probe:02x} exp_probe=0x{exp_probe:02x} "
                        f"smc=0x{smc:02x} count={popcount(smc)} exp_count={exp_cnt}",
                    )
                if p == "in":
                    return (probe >> m) & 1, f"probe=0x{probe:02x}"
                return popcount(smc), f"smc=0x{smc:02x}"

            k_before = self.mbx.out_count()
            resp, data = await self.ops[m].pop(p)
            mb.pop(p)
            l0, s0 = await line_obs("before_enable")
            irqs = await self._rd(m, p, "IRQS")
            await self._wr(m, p, "IRQEN", IRQ_EIRQ)
            l1, s1 = await line_obs("after_enable")
            flags = await self._rd(m, p, "ERROR_FLAGS")
            l2, s2 = await line_obs("after_flags_read")
            await self._wr(m, p, "IRQS", IRQ_EIRQ)
            l3, s3 = await line_obs("after_w1c")
            await self._wr(m, p, "IRQEN", 0)
            if p == "in":
                txt = (
                    f"mbox={m} port=in resp={resp_name(resp)} irqs_bit2={(irqs >> 2) & 1} line_before_enable={l0} "
                    f"line_rise={l1} error_flags=0x{flags:x} line_after_read={l2} line_after_w1c={l3} "
                    f"{s0} {s1} {s2} {s3}"
                )
                ok = (l0, l1, l2, l3) == (0, 1, 1, 0)
            else:
                txt = (
                    f"mbox={m} port=out resp={resp_name(resp)} irqs_bit2={(irqs >> 2) & 1} k={k_before} "
                    f"smc_count_before_enable={l0} smc_count_after_enable={l1} smc_count_after_read={l2} "
                    f"error_flags=0x{flags:x} smc_count_after_w1c={l3} {s0} {s1} {s2} {s3}"
                )
                ok = (l0, l1, l2, l3) == (
                    k_before,
                    k_before + 1,
                    k_before + 1,
                    k_before,
                )
            ok = ok and resp == RESP_SLVERR and irqs & IRQ_EIRQ and flags == ERR_READ
            if not ok:
                self._fail("CHK-ERR-LINE", txt)
            self._pass("CHK-ERR-LINE", txt)

    async def _wo_read(self) -> None:
        for m in range(8):
            for p in ("out", "in"):
                await self._clear_port(m, p)
        his = []
        n = 0
        for m in range(8):
            for p in ("out", "in"):
                if (m, p) == (0, "out"):
                    continue
                self.mbx[m]
                w = self.wo_words[(m, p)]
                await self._setup_push(m, PEER[p], w)
                s0 = (
                    await self._rd(m, "out", "STATUS"),
                    await self._rd(m, "in", "STATUS"),
                )
                first = self.wo_first_half[(m, p)]
                got = {}
                addr = port_base(m, p) + MBX_REGS.offset("WRITE_DATA")
                for h in (first, 1 - first):
                    got[h] = await self.ops[m].raw("in", SepAxiOp.READ, addr + 4 * h, size=SIZE_4B)
                s1 = (
                    await self._rd(m, "out", "STATUS"),
                    await self._rd(m, "in", "STATUS"),
                )
                flags = await self._rd(m, p, "ERROR_FLAGS")
                presp, pg, pe = await self._pop_cmp(m, p)
                st = await self._rd(m, p, "STATUS")
                lo = got[0][1] & M32
                hi = got[1][1] & M32
                his.append(hi)
                txt = (
                    f"mbox={m} port={p} first_half={first} resp_lo={resp_name(got[0][0])} "
                    f"resp_hi={resp_name(got[1][0])} data_lo=0x{lo:08X} data_hi=0x{hi:08x} "
                    f"status_before=0x{s0[0]:x}/0x{s0[1]:x} status_after=0x{s1[0]:x}/0x{s1[1]:x} "
                    f"flags=0x{flags:x} pop=0x{pg:016x} exp=0x{pe:016x} empty_after={int(bool(st & ST_EMPTY))}"
                )
                ok = (
                    got[0][0] == RESP_OKAY
                    and got[1][0] == RESP_OKAY
                    and lo == WRITE_DATA_RD_SENTINEL
                    and s0 == s1
                    and not s0[0 if p == "out" else 1] & ST_EMPTY
                    and flags == 0
                    and presp == RESP_OKAY
                    and pg == pe == w
                    and st & ST_EMPTY
                )
                self.logger.info("WO-READ LOG seed=%d %s", self.seed, txt)
                if not ok:
                    self._fail("CHK-WO-READ", txt)
                n += 1
        self._pass(
            "CHK-WO-READ",
            f"apertures={n} resp=OKAY data_lo=0x{WRITE_DATA_RD_SENTINEL:08X} "
            f"data_hi={','.join(f'0x{h:x}' for h in sorted(set(his)))} status_same={n} flags=0x0",
        )

    # --------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.n_checks = 0
        self.rng = SepSeededRng(self.seed)
        self.used: set[int] = set()
        self.logger.info("SEED seed=%d", self.seed)
        self._draw()
        close_graded_window(self.logger)

        await self.bring_up_no_cpu()
        await SepMbox(self).ungate_clock()
        self.ops = ports(self)
        self.mbx = MboxSystem()
        self.bank = SepFilterBank(self, "in")
        for m in range(8):
            base = port_base(m, "out")
            for k, ns in enumerate((False, True)):
                await self.bank.program(
                    2 * m + k,
                    FilterEntry(
                        start=base,
                        end=base + PAIR_BYTES - 1,
                        enabled=True,
                        read_allowed=True,
                        write_allowed=True,
                        allow_ns=ns,
                        src_id=0,
                    ),
                )

        open_graded_window(TEST, self.logger)
        for i, inj in enumerate(self.injections):
            self.logger.info("INJ LOG seed=%d idx=%d %s", self.seed, i, inj.line())
            if inj.kind == "K1":
                await self._k1(inj)
            elif inj.kind == "K2":
                await self._k2(inj)
            elif inj.kind == "K3":
                await self._k3(inj)
            elif inj.kind in ("K4", "K5"):
                await self._k45(inj)
            else:
                await self._k6(inj)
            for m in range(8):
                mb = self.mbx[m]
                if mb.occ("A") or mb.occ("B"):
                    raise AssertionError(f"test error: mailbox {m} not drained after {inj.kind}")
        await self._flags_both()
        await self._err_line()
        await self._wo_read()
        close_graded_window(self.logger)
        self.result_pass(TEST, self.seed, self.n_checks)
