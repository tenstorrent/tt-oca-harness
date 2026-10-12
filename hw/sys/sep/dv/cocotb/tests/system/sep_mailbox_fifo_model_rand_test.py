# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Paired mailbox FIFOs of all eight SEP mailboxes against a golden queue model.

Contract (``hw/sys/sep/doc/mailbox.adoc``, "Mailboxes";
``hw/ip/axi_lite_mailbox_unit/doc/architecture.adoc``, "Paired FIFOs",
"Interrupts"; ``hw/ip/axi_lite_mailbox_unit/doc/interface.adoc``, "Access
Results", "Sending and Receiving";
``hw/ip/axi_lite_mailbox_unit/regs/gen/adoc/axil_mailbox.adoc``;
``hw/sys/sep/doc/interrupts.adoc``, "SEP PIC source assignments";
``hw/sys/sep/doc/port_table.adoc``):

* mailbox ``m`` holds FIFO A (outbound writes, inbound reads) and FIFO B
  (inbound writes, outbound reads), 8 entries of 64 bits each; a write at
  either half of ``WRITE_DATA`` pushes one entry and a read at either half of
  ``READ_DATA`` pops one entry;
* ``STATUS`` bit 2 is set while the write FIFO occupancy is above ``WIRQT``
  and bit 3 while the read FIFO occupancy is above ``RIRQT``; a threshold
  above 7 acts as 7; ``IRQS`` latches a cause until its write-one-to-clear
  and sets again while the condition holds; ``IRQP`` is ``IRQS`` AND
  ``IRQEN``; the line of a port is the OR of ``IRQP``;
* a flush bit discards the selected FIFO and ``CTRL`` reads 0;
* the inbound line of mailbox ``m`` is bit ``m`` of
  ``sep_internal_interrupts_probe_o``; the eight outbound lines are the eight
  bits of ``smc_mailbox_interrupt_o``, graded as a set (count, 0x00, 0xFF,
  Hamming distance), because no text states the port-bit map.

Expected values come from ``env/sep_mbox_pair_model.MboxSystem``, which holds
the stimulus only. The CPU-LSU master drives the outbound apertures; the
external SMN master drives the inbound apertures through one inbound filter
window per mailbox (``src_id`` 0, ``allow_ns`` 0, ``AxPROT[1]`` 0).

Every operation is followed by a check cycle: a bounded settle wait until the
probe bits [7:0] and the port equal the model, a quiet window of a fixed
number of clocks with no mailbox access (``u_sep_fcov.quiet_win`` held at 1
on VCS) in which ``SepBitWatch`` samples the 16 lines and probe bit 14 on
every clock, and then the reads of ``STATUS``, ``IRQS``, ``IRQEN`` and
``IRQP`` of both ports of the mailbox under test.

Legs per mailbox, in seeded order: threshold runs on both FIFOs (boundary
values 7, 0, 8 and 255 on the first mailbox, two drawn values per FIFO on
every mailbox), the two-threshold alias on FIFO A, one flush kind, the
``IRQEN`` gate and the acknowledge of each cause on each port, and the drain.
Then the outbound-set leg raises all eight outbound lines and a subset of
inbound lines and releases them one at a time.

