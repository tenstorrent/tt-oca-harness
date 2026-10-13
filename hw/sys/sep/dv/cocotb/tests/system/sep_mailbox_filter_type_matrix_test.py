# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The mailbox consequence of the inbound filter verdict for ISS, STEE and Regular mailboxes.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense`` (``SEP_DBG``
off, so the inbound filter decides every external access).

Contract (``hw/sys/sep/doc/mailbox.adoc``, "Mailboxes", mailbox types;
``hw/ip/axi_filter/doc/index.adoc``, "Match, Then Permit", "Blocked
Transactions", "Locking a Filter Entry";
``hw/ip/axi_filter/regs/gen/adoc/filter_ctrl.adoc``, ``FILTER_CONFIG``):

* the type of a mailbox is the inbound filter entry over its inbound half. ISS
  is one entry with a non-zero ``src_id``; STEE is one entry with ``src_id``
  0; Regular is two entries with ``src_id`` 0, one per ``allow_ns`` value;
* an admitted write adds one entry to FIFO B and raises the inbound line
  (``sep_internal_interrupts_probe_o`` bit ``m``) with ``IRQEN.wtirq`` 1 and
  ``WIRQT`` 0; a blocked write adds no entry, sets no ``IRQS`` bit and raises
  no line; no other mailbox changes;
* the lock bit freezes the entry: a later ``src_id`` write leaves the old
  value, the old source ID stays admitted and the new one stays blocked.

The verdict classes of the filter are graded by the fabric tests. Here the
response of every external write is a precondition: a response that differs
from the expected one prints ``CTL-RESP FAIL`` and fails the leaf.

The external SMN master (``m_axi``) drives the inbound half; the source ID
travels on AxUSER[3:0] and the NS value on AxPROT[1] (the driver of
``sep_fabric_inbound_filter_rule_matrix_test``). The CPU-LSU master
(``s_axi``) programs the filter and pops the outbound ``READ_DATA``.

Randomization (``SepSeededRng`` from the run seed): the type of each mailbox
(each type on at least one mailbox), the ISS ``src_id`` values (1 to 15), the
``allow_ns`` values, the admit source IDs, the order of the two ``AxPROT[1]``
values of a Regular mailbox, the entry placement (lowest or highest free
index), the mailbox order, the reject source IDs, the lock mailbox and its new
``src_id``, and the data words. Every seed runs all three types, the admit of
every mailbox, the rejects of every ISS and STEE mailbox, the no-entry leg of
every mailbox and the lock leg last.

Checkers:
  CHK-ADMIT    an admitted write lands one entry (popped word equals the
               pushed word, then STATUS empty) and raises line ``m``.
  CHK-REJECT   a write with the wrong source ID or NS value lands nothing:
               0 pops, inbound IRQS 0, line ``m`` low; twin: the admit line.
  CHK-NOENTRY  with every entry over the mailbox disabled, the write lands
               nothing; IRQS read after the entries are enabled again.
  CHK-ISO-MBX  an admit changes the outbound STATUS and the inbound line of no
               other mailbox.
  CHK-LOCK     after the lock, the ``src_id`` write leaves the old value, the
               old ID is admitted and the new ID is blocked at the aperture.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles, NextTimeStep, ReadOnly, RisingEdge
from env.sep_fcov_gate import close_graded_window, open_graded_window
from env.sep_field_compare import field_compare
from env.sep_filter_model import FilterEntry
from env.sep_mbox_golden import IRQ_EIRQ, IRQ_RTIRQ, IRQ_WTIRQ, ST_EMPTY
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_csr_bank_seq import F_SRC_ID_LSB, FILTER_CFG_LO_FIELDS
from seq_lib.sep_fabric_filter_bank_seq import SRC_ID_MASK, SepFilterBank, config_word
from seq_lib.sep_inbound_filter_rule_seq import SepInboundFilter
from seq_lib.sep_mailbox_iface_seq import SepMbox
from seq_lib.sep_mbox_port_ops import (
    MAILBOX_COUNT,
    RESP_DECERR,
    RESP_OKAY,
    SepMboxPortOps,
    port_base,
    resp_name,
)

TEST = "sep_mailbox_filter_type_matrix_test"
TYPES = ("ISS", "STEE", "REG")
IRQ_FIELDS = IRQ_WTIRQ | IRQ_RTIRQ | IRQ_EIRQ
# Clocks of a quiet window: no access to the mailbox unit, then the probe sample.
QUIET = 32
# Upper bound of pops in one quiesce (FIFO depth plus margin).
DRAIN_BOUND = 12
SRC_ID_FIELD = SRC_ID_MASK << F_SRC_ID_LSB


class _Mbx:
    """Plan of one mailbox: type, entries and the attributes of its accesses."""

    def __init__(self, m: int, kind: str) -> None:
        self.m = m
        self.kind = kind
        self.src_id = 0  # entry src_id (ISS only non-zero)
        self.allow_ns = 0  # ISS and STEE
        self.admit_user = 0  # source ID of an admitted access
        self.prot_order: list[int] = []  # AxPROT[1] of each admit draw
        self.entries: list[int] = []  # inbound filter entry indexes
        self.place_high = False
        self.rejects: list[tuple[str, int, int]] = []  # (what, user, prot1)
        self.words: list[int] = []

    @property
    def start(self) -> int:
        return port_base(self.m, "in")

    @property
    def end(self) -> int:
        return port_base(self.m, "in") + 0x7FF

    def summary(self) -> str:
        rej = ",".join(f"{w}:u{u}/p{p}" for w, u, p in self.rejects) or "-"
        return (
            f"mbox={self.m} type={self.kind} src_id={self.src_id} allow_ns={self.allow_ns} "
            f"admit_user={self.admit_user} prots={','.join(map(str, self.prot_order))} "
            f"entries={','.join(map(str, self.entries))} place={'high' if self.place_high else 'low'} "
            f"rejects={rej} words=" + ",".join(f"0x{w:016x}" for w in self.words)
        )