Checks: CHK-ENTRY, CHK-STATUS, CHK-CLAMP, CHK-FLUSH, CHK-CTRL0, CHK-ALIAS,
CHK-LINE-IN, CHK-LINE-OUT, CHK-LINE-ISO, CHK-GATE, CHK-W1C, CHK-WIDTH,
CHK-GLITCH, CHK-NONVAC. The outbound mailbox 0 cells that open tests grade
(the outbound write threshold and ``wtirq`` gate of FIFO A, the acknowledge
of ``wtirq`` above the threshold, the outbound ``wflush`` and the outbound
read threshold of FIFO B) run as controls and print ``CTL-<NAME> LOG``;
``STATUS`` bits [1:0] print ``CTL-STATUS LOG`` outside the flush check; the
alias-leg pops print ``CTL-ENTRY LOG``.
Log only: ``OBS-KM-LINE`` (probe bit 14), ``OBS-SMC-MAP`` (the port bit that
rose when one outbound line rose).

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``, RAND-REP.
Every draw comes from ``SepSeededRng`` and the run seed: mailbox order,
``IRQEN`` values, payloads, access widths and halves, threshold values (1, 6
and 9 weighted, other 8-bit values), fill counts, flush kinds (each kind on
two mailboxes), alias thresholds, outbound-set order and subset.
"""

from __future__ import annotations

import logging
from typing import Any

import cocotb
import pyuvm
from cocotb.triggers import FallingEdge, ReadOnly, RisingEdge
from env.sep_bit_watch import SepBitWatch
from env.sep_fcov_gate import close_graded_window, open_graded_window, set_quiet_window
from env.sep_filter_model import FilterEntry
from env.sep_mbox_golden import (
    CTRL_WFLUSH,
    IRQ_RTIRQ,
    IRQ_WTIRQ,
    MAILBOX_DEPTH,
    ST_EMPTY,
    ST_FULL,
    ST_RLVL_ABOVE,
    ST_WLVL_ABOVE,
)
from env.sep_mbox_pair_model import (
    CTRL_RFLUSH,
    IRQ_ALL,
    READ_FIFO,
    WRITE_FIFO,
    MboxSystem,
    popcount,
)
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import AXIL_MAILBOX_OUTBOUND_0 as MBX_REGS
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_mailbox_iface_seq import SepMbox
from seq_lib.sep_mailbox_walk_seq import inbound_base
from seq_lib.sep_mbox_port_ops import RESP_OKAY, ports, resp_name

TEST = "sep_mailbox_fifo_model_rand_test"

M32 = 0xFFFF_FFFF
M64 = (1 << 64) - 1
PEER = {"out": "in", "in": "out"}
FIFO_WRITER = {"A": "out", "B": "in"}
FIFO_READER = {"A": "in", "B": "out"}
FIELD = {r: MBX_REGS.mask32(r) for r in ("STATUS", "IRQS", "IRQEN", "IRQP", "CTRL")}
ABOVE = ST_WLVL_ABOVE | ST_RLVL_ABOVE
EMPTY_FULL = ST_EMPTY | ST_FULL
BOUNDARY = (7, 0, 8, 255)
MB0_CHK_THRESH = (0, 7, 8, 9, 255)
CAUSE_BIT = {"wtirq": IRQ_WTIRQ, "rtirq": IRQ_RTIRQ}


def _wab(st: int) -> int:
    """STATUS.write_level_above_thresh as 0 or 1."""
    return int(bool(st & ST_WLVL_ABOVE))


def _rab(st: int) -> int:
    """STATUS.read_level_above_thresh as 0 or 1."""
    return int(bool(st & ST_RLVL_ABOVE))


FLUSH_KINDS = ("wflush_out", "rflush_in", "wflush_in", "rflush_out")
FLUSH_SPEC = {
    # kind: (port written, CTRL bit, flushed FIFO)
    "wflush_out": ("out", CTRL_WFLUSH, "A"),
    "rflush_in": ("in", CTRL_RFLUSH, "A"),
    "wflush_in": ("in", CTRL_WFLUSH, "B"),
    "rflush_out": ("out", CTRL_RFLUSH, "B"),
}
GATE_CELLS = (("wtirq", "out"), ("rtirq", "out"), ("wtirq", "in"), ("rtirq", "in"))
SETTLE_BOUND = 200
QUIET_CLKS = 12
EXPECTED_WIDTH = 8
KM_BIT = 14


class Ctx:
    """The leg in progress; decides whether an outbound mailbox 0 cell is a control."""

    def __init__(self, leg: str, m: int, **kw) -> None:
        self.leg = leg
        self.m = m
        self.value = kw.get("value")
        self.fifo = kw.get("fifo")
        self.kind = kw.get("kind")
        self.cause = kw.get("cause")
        self.port = kw.get("port")

    def out_is_ctl(self, m: int) -> bool:
        if m != 0 or self.m != 0:
            return False
        if self.leg == "thresh":
            return self.value not in MB0_CHK_THRESH
        if self.leg in ("flush", "flush_post"):
            return self.kind == "wflush_out"
        if self.leg in ("gate", "ack"):
            return self.cause == "wtirq" and self.port == "out"
        return False

    def tag(self) -> str:
        s = f"leg={self.leg}"
        for k in ("value", "fifo", "kind", "cause", "port"):
            v = getattr(self, k)
            if v is not None:
                s += f" {k}={v}"
        return s


class CC:
    """The result of one check cycle."""

    def __init__(self, probe: int, smc: int, km: int) -> None:
        self.probe = probe
        self.smc = smc
        self.km = km
        self.r: dict[tuple[int, str], dict[str, int]] = {}


@pyuvm.test()
class sep_mailbox_fifo_model_rand_test(sep_base_test):
    """Golden queue model of all eight paired mailboxes: thresholds, flush, gate, acknowledge, lines."""

    required_evidence = (
        "CHK-ENTRY",
        "CHK-STATUS",
        "CHK-CLAMP",
        "CHK-FLUSH",
        "CHK-CTRL0",
        "CHK-ALIAS",
        "CHK-LINE-IN",
        "CHK-LINE-OUT",
        "CHK-LINE-ISO",
        "CHK-GATE",
        "CHK-W1C",
        "CHK-WIDTH",
        "CHK-GLITCH",
        "CHK-NONVAC",
    )

    # ------------------------------------------------------------------ log
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.seed, line)
        self.n_checks += 1

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _grade(self, chk: str, ok: bool, line: str, *, ctl: bool = False) -> None:
        """A CHK line, or a CTL line for an open-test cell (a CTL mismatch still fails)."""
        if ctl:
            name = "CTL-" + chk[4:]
            if not ok:
                self._fail(name, line)
            self.logger.info("%s LOG seed=%d %s", name, self.seed, line)
            return
        if not ok:
            self._fail(chk, line)
        self._pass(chk, line)

    def _ctrl_missing(self, line: str) -> None:
        msg = f"CTRL-MISSING seed={self.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _quiet_axi_logs(self) -> None:
        for agent in (self.env.axi_agent, self.env.ext_axi_agent):
            drv = agent.driver
            drv.logger.setLevel(logging.WARNING)
            be = drv.axi.driver.backend
            be.read_if.log.setLevel(logging.WARNING)
            be.write_if.log.setLevel(logging.WARNING)

    # --------------------------------------------------------------- access
    async def _push(self, m: int, port: str, data: int, half: int | None = None) -> None:
        resp = await self.ops[m].push(port, data, half=half)
        exp = self.mbx[m].push(port, data, half=half)
        if exp != "OKAY":
            raise AssertionError(f"test error: push on mbox {m} {port} with a full FIFO")
        if resp != RESP_OKAY:
            self._fail(
                "CHK-STATUS",
                f"mbox={m} port={port} push resp={resp_name(resp)} exp=OKAY occ_before<8",
            )

    async def _pop(self, m: int, port: str, half: int | None = None) -> tuple[int, int | None, int]:
        """(got, exp, occ_before). The response of a pop with data is OKAY."""
        occ = self.mbx[m].read_occ(port)
        if occ == 0:
            raise AssertionError(f"test error: pop on mbox {m} {port} with an empty FIFO")
        resp, data = await self.ops[m].pop(port, half=half)
        _, exp, _ = self.mbx[m].pop(port, half=half)
        if resp != RESP_OKAY:
            self._fail(
                "CHK-STATUS",
                f"mbox={m} port={port} pop resp={resp_name(resp)} exp=OKAY occ_before={occ}",
            )
        return data, exp, occ

    async def _wr(self, m: int, port: str, reg: str, value: int) -> None:
        await self.ops[m].wr_ok(port, reg, value)
        self.mbx[m].write_reg(port, reg, value)

    async def _rd(self, m: int, port: str, reg: str) -> int:
        return int(await self.ops[m].rd_ok(port, reg))

    # ------------------------------------------------------------- check cycle
    async def _check(self, mboxes: list[int], note: str) -> CC:
        dut: Any = cocotb.top
        clk = dut.clk_i
        exp_in = self.mbx.in_lines()
        exp_cnt = self.mbx.out_count()
        out_now = self.mbx.out_lines()
        probe = smc = -1
        for _ in range(SETTLE_BOUND):
            await RisingEdge(clk)
            await ReadOnly()
            probe = self.rd(dut.sep_internal_interrupts_probe_o, 0xFF) & 0xFF
            smc = self.rd(dut.smc_mailbox_interrupt_o, 0xFF) & 0xFF
            if probe == exp_in and popcount(smc) == exp_cnt:
                break
        else:
            chk = "CHK-LINE-IN" if probe != exp_in else "CHK-LINE-OUT"
            self._fail(
                chk,
                f"{self.ctx.tag()} {note} settle_timeout={SETTLE_BOUND} probe=0x{probe:02x} model=0x{exp_in:02x} "
                f"smc=0x{smc:02x} popcount={popcount(smc)} high_model={exp_cnt}",
            )
        await FallingEdge(clk)
        set_quiet_window(True)
        mk_in = self.w_in.mark()
        mk_out = self.w_out.mark()
        for _ in range(QUIET_CLKS):
            await RisingEdge(clk)
        await ReadOnly()
        probe_end = self.rd(dut.sep_internal_interrupts_probe_o, 0xFF) & 0xFF
        smc_end = self.rd(dut.smc_mailbox_interrupt_o, 0xFF) & 0xFF
        await FallingEdge(clk)
        end = self.w_in.clk
        toggles = 0
        for w, mk in ((self.w_in, mk_in), (self.w_out, mk_out)):
            for b in w.bits:
                if b == "km":
                    continue
                toggles += len([c for c in w.rise_clks_since(mk, b) if c <= end])
                toggles += len([c for c in w.fall_clks_since(mk, b) if c <= end])
        set_quiet_window(False)
        km = self.w_in.level("km")
        self.windows += 1
        if probe_end or smc_end:
            self.windows_high += 1
        if toggles or probe_end != probe or smc_end != smc:
            self._fail(
                "CHK-GLITCH",
                f"{self.ctx.tag()} {note} window={self.windows} toggles={toggles} "
                f"probe=0x{probe:02x}->0x{probe_end:02x} smc=0x{smc:02x}->0x{smc_end:02x}",
            )
        if km != self.last_km:
            self.logger.info(
                "OBS-KM-LINE LOG seed=%d bit14=%s window=%d %s",
                self.seed,
                km,
                self.windows,
                note,
            )
            self.last_km = km
        cc = CC(probe_end, smc_end, km)

        # ---- the 16 lines --------------------------------------------------
        all_zero_ok = "na" if exp_cnt else int(smc_end == 0)
        all_one_ok = "na" if exp_cnt != 8 else int(smc_end == 0xFF)
        self.max_high = max(self.max_high, exp_cnt)
        out_ok = popcount(smc_end) == exp_cnt and all_zero_ok != 0 and all_one_ok != 0
        self._grade(
            "CHK-LINE-OUT",
            out_ok,
            f"high_model={exp_cnt} smc=0x{smc_end:02x} popcount={popcount(smc_end)} "
            f"all_zero_ok={all_zero_ok} all_one_ok={all_one_ok} {note}",
        )
        if exp_cnt == 8 and smc_end == 0xFF:
            self.seen_all_one = True
        changed = sum(1 for a, b in zip(out_now, self.prev_out) if a != b)
        ham = popcount(smc_end ^ self.prev_smc)
        driven = mboxes[0]
        others = probe_end & ~(1 << driven) & 0xFF
        others_model = exp_in & ~(1 << driven) & 0xFF
        moved = ((probe_end ^ self.prev_probe) >> driven) & 1 or changed
        if moved:
            self.iso_moves += 1
        self._grade(
            "CHK-LINE-ISO",
            others == others_model and ham == changed,
            f"driven={driven} others=0x{others:02x} model=0x{others_model:02x} smc_hamming={ham} "
            f"model_changed={changed} driven_moved={int(bool(moved))} {note}",
        )
        rose = [m for m in range(8) if out_now[m] and not self.prev_out[m]]
        if len(rose) == 1 and popcount(smc_end & ~self.prev_smc) == 1:
            bit = (smc_end & ~self.prev_smc).bit_length() - 1
            self.logger.info("OBS-SMC-MAP LOG seed=%d mbox=%d bit=%d", self.seed, rose[0], bit)
        self.prev_out = out_now
        self.prev_smc = smc_end
        self.prev_probe = probe_end

        # ---- the registers of both ports -----------------------------------
        for m in mboxes:
            mb = self.mbx[m]
            for p in ("out", "in"):
                vals = {
                    reg: await self._rd(m, p, reg) for reg in ("STATUS", "IRQS", "IRQEN", "IRQP")
                }
                cc.r[(m, p)] = vals
                ctl_out = p == "out" and self.ctx.out_is_ctl(m)
                st = vals["STATUS"]
                exp_st = mb.status(p)
                r = mb.regs[p]
                self._grade(
                    "CHK-STATUS",
                    (st & ABOVE) == (exp_st & ABOVE),
                    f"mbox={m} port={p} occ={mb.write_occ(p)} rocc={mb.read_occ(p)} wirqt={r.wirqt} "
                    f"rirqt={r.rirqt} wabove={_wab(st)} rabove={_rab(st)} "
                    f"exp_wabove={_wab(exp_st)} exp_rabove={_rab(exp_st)} "
                    f"rsvd=0x{st & ~FIELD['STATUS'] & M32:x} {self.ctx.tag()}",
                    ctl=ctl_out,
                )
                if self.ctx.leg != "flush_post":
                    ok = (st & EMPTY_FULL) == (exp_st & EMPTY_FULL)
                    line = (
                        f"mbox={m} port={p} occ={mb.write_occ(p)} rocc={mb.read_occ(p)} empty={int(bool(st & ST_EMPTY))} "
                        f"full={int(bool(st & ST_FULL))} exp_empty={int(bool(exp_st & ST_EMPTY))} "
                        f"exp_full={int(bool(exp_st & ST_FULL))}"
                    )
                    if not ok:
                        self._fail("CTL-STATUS", line)
                    self.logger.info("CTL-STATUS LOG seed=%d %s", self.seed, line)
                irqs = vals["IRQS"] & FIELD["IRQS"]
                irqen = vals["IRQEN"] & FIELD["IRQEN"]
                irqp = vals["IRQP"] & FIELD["IRQP"]
                ex = {k: mb.reg(p, k) for k in ("IRQS", "IRQEN", "IRQP")}
                rsvd = (vals["IRQS"] | vals["IRQEN"] | vals["IRQP"]) & ~FIELD["IRQS"] & M32
                ok = irqs == ex["IRQS"] and irqen == ex["IRQEN"] and irqp == ex["IRQP"]
                if p == "in":
                    line = (
                        f"mbox={m} port=in occ_B={mb.occ('B')} occ_A={mb.occ('A')} wirqt={r.wirqt} "
                        f"rirqt={r.rirqt} irqen=0x{irqen:x} exp_irqen=0x{ex['IRQEN']:x} irqs=0x{irqs:x} "
                        f"exp_irqs=0x{ex['IRQS']:x} irqp=0x{irqp:x} exp_irqp=0x{ex['IRQP']:x} "
                        f"probe={(probe_end >> m) & 1} model={(exp_in >> m) & 1} rsvd=0x{rsvd:x} {note}"
                    )
                    self._grade("CHK-LINE-IN", ok and ((probe_end ^ exp_in) >> m) & 1 == 0, line)
                else:
                    line = (
                        f"mbox={m} port=out occ_A={mb.occ('A')} occ_B={mb.occ('B')} wirqt={r.wirqt} "
                        f"rirqt={r.rirqt} irqen=0x{irqen:x} exp_irqen=0x{ex['IRQEN']:x} irqs=0x{irqs:x} "
                        f"exp_irqs=0x{ex['IRQS']:x} irqp=0x{irqp:x} exp_irqp=0x{ex['IRQP']:x} "
                        f"model_line={mb.line('out')} rsvd=0x{rsvd:x} {note}"
                    )
                    self._grade("CHK-LINE-OUT", ok, line, ctl=ctl_out)
        return cc

    def _line(self, cc: CC, m: int, port: str) -> int:
        """The observed line of one port: probe bit m, or the port count less the other outbound lines."""
        if port == "in":
            return (cc.probe >> m) & 1
        others = sum(self.mbx[k].line("out") for k in range(8) if k != m)
        return popcount(cc.smc) - others

    # ------------------------------------------------------------------ draws
    def _payload(self, used: set, bits: int = 64) -> int:
        while True:
            v = self.rng.getrandbits(bits)
            if v and v not in used:
                used.add(v)
                return v

    def _width(self) -> int | None:
        """None for a 64-bit access, else the 32-bit half."""
        c = self.rng.randrange(0, 3)
        return None if c == 0 else c - 1

    def _drawn_thresh(self) -> int:
        if self.rng.randrange(0, 2):
            return self.rng.choice([1, 6, 9])
        pool = list(range(2, 6)) + list(range(10, 255))
        return self.rng.choice(pool)

    def _fill(self, v: int) -> int:
        if v >= MAILBOX_DEPTH - 1:
            return MAILBOX_DEPTH
        return self.rng.choice([c for c in (v - 1, v, v + 1) if c >= 1])

    def _draw(self) -> None:
        r = self.rng
        self.order = list(range(8))
        r.shuffle(self.order)
        kinds = list(FLUSH_KINDS) * 2
        r.shuffle(kinds)
        self.plan: dict[int, dict] = {}
        for i, m in enumerate(self.order):
            runs = []
            values: dict[str, list[int]] = {"A": [], "B": []}
            for f in ("A", "B"):
                drawn = [self._drawn_thresh(), self._drawn_thresh()]
                values[f] = (list(BOUNDARY) if i == 0 else []) + drawn
            # Each value runs on FIFO A then FIFO B; boundary values first.
            for f in ("A", "B"):
                for v in values[f]:
                    n = self._fill(v)
                    used: set = set()
                    pushes = []
                    for _ in range(n):
                        h = self._width()
                        pushes.append((self._payload(used, 64 if h is None else 32), h))
                    pops = [self._width() for _ in range(n)]
                    runs.append(
                        {
                            "fifo": f,
                            "value": v,
                            "fill": n,
                            "irqen": (r.randrange(0, 8), r.randrange(0, 8)),
                            "pushes": pushes,
                            "pops": pops,
                        }
                    )
            a = r.randrange(0, 8)
            b = r.choice([x for x in range(8) if x != a])
            used = set()
            alias_words = [self._payload(used) for _ in range(MAILBOX_DEPTH)]
            na, nb = r.randrange(1, 9), r.randrange(1, 9)
            used = set()
            fl_words = {
                "A": [self._payload(used) for _ in range(na)],
                "B": [self._payload(used) for _ in range(nb)],
            }
            fl_pops = [self._width() for _ in range(MAILBOX_DEPTH)]
            gate_words = [self._payload(used) for _ in GATE_CELLS]
            ack = []
            for _ in GATE_CELLS:
                w = r.randrange(1, 7)
                ack.append((w, [self._payload(used) for _ in range(w + 4)]))
            self.plan[m] = {
                "runs": runs,
                "alias": (a, b, alias_words),
                "flush": (kinds[m], fl_words, fl_pops),
                "gate": gate_words,
                "ack": ack,
            }
            self.logger.info(
                "DRAW mbox=%d pos=%d thresh_A=%s thresh_B=%s alias=%d,%d flush=%s fill_A=%d fill_B=%d ack_w=%s",
                m,
                i,
                values["A"],
                values["B"],
                a,
                b,
                kinds[m],
                na,
                nb,
                [w for w, _ in ack],
            )
            for k, run in enumerate(runs):
                self.logger.info(
                    "DRAW mbox=%d run=%d fifo=%s value=%d fill=%d irqen_out=%d irqen_in=%d widths=%s pops=%s "
                    "words=%s",
                    m,
                    k,
                    run["fifo"],
                    run["value"],
                    run["fill"],
                    run["irqen"][0],
                    run["irqen"][1],
                    ",".join("64" if h is None else f"32h{h}" for _, h in run["pushes"]),
                    ",".join("64" if h is None else f"32h{h}" for h in run["pops"]),
                    ",".join(f"0x{w:x}" for w, _ in run["pushes"]),
                )
        self.set_order = list(range(8))
        r.shuffle(self.set_order)
        self.set_k = r.randrange(1, 7)
        used = set()
        self.set_words_out = {m: self._payload(used) for m in range(8)}
        self.set_words_in = {m: self._payload(used) for m in range(8)}
        rel = [("out", m) for m in range(8)] + [("in", m) for m in self.set_order[: self.set_k]]
        r.shuffle(rel)
        self.set_release = rel
        self.logger.info(
            "DRAW mailbox_order=%s set_order=%s set_k=%d release=%s",
            self.order,
            self.set_order,
            self.set_k,
            ",".join(f"{p}{m}" for p, m in rel),
        )

    # ------------------------------------------------------------------ legs
    def _gate(self, graded: bool) -> None:
        if graded == getattr(self, "_graded", None):
            return
        self._graded = graded
        if graded:
            open_graded_window(TEST, self.logger)
        else:
            close_graded_window(self.logger)

    async def _threshold_leg(self, m: int) -> None:
        mb = self.mbx[m]
        ref: dict[str, dict[int, tuple[int, int]]] = {}
        for run in self.plan[m]["runs"]:
            f, v = run["fifo"], run["value"]
            wp, rp = FIFO_WRITER[f], FIFO_READER[f]
            self.ctx = Ctx("thresh", m, value=v, fifo=f)
            await self._wr(m, "out", "IRQEN", run["irqen"][0])
            await self._wr(m, "in", "IRQEN", run["irqen"][1])
            await self._wr(m, wp, "WIRQT", v)
            await self._wr(m, rp, "RIRQT", v)
            seen: dict[int, tuple[int, int]] = {}
            for k, (data, half) in enumerate(run["pushes"]):
                await self._push(m, wp, data, half)
                cc = await self._check([m], f"push={k + 1}")
                occ = mb.occ(f)
                bits = (
                    _wab(cc.r[(m, wp)]["STATUS"]),
                    _rab(cc.r[(m, rp)]["STATUS"]),
                )
                seen[occ] = bits
            for half in run["pops"]:
                await self._pop(m, rp, half)
                await self._check([m], f"pop_to={mb.occ(f)}")
            await self._wr(m, "out", "IRQS", IRQ_ALL)
            await self._wr(m, "in", "IRQS", IRQ_ALL)
            await self._check([m], "irqs_clear")
            if v == 7:
                ref[f] = seen
            elif v in (8, 255) and f in ref:
                r7 = ref[f]
                exp = {o: (int(o > 7), int(o > 7)) for o in (7, 8)}
                ok = seen.get(7) == r7.get(7) == exp[7] and seen.get(8) == r7.get(8) == exp[8]
                self._grade(
                    "CHK-CLAMP",
                    ok,
                    f"mbox={m} fifo={f} written={v} fires_at_occ=8 not_at_occ=7 ref_thr7_fires_at_occ=8 "
                    f"at7=w{seen.get(7, ('-', '-'))[0]}r{seen.get(7, ('-', '-'))[1]} "
                    f"at8=w{seen.get(8, ('-', '-'))[0]}r{seen.get(8, ('-', '-'))[1]} "
                    f"ref7_at7={r7.get(7)} ref7_at8={r7.get(8)}",
                )

    async def _alias_leg(self, m: int) -> None:
        mb = self.mbx[m]
        a, b, words = self.plan[m]["alias"]
        self.ctx = Ctx("alias", m)
        await self._wr(m, "out", "WIRQT", a)
        await self._wr(m, "in", "RIRQT", b)

        def alias_line(cc: CC, note: str) -> None:
            wab = _wab(cc.r[(m, "out")]["STATUS"])
            rab = _rab(cc.r[(m, "in")]["STATUS"])
            ew = _wab(mb.status("out"))
            er = _rab(mb.status("in"))
            self._grade(
                "CHK-ALIAS",
                wab == ew and rab == er,
                f"mbox={m} wirqt_out={a} rirqt_in={b} occ_A={mb.occ('A')} wabove={wab} rabove={rab} "
                f"exp_wabove={ew} exp_rabove={er} {note}",
            )

        alias_line(await self._check([m], "alias_start"), "start")
        for w in words:
            await self._push(m, "out", w)
            alias_line(await self._check([m], f"alias_push occ={mb.occ('A')}"), "push")
        for _ in words:
            got, exp, occ = await self._pop(m, "in")
            ok = got & M64 == exp
            line = (
                f"mbox={m} fifo=A half=- got=0x{got & M64:016x} exp=0x{exp:016x} occ_before={occ}"
            )
            if not ok:
                self._fail("CTL-ENTRY", line)
            self.logger.info("CTL-ENTRY LOG seed=%d %s", self.seed, line)
            alias_line(await self._check([m], f"alias_pop occ={mb.occ('A')}"), "pop")
        await self._wr(m, "out", "IRQS", IRQ_ALL)
        await self._wr(m, "in", "IRQS", IRQ_ALL)

    async def _flush_leg(self, m: int) -> None:
        mb = self.mbx[m]
        kind, words, pops = self.plan[m]["flush"]
        port, bit, flushed = FLUSH_SPEC[kind]
        other = "B" if flushed == "A" else "A"
        self.ctx = Ctx("flush", m, kind=kind)
        ctl = self.ctx.out_is_ctl(m)
        self._gate(not ctl)
        for f in ("A", "B"):
            for w in words[f]:
                await self._push(m, FIFO_WRITER[f], w)
        await self._check([m], "flush_pre")
        reader = FIFO_READER[flushed]
        pre = await self._rd(m, reader, "STATUS")
        pre_empty = pre & ST_EMPTY
        if pre_empty:
            self._ctrl_missing(f"CHK-FLUSH mbox={m} kind={kind} pre-flush reader STATUS empty")
        n_other = mb.occ(other)
        await self._wr(m, port, "CTRL", bit)
        cresp, ctrl = await self.ops[m].rd(port, "CTRL")
        self._grade(
            "CHK-CTRL0",
            cresp == RESP_OKAY and (ctrl & FIELD["CTRL"]) == 0,
            f"mbox={m} kind={kind} ctrl_read=0x{ctrl & FIELD['CTRL']:x} resp={resp_name(cresp)} "
            f"rsvd=0x{ctrl & ~FIELD['CTRL'] & M32:x}",
            ctl=ctl,
        )
        self.ctx = Ctx("flush_post", m, kind=kind)
        cc = await self._check([m], "flush_post")
        st_reader = cc.r[(m, reader)]["STATUS"]
        st_other = cc.r[(m, FIFO_READER[other])]["STATUS"]
        reader_empty = int(bool(st_reader & ST_EMPTY))
        other_empty = int(bool(st_other & ST_EMPTY))
        self.ctx = Ctx("flush", m, kind=kind)
        popped = 0
        for k in range(n_other):
            half = pops[k]
            got, exp, occ = await self._pop(m, FIFO_READER[other], half)
            ok = exp is not None and got == exp
            if ok:
                popped += 1
            self._grade(
                "CHK-ENTRY",
                ok,
                f"mbox={m} fifo={other} half={'-' if half is None else half} got=0x{got:x} "
                f"exp=0x{exp if exp is not None else 0:x} occ_before={occ} kind={kind}",
                ctl=ctl,
            )
            cc = await self._check([m], f"flush_pop occ={mb.occ(other)}")
        end_empty = cc.r[(m, FIFO_READER[other])]["STATUS"] & ST_EMPTY
        ok = reader_empty == 1 and other_empty == 0 and popped == n_other and end_empty
        self._grade(
            "CHK-FLUSH",
            ok,
            f"mbox={m} kind={kind.split('_')[0]} port={port} flushed={flushed} reader_status_empty={reader_empty} "
            f"pre_flush_reader_empty={int(bool(pre_empty))} other_occ={popped} exp_other_occ={n_other} "
            f"other_reader_empty_after_flush={other_empty} other_empty_after_pops={int(bool(end_empty))}",
            ctl=ctl,
        )
        await self._wr(m, "out", "IRQS", IRQ_ALL)
        await self._wr(m, "in", "IRQS", IRQ_ALL)
        self._gate(True)

    def _watched(self, cause: str, port: str) -> tuple[str, str, str]:
        """(FIFO, push port, pop port) of the FIFO that ``cause`` on ``port`` watches."""
        f = WRITE_FIFO[port] if cause == "wtirq" else READ_FIFO[port]
        return f, FIFO_WRITER[f], FIFO_READER[f]

    async def _gate_leg(self, m: int) -> None:
        for (cause, port), word in zip(GATE_CELLS, self.plan[m]["gate"]):
            self.ctx = Ctx("gate", m, cause=cause, port=port)
            ctl = self.ctx.out_is_ctl(m)
            self._gate(not ctl)
            bit = CAUSE_BIT[cause]
            await self._wr(m, port, "IRQEN", 0)
            await self._wr(m, port, "WIRQT", 0)
            await self._wr(m, port, "RIRQT", 0)
            await self._wr(m, port, "IRQS", IRQ_ALL)
            f, pu, po = self._watched(cause, port)
            await self._push(m, pu, word)
            c1 = await self._check([m], f"gate_off cause={cause} port={port}")
            r1 = c1.r[(m, port)]
            l1 = self._line(c1, m, port)
            await self._wr(m, port, "IRQEN", bit)
            c2 = await self._check([m], f"gate_on cause={cause} port={port}")
            r2 = c2.r[(m, port)]
            l2 = self._line(c2, m, port)
            irqs1, irqp1 = r1["IRQS"] & IRQ_ALL, r1["IRQP"] & IRQ_ALL
            irqp2 = r2["IRQP"] & IRQ_ALL
            ok = irqs1 == bit and irqp1 == 0 and l1 == 0 and irqp2 == bit and l2 == 1
            self._grade(
                "CHK-GATE",
                ok,
                f"mbox={m} port={port} cause={cause} irqs=0x{irqs1:x} irqen=0x{r1['IRQEN'] & IRQ_ALL:x} "
                f"irqp=0x{irqp1:x} line={l1} then irqen=0x{r2['IRQEN'] & IRQ_ALL:x} irqp=0x{irqp2:x} line={l2}",
                ctl=ctl,
            )
            await self._pop(m, po)
            await self._wr(m, port, "IRQS", IRQ_ALL)
            await self._check([m], f"gate_done cause={cause} port={port}")
        self._gate(True)

    async def _ack_leg(self, m: int) -> None:
        mb = self.mbx[m]
        for (cause, port), (w, words) in zip(GATE_CELLS, self.plan[m]["ack"]):
            self.ctx = Ctx("ack", m, cause=cause, port=port)
            ctl = self.ctx.out_is_ctl(m)
            self._gate(not ctl)
            bit = CAUSE_BIT[cause]
            f, pu, po = self._watched(cause, port)
            await self._wr(m, port, "IRQEN", bit)
            await self._wr(m, port, "WIRQT" if cause == "wtirq" else "RIRQT", w)
            await self._wr(m, port, "IRQS", IRQ_ALL)
            for d in words[: w + 2]:
                await self._push(m, pu, d)
            c1 = await self._check([m], f"ack_above cause={cause} port={port}")
            for _ in range(2):
                await self._pop(m, po)
            c2 = await self._check([m], f"ack_below cause={cause} port={port}")
            occ_below = mb.occ(f)
            await self._wr(m, port, "IRQS", bit)
            c3 = await self._check([m], f"ack_w1c_below cause={cause} port={port}")
            for d in words[w + 2 : w + 4]:
                await self._push(m, pu, d)
            occ_above = mb.occ(f)
            c4 = await self._check([m], f"ack_reabove cause={cause} port={port}")
            await self._wr(m, port, "IRQS", bit)
            c5 = await self._check([m], f"ack_w1c_above cause={cause} port={port}")

            def s(cc: CC) -> tuple[int, int]:
                return self._line(cc, m, port), cc.r[(m, port)]["IRQS"] & bit

            got = [s(c) for c in (c1, c2, c3, c4, c5)]
            exp = [(1, bit), (1, bit), (0, 0), (1, bit), (1, bit)]
            self._grade(
                "CHK-W1C",
                got == exp,
                f"mbox={m} port={port} cause={cause} {'wirqt' if cause == 'wtirq' else 'rirqt'}={w} "
                f"occ_below={occ_below} occ_above={occ_above} above=line{got[0][0]}_irqs0x{got[0][1]:x} "
                f"below_before_ack=line{got[1][0]}_irqs0x{got[1][1]:x} "
                f"w1c_below=line{got[2][0]}_irqs0x{got[2][1]:x} reabove=line{got[3][0]}_irqs0x{got[3][1]:x} "
                f"w1c_above=line{got[4][0]}_irqs0x{got[4][1]:x}",
                ctl=ctl,
            )
            while mb.occ(f):
                await self._pop(m, po)
            await self._wr(m, port, "IRQS", IRQ_ALL)
            await self._wr(m, port, "IRQEN", 0)
        self._gate(True)

    async def _drain(self, m: int) -> None:
        mb = self.mbx[m]
        self.ctx = Ctx("drain", m)
        for f in ("A", "B"):
            while mb.occ(f):
                await self._pop(m, FIFO_READER[f])
        for p in ("out", "in"):
            await self._wr(m, p, "IRQS", IRQ_ALL)
            await self._wr(m, p, "IRQEN", 0)
        cc = await self._check([m], "drain")
        if self._line(cc, m, "in") or self._line(cc, m, "out"):
            self._fail(
                "CHK-LINE-IN",
                f"mbox={m} line high after the drain probe=0x{cc.probe:02x} smc=0x{cc.smc:02x}",
            )

    async def _outbound_set_leg(self) -> None:
        self.ctx = Ctx("outset", -1)
        for m in range(8):
            await self._wr(m, "out", "IRQEN", IRQ_WTIRQ)
            await self._wr(m, "out", "WIRQT", 0)
        order, k = self.set_order, self.set_k
        i = 0
        while i < 8:
            if i == k:
                for m in order[k : k + 2]:
                    await self._push(m, "out", self.set_words_out[m])
                cc = await self._check(order[k : k + 2], "outset_double")
                if self.mbx.out_count() >= 2:
                    self.seen_two = True
                i += 2
                continue
            m = order[i]
            await self._push(m, "out", self.set_words_out[m])
            cc = await self._check([m], f"outset_raise n={self.mbx.out_count()}")
            if self.mbx.out_count() >= 2:
                self.seen_two = True
            i += 1
        if cc.smc != 0xFF:
            self._fail("CHK-LINE-OUT", f"all eight outbound lines raised smc=0x{cc.smc:02x}")
        for m in order[:k]:
            await self._wr(m, "in", "IRQEN", IRQ_WTIRQ)
            await self._wr(m, "in", "WIRQT", 0)
            await self._push(m, "in", self.set_words_in[m])
            await self._check([m], "inset_raise")
        for p, m in self.set_release:
            if p == "out":
                await self._pop(m, "in")
                await self._wr(m, "out", "IRQS", IRQ_WTIRQ)
            else:
                await self._pop(m, "out")
                await self._wr(m, "in", "IRQS", IRQ_WTIRQ)
            await self._check([m], f"release {p}{m}")

    async def _end_state(self) -> None:
        self.ctx = Ctx("end", -1)
        for m in range(8):
            for p in ("out", "in"):
                st = await self._rd(m, p, "STATUS")
                exp = self.mbx[m].status(p)
                line = f"mbox={m} port={p} end_state empty={st & 1} exp_empty={exp & 1}"
                if (st & ST_EMPTY) != (exp & ST_EMPTY) or not exp & ST_EMPTY:
                    self._fail("CTL-STATUS", line)
                self.logger.info("CTL-STATUS LOG seed=%d %s", self.seed, line)
        for m in range(8):
            for p in ("out", "in"):
                await self._wr(m, p, "IRQS", IRQ_ALL)
        cc = await self._check(list(range(8)), "end_state")
        if cc.probe or cc.smc:
            self._fail("CHK-LINE-OUT", f"end state probe=0x{cc.probe:02x} smc=0x{cc.smc:02x}")

    def _width_check(self) -> None:
        """CHK-WIDTH on the DUT instance port.

        Verilator builds expose the port read-only through
        ``hw/sys/sep/dv/sep_public_scope.vlt``; an unreachable handle fails the check.
        """
        dut: Any = cocotb.top
        try:
            width = len(dut.u_dut.smc_mailbox_interrupt_o)
        except (AttributeError, TypeError) as exc:
            self._fail("CHK-WIDTH", f"u_dut.smc_mailbox_interrupt_o not reachable: {exc}")
            return
        self._grade(
            "CHK-WIDTH",
            width == EXPECTED_WIDTH,
            f"width={width} exp={EXPECTED_WIDTH} handle=u_dut.smc_mailbox_interrupt_o",
        )

    # --------------------------------------------------------------- scenario
    async def run_scenario(self) -> None:
        self.seed = self.random_seed()
        self.n_checks = 0
        self.rng = SepSeededRng(self.seed)
        self.logger.info("SEED seed=%d", self.seed)
        self._draw()
        self._gate(False)

        # Steps 1 and 2: bring-up, mailbox clock, width, one window per inbound aperture.
        await self.bring_up_no_cpu()
        await SepMbox(self).ungate_clock()
        self._quiet_axi_logs()
        self._width_check()
        self.ops = ports(self)
        self.mbx = MboxSystem()
        bank = SepFilterBank(self, "in")
        for m in range(8):
            base = inbound_base(m)
            await bank.program(
                m,
                FilterEntry(
                    start=base,
                    end=base + 0x7FF,
                    enabled=True,
                    read_allowed=True,
                    write_allowed=True,
                    allow_ns=False,
                    src_id=0,
                ),
            )
        dut: Any = cocotb.top
        self.w_in = SepBitWatch(
            dut.sep_internal_interrupts_probe_o,
            {**{f"in{m}": m for m in range(8)}, "km": KM_BIT},
        ).start()
        self.w_out = SepBitWatch(
            dut.smc_mailbox_interrupt_o, {f"o{m}": m for m in range(8)}
        ).start()
        await RisingEdge(dut.clk_i)
        await RisingEdge(dut.clk_i)
        mk_in, mk_out = self.w_in.mark(), self.w_out.mark()
        self.windows = self.windows_high = self.iso_moves = self.max_high = 0
        self.seen_all_one = self.seen_two = False
        self.prev_out = [0] * 8
        self.prev_smc = 0
        self.prev_probe = 0
        self.last_km = None
        self.ctx = Ctx("start", -1)

        # Steps 4 to 10 per mailbox, then 11 to 14.
        self._gate(True)
        for m in self.order:
            await self._threshold_leg(m)
            await self._alias_leg(m)
            await self._flush_leg(m)
            await self._gate_leg(m)
            await self._ack_leg(m)
            await self._drain(m)
        await self._outbound_set_leg()
        await self._end_state()
        self._gate(False)

        in_rises = sum(self.w_in.rises_since(mk_in, f"in{m}") for m in range(8))
        out_rises = sum(self.w_out.rises_since(mk_out, f"o{m}") for m in range(8))
        await self.w_in.stop()
        await self.w_out.stop()
        if not self.seen_two or not self.seen_all_one:
            self._ctrl_missing(
                f"CHK-LINE-OUT two_high={int(self.seen_two)} all_eight={int(self.seen_all_one)}"
            )
        if not self.windows_high or not self.iso_moves:
            self._ctrl_missing(
                f"CHK-GLITCH windows_line_high={self.windows_high} iso_moves={self.iso_moves}"
            )
        self._pass(
            "CHK-LINE-OUT",
            f"summary windows={self.windows} max_high_model={self.max_high} two_or_more_seen={int(self.seen_two)} "
            f"all_one_ok={int(self.seen_all_one)}",
        )
        self._pass(
            "CHK-GLITCH",
            f"windows={self.windows} toggles=0 windows_line_high={self.windows_high}",
        )
        self._grade(
            "CHK-NONVAC",
            in_rises > 0 and out_rises > 0,
            f"in_rises={in_rises} out_rises={out_rises}",
        )
        self.logger.info("RESULT %s seed=%d PASS checks=%d", TEST, self.seed, self.n_checks)