class _Cfg:
    """Seed-drawn plan of the leaf."""

    def __init__(self, seed: int, n_entries: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        kinds = list(TYPES) + [rng.choice(TYPES) for _ in range(MAILBOX_COUNT - len(TYPES))]
        rng.shuffle(kinds)
        self.mbx = [_Mbx(m, k) for m, k in enumerate(kinds)]
        self.order = list(range(MAILBOX_COUNT))
        rng.shuffle(self.order)
        free = list(range(n_entries))
        for m in self.order:
            b = self.mbx[m]
            b.place_high = bool(rng.getrandbits(1))
            n = 2 if b.kind == "REG" else 1
            for _ in range(n):
                b.entries.append(free.pop(-1 if b.place_high else 0))
            if b.kind == "ISS":
                b.src_id = rng.randrange(1, 16)
                b.allow_ns = rng.getrandbits(1)
                b.admit_user = b.src_id
                b.prot_order = [b.allow_ns]
                wrong = rng.choice([u for u in range(16) if u != b.src_id])
                b.rejects = [("src", wrong, b.allow_ns), ("ns", b.src_id, 1 - b.allow_ns)]
            elif b.kind == "STEE":
                b.allow_ns = rng.getrandbits(1)
                b.admit_user = rng.randrange(16)
                b.prot_order = [b.allow_ns]
                b.rejects = [("ns", b.admit_user, 1 - b.allow_ns)]
            else:
                b.admit_user = rng.randrange(16)
                first = rng.getrandbits(1)
                b.prot_order = [first, 1 - first]
            # Data words: one per admit, one per reject, one for the no-entry leg,
            # two for the lock leg.
            n_words = len(b.prot_order) + len(b.rejects) + 3
            b.words = [rng.getrandbits(64) | 1 for _ in range(n_words)]
        iss = [b.m for b in self.mbx if b.kind == "ISS"]
        self.lock_m = rng.choice(iss)
        old = self.mbx[self.lock_m].src_id
        self.lock_new = rng.choice([s for s in range(1, 16) if s != old])

    def draw_lines(self) -> list[str]:
        out = [
            f"order={','.join(map(str, self.order))}",
            f"types={','.join(b.kind for b in self.mbx)}",
            f"lock_mbox={self.lock_m} lock_new_src_id={self.lock_new}",
        ]
        out += [b.summary() for b in self.mbx]
        return out


@pyuvm.test()
class sep_mailbox_filter_type_matrix_test(sep_base_test):
    """ISS, STEE and Regular mailboxes: admit, reject, no entry, isolation and the lock."""

    required_evidence = ("CHK-ADMIT", "CHK-REJECT", "CHK-NOENTRY", "CHK-ISO-MBX", "CHK-LOCK")

    # ---- log helpers ---------------------------------------------------------
    def _pass(self, chk: str, line: str) -> None:
        self.logger.info("%s PASS seed=%d %s", chk, self.c.seed, line)
        self.n_checks += 1
        self.counts[chk] = self.counts.get(chk, 0) + 1

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.c.seed} {line}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _ctl_resp(self, what: str, got: int, want: int) -> None:
        line = f"seed={self.c.seed} {what} resp={resp_name(got)} expect={resp_name(want)}"
        if got != want:
            msg = f"CTL-RESP FAIL {line}"
            self.logger.error(msg)
            raise AssertionError(msg)
        self.logger.info("CTL-RESP LOG %s", line)

    # ---- DUT observation -----------------------------------------------------
    async def _lines(self) -> int:
        """Probe bits [7:0] after one clock edge (each bit must be 0 or 1)."""
        await RisingEdge(cocotb.top.clk_i)
        await ReadOnly()
        v = self.rd_known(cocotb.top.sep_internal_interrupts_probe_o, 0xFF) & 0xFF
        await NextTimeStep()
        return v

    async def _quiet(self) -> int:
        await ClockCycles(cocotb.top.clk_i, QUIET)
        return await self._lines()

    # ---- accesses ------------------------------------------------------------
    async def _ext_wr(self, b: _Mbx, reg: str, value: int, *, user: int, prot1: int, want: int):
        resp = await self.ops[b.m].wr("in", reg, value, user=user, prot1=prot1)
        self._ctl_resp(f"mbox={b.m} in {reg}=0x{value:x} user={user} prot1={prot1}", resp, want)
        return resp

    async def _ext_push(self, b: _Mbx, data: int, *, user: int, prot1: int, want: int) -> int:
        resp = await self.ops[b.m].push("in", data, user=user, prot1=prot1)
        self._ctl_resp(f"mbox={b.m} in WRITE_DATA user={user} prot1={prot1}", resp, want)
        return resp

    async def _ext_irqs(self, b: _Mbx) -> int:
        resp, v = await self.ops[b.m].rd("in", "IRQS", user=b.admit_user, prot1=b.prot_order[0])
        self._ctl_resp(f"mbox={b.m} in IRQS read", resp, RESP_OKAY)
        return v

    async def _out_status(self, m: int) -> int:
        return await self.ops[m].rd_ok("out", "STATUS")

    async def _drain(self, b: _Mbx) -> list[int]:
        """Pop the outbound READ_DATA until STATUS reads empty; returns the popped words."""
        words: list[int] = []
        for _ in range(DRAIN_BOUND):
            st = await self._out_status(b.m)
            if st & ST_EMPTY:
                return words
            resp, data = await self.ops[b.m].pop("out")
            if resp != RESP_OKAY:
                raise AssertionError(
                    f"MBX-SETUP FAIL: mailbox {b.m} out pop answered {resp_name(resp)} "
                    f"with STATUS=0x{st:x} not empty"
                )
            words.append(data)
        raise AssertionError(f"MBX-SETUP FAIL: mailbox {b.m} not empty after {DRAIN_BOUND} pops")

    async def _quiesce(self, b: _Mbx) -> int:
        """Drain, then clear the inbound IRQS with an admitted access; returns the pop count."""
        n = len(await self._drain(b))
        await self._ext_wr(
            b, "IRQS", IRQ_FIELDS, user=b.admit_user, prot1=b.prot_order[0], want=RESP_OKAY
        )
        return n

    # ---- legs ----------------------------------------------------------------
    async def _program(self) -> None:
        for m in self.c.order:
            b = self.c.mbx[m]
            if b.kind == "REG":
                ns_vals = [0, 1]
            else:
                ns_vals = [b.allow_ns]
            for idx, ns in zip(b.entries, ns_vals):
                e = FilterEntry(
                    start=b.start,
                    end=b.end,
                    enabled=True,
                    read_allowed=True,
                    write_allowed=True,
                    allow_ns=bool(ns),
                    allow_burst=False,
                    src_id=b.src_id,
                )
                await self.bank.program(idx, e)
        for m in self.c.order:
            b = self.c.mbx[m]
            for reg, v in (("IRQEN", IRQ_WTIRQ), ("WIRQT", 0)):
                await self._ext_wr(
                    b, reg, v, user=b.admit_user, prot1=b.prot_order[0], want=RESP_OKAY
                )

    async def _admit(self, b: _Mbx, prot1: int, word: int) -> None:
        await self._quiesce(b)
        others = [m for m in range(MAILBOX_COUNT) if m != b.m]
        before = {m: await self._out_status(m) for m in others}
        await self._ext_push(b, word, user=b.admit_user, prot1=prot1, want=RESP_OKAY)
        lines = await self._quiet()
        line_m = (lines >> b.m) & 1
        st = await self._out_status(b.m)
        after = {m: await self._out_status(m) for m in others}
        others_lines = lines & ~(1 << b.m) & 0xFF
        same = sum(1 for m in others if after[m] == before[m] and after[m] & ST_EMPTY)
        popped = await self._drain(b)
        occ = len(popped)
        pop = popped[0] if popped else None
        self.twin_line[b.m] = line_m
        pop_s = "none" if pop is None else f"0x{pop:016x}"
        line = (
            f"mbox={b.m} type={b.kind} src={b.admit_user} prot1={prot1} occ={occ} "
            f"pop={pop_s} exp=0x{word:016x} line={line_m} ctl_resp=OKAY "
            f"status_before_pop=0x{st:x}"
        )
        if occ != 1 or pop != word or line_m != 1 or st & ST_EMPTY:
            self._fail("CHK-ADMIT", line)
        self._pass("CHK-ADMIT", line)
        iso = (
            f"admitted={b.m} admitted_line={line_m} others_status_same={same} "
            f"others_lines=0x{others_lines:02x} others_status="
            + ",".join(f"{m}:0x{after[m]:x}" for m in others)
        )
        if same != len(others) or others_lines != 0 or line_m != 1:
            self._fail("CHK-ISO-MBX", iso)
        self._pass("CHK-ISO-MBX", iso)

    async def _reject(self, b: _Mbx, what: str, user: int, prot1: int, word: int) -> None:
        await self._quiesce(b)
        await self._ext_push(b, word, user=user, prot1=prot1, want=RESP_DECERR)
        lines = await self._quiet()
        line_m = (lines >> b.m) & 1
        st = await self._out_status(b.m)
        occ = len(await self._drain(b))
        irqs = await self._ext_irqs(b)
        fc = field_compare(irqs, 0, IRQ_FIELDS)
        twin = self.twin_line[b.m]
        line = (
            f"mbox={b.m} type={b.kind} kind={what} src={user} prot1={prot1} "
            f"entry_src={b.src_id} allow_ns={b.allow_ns} ctl_resp=DECERR occ={occ} "
            f"status=0x{st:x} irqs=0x{irqs & IRQ_FIELDS:x} line={line_m} twin_line={twin} "
            f"irqs[{fc.fields()}]"
        )
        if occ != 0 or not fc.ok or line_m != 0 or not st & ST_EMPTY:
            self._fail("CHK-REJECT", line)
        if twin != 1:
            self._fail("CHK-REJECT", line + " twin admit line not high")
        self._pass("CHK-REJECT", line)

    async def _no_entry(self, b: _Mbx, word: int) -> None:
        await self._quiesce(b)
        for idx in b.entries:
            await self.bank.set_enabled(idx, False)
        enabled = sum(1 for idx in b.entries if self.bank.model.entries[idx].enabled)
        await self._ext_push(b, word, user=b.admit_user, prot1=b.prot_order[0], want=RESP_DECERR)
        lines = await self._quiet()
        line_m = (lines >> b.m) & 1
        occ = len(await self._drain(b))
        for idx in b.entries:
            await self.bank.set_enabled(idx, True)
        irqs = await self._ext_irqs(b)
        fc = field_compare(irqs, 0, IRQ_FIELDS)
        twin = self.twin_line[b.m]
        line = (
            f"mbox={b.m} type={b.kind} enabled_entries={enabled} ctl_resp=DECERR occ={occ} "
            f"irqs=0x{irqs & IRQ_FIELDS:x} line={line_m} twin_line={twin} irqs[{fc.fields()}]"
        )
        if occ != 0 or not fc.ok or line_m != 0 or twin != 1:
            self._fail("CHK-NOENTRY", line)
        self._pass("CHK-NOENTRY", line)

    async def _lock(self) -> None:
        c = self.c
        b = c.mbx[c.lock_m]
        idx = b.entries[0]
        await self._quiesce(b)
        await self.infilt.lock_entry(idx)
        cfg_addr = self.bank.cfg_addr(idx)
        new_lo = (config_word(self.bank.model.entries[idx]) & ~SRC_ID_FIELD) | (
            c.lock_new << F_SRC_ID_LSB
        )
        wr_resp = await self.infilt.write_tolerant(cfg_addr, new_lo)
        self._ctl_resp(
            f"mbox={b.m} FILTER_CONFIG[{idx}] src_id={c.lock_new} locked", wr_resp, RESP_DECERR
        )
        cfg_lo = await self.infilt.read_cpu(cfg_addr)
        cfg_hi = await self.infilt.read_cpu(cfg_addr + 4)
        src_after = (cfg_lo >> F_SRC_ID_LSB) & SRC_ID_MASK
        old_w, new_w = b.words[-2], b.words[-1]
        old_resp = await self._ext_push(b, old_w, user=b.src_id, prot1=b.allow_ns, want=RESP_OKAY)
        old_line = (await self._quiet() >> b.m) & 1
        old_occ = await self._quiesce(b)
        new_resp = await self._ext_push(
            b, new_w, user=c.lock_new, prot1=b.allow_ns, want=RESP_DECERR
        )
        new_line = (await self._quiet() >> b.m) & 1
        new_occ = len(await self._drain(b))
        line = (
            f"mbox={b.m} entry={idx} old_id={b.src_id} new_id={c.lock_new} "
            f"cfg_write_resp={resp_name(wr_resp)} cfg_src_after={src_after} "
            f"cfg_lo=0x{cfg_lo & FILTER_CFG_LO_FIELDS:08x} cfg_hi=0x{cfg_hi:08x} "
            f"old_resp={resp_name(old_resp)} old_line={old_line} old_occ={old_occ} "
            f"new_resp={resp_name(new_resp)} new_line={new_line} new_occ={new_occ}"
        )
        ok = (
            src_after == b.src_id
            and old_line == 1
            and old_occ == 1
            and new_line == 0
            and new_occ == 0
        )
        if not ok:
            self._fail("CHK-LOCK", line)
        self._pass("CHK-LOCK", line)

    # ---- scenario ------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.bank = SepFilterBank(self, "in")
        self.c = c = _Cfg(seed, self.bank.n)
        self.n_checks = 0
        self.counts: dict[str, int] = {}
        self.twin_line = [0] * MAILBOX_COUNT
        self.logger.info("SEED seed=%d", seed)
        for d in c.draw_lines():
            self.logger.info("DRAW %s", d)
        self.ops = [SepMboxPortOps(self, m) for m in range(MAILBOX_COUNT)]
        self.infilt = SepInboundFilter(self)
        await SepMbox(self).ungate_clock()
        await self._program()

        open_graded_window(TEST, self.logger)
        for m in c.order:
            b = c.mbx[m]
            w = iter(b.words)
            for prot1 in b.prot_order:
                await self._admit(b, prot1, next(w))
            for what, user, prot1 in b.rejects:
                await self._reject(b, what, user, prot1, next(w))
            await self._no_entry(b, next(w))
        await self._lock()
        close_graded_window(self.logger)

        n_admit = sum(len(b.prot_order) for b in c.mbx)
        expect = {
            "CHK-ADMIT": n_admit,
            "CHK-ISO-MBX": n_admit,
            "CHK-REJECT": sum(len(b.rejects) for b in c.mbx),
            "CHK-NOENTRY": MAILBOX_COUNT,
            "CHK-LOCK": 1,
        }
        if any(self.counts.get(k, 0) != v for k, v in expect.items()):
            raise AssertionError(f"CHK-COUNT FAIL seed={seed} counts={self.counts} expect={expect}")
        self.result_pass(TEST, seed, self.n_checks, f" counts={self.counts}")
