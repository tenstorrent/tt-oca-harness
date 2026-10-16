# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Three initiators toward the outbound port under randomized target delays.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``. RANDCFG.

Contract (``hw/sys/sep/doc/fabric.adoc``, "Fabric Topology", "Transaction
Routing", "Filtering and Protection"; ``hw/sys/sep/doc/cpu.adoc``, LSU master
and AxPROT table; ``hw/sys/sep/doc/dma.adoc``, master path; the issue text for
concurrent initiators toward a stalling outbound target): the CPU LSU (the TB
master on ``s_axi``), the Secure DMA (programmed over that master) and the SMN
inbound master (``m_axi``, through the inbound filter) each issue to one
outbound window, singly and at the same time, while the responder
(``tb/sep_outbound_mbx.sv``) stalls AW, W and AR READY and holds B and R VALID
from a seeded stream.

Each initiator owns a slot of the outbound page, so a PR-OUT request is
attributed to its initiator by address; the responder answers in request
order, so a PR-OUT-RSP beat is attributed to the initiator of the request it
answers by order. The responder returns ``{~a, a}`` as read data
(``smn_outbound_rd_addr_data_i``), so every read carries data of its own
address. The seed draws the delay profile, the AxUSER of the LSU and of the
System Interface, the transaction counts, the start offsets, the read and
write mix and the burst length.

The SMN inbound master has no route to the outbound port:
``hw/sys/sep/doc/fabric.adoc`` (Routing) states that the peripheral crossbar
answers any inbound address at or above ``0x4000_0000`` with DECERR, and the
outbound window lies above it. Every access that master issues, in every phase,
is stimulus of the one no-path check CHK-SYSIF-NO-OUTBOUND-PATH; no other
checker counts it.

Open findings are printed as measured and never compared: the order of same-ID
write responses (SF-007), the completion latency (SF-004), the outbound ID
encoding (SF-008) and the acceptance point of a request the filters answer
themselves (SF-015).

Checkers (printed as ``CHK-<NAME>: <fields>`` after the exact comparison):
  CHK-LSU-PATH, CHK-DMA-PATH
                    the LSU and the DMA alone: one request per access at
                    PR-OUT, AxLEN 0 for a single beat, one B or ARLEN+1 R
                    beats with RLAST on the last, DMA STATUS DONE then cleared.
  CHK-SYSIF-NO-OUTBOUND-PATH
                    every single and burst access of the SMN inbound master
                    answers DECERR with one B or its R beats, RLAST on the
                    last, and none reaches PR-OUT.
  CHK-CONC-ALL      every transaction of every initiator completes in the
                    write, read, mixed and pair phases.
  CHK-ID-ORDER      same-ID reads come back in the PR-OUT-RSP order.
  CHK-B-COUNT, CHK-R-COUNT
                    exactly one B per accepted write, exactly its beats per
                    accepted read, and none after the idle window.
  CHK-RESP-ROUTE    every response reaches the initiator that issued it.
  CHK-ATTR-USER, CHK-ATTR-PROT, CHK-ATTR-ID-DISTINCT
                    AxUSER, AxPROT and ID of every PR-OUT request per initiator.
  CHK-NONVAC        the ordered fence of the phases.
  CHK-TIMEOUT-PATHS the bound of each wait.
"""

from __future__ import annotations

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from env.sep_fabric_tap import SepFabricTap
from env.sep_filter_model import FilterEntry
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, sym
from seq_lib.sep_dma_ops import _D
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_outbound_contention_seq import (
    INITS,
    MAGIC_WORDS,
    RESP_OKAY,
    DmaJob,
    Layout,
    OutboundTraffic,
    PinWatch,
    PortStall,
    ResponderDelay,
    Txn,
    id_overlap,
    port_view,
    r_word,
    run_all,
)

TEST = "sep_outbound_contention_rand_test"

SMU_BASE = SEP_CPU_CTRL.reset("SMU_GLOBAL_BASE_ADDR")
PAGE = SMU_BASE + 0x0002_0000
SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
DMA_DST = SRAM_BASE + 0x0003_0000
DMA_SRC = DMA_DST + 0x100
ASID_RESET = _D.reset32("ADDR_SPACE_ID")
OUT_ENTRY = 4
IN_ENTRY = 0
LSU_PROT = 0b001
SYS_PROT = 0b000
DMA_PROT = 0b001
DMA_USER = 0
IDLE_CLOCKS = 256
RESP_DECERR = 3
DMA_STAGE_BYTES = 0x100

FENCE = (
    "BRINGUP_DONE",
    "LSU_SINGLES",
    "DMA_SINGLES",
    "SYSIF_SINGLES",
    "SYSIF_BURSTS",
    "WRITES_3WAY",
    "READS_3WAY",
    "MIX_3WAY",
    "PAIRS",
    "ID_ORDER",
    "ATTR_AND_IDLE",
)
CHECKS = (
    "CHK-LSU-PATH",
    "CHK-DMA-PATH",
    "CHK-SYSIF-NO-OUTBOUND-PATH",
    "CHK-CONC-ALL",
    "CHK-ID-ORDER",
    "CHK-B-COUNT",
    "CHK-R-COUNT",
    "CHK-RESP-ROUTE",
    "CHK-ATTR-USER",
    "CHK-ATTR-PROT",
    "CHK-ATTR-ID-DISTINCT",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


class _Cfg:
    """The seed-drawn knobs."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.lsu_user = rng.randrange(1, 16)
        self.sys_user = rng.choice([u for u in range(1, 16) if u != self.lsu_user])
        self.p_stall = (rng.randrange(0, 41), rng.randrange(0, 41), rng.randrange(0, 41))
        self.p_hold = rng.randrange(0, 9)
        self.hold_max = rng.randrange(2, 25)
        self.n_single = rng.randrange(3, 7)
        self.n_sys_single = rng.randrange(3, 7)
        self.burst_max = rng.randrange(3, 9)
        self.n_bursts = rng.randrange(2, 4)
        self.n_conc = rng.randrange(2, 5)
        self.n_dma_jobs = rng.randrange(1, 3)
        self.offset_max = rng.randrange(8, 49)
        self.same_id_n = rng.randrange(3, 6)
        self.same_id = rng.randrange(1, 8)

    def delays(self) -> str:
        return (
            f"aw{self.p_stall[0]}/w{self.p_stall[1]}/ar{self.p_stall[2]}"
            f"/hold{self.p_hold}x{self.hold_max}"
        )

    def draw_lines(self) -> list[str]:
        return [
            f"lsu_user={self.lsu_user} lsu_prot=0b{LSU_PROT:03b}",
            f"sysif_user={self.sys_user} sysif_prot=0b{SYS_PROT:03b}",
            f"ready_stall_percent aw={self.p_stall[0]} w={self.p_stall[1]} ar={self.p_stall[2]}",
            f"resp_hold_percent={self.p_hold} hold_max_clocks={self.hold_max}",
            f"singles lsu={self.n_single} sysif={self.n_sys_single}",
            f"bursts count={self.n_bursts} max_beats={self.burst_max}",
            f"concurrent per_initiator={self.n_conc} dma_jobs={self.n_dma_jobs}",
            f"start_offset_max_clocks={self.offset_max}",
            f"same_id={self.same_id} outstanding={self.same_id_n}",
        ]


def _setfmt(vals) -> str:
    return "{" + ",".join(str(v) for v in sorted(set(vals))) + "}"


def _listfmt(vals) -> str:
    return "[" + ",".join(str(v) for v in vals) + "]"


@pyuvm.test()
class sep_outbound_contention_rand_test(sep_base_test):
    """LSU, Secure DMA and SMN inbound master toward the outbound port, singly and together."""

    required_evidence = CHECKS

    # ---- log helpers ---------------------------------------------------------
    def _emit(self, chk: str, line: str) -> None:
        self.logger.info("%s: %s", chk, line)
        self.logger.info("%s PASS: compared as stated seed=%d", chk, self.c.seed)

    def _obs_row(self, tag: str, line: str) -> None:
        self.logger.info("OBS-%s: %s", tag, line)

    def _fail(self, chk: str, line: str) -> None:
        msg = f"{chk} FAIL seed={self.c.seed} {line} last_port_state={self._port_state()}"
        self.logger.error(msg)
        raise AssertionError(msg)

    def _fence(self, term: str) -> None:
        self.fence_seen.append(term)
        self.logger.info(
            "CHK-NONVAC: fence=%s index=%d seed=%d", term, len(self.fence_seen), self.c.seed
        )

    def _port_state(self) -> str:
        def n(tap, ch):
            return sum(1 for b in tap.beats if b.ch == ch)

        return (
            f"PR-OUT aw={n(self.out, 'aw')} w={n(self.out, 'w')} ar={n(self.out, 'ar')} "
            f"PR-OUT-RSP b={n(self.rsp, 'b')} r={n(self.rsp, 'r')}"
        )

    def _wait_bound(self, kind: str, bound: str) -> None:
        if kind in self.waits_logged:
            return
        self.waits_logged.add(kind)
        self.logger.info(
            "CHK-TIMEOUT-PATHS: wait=%s bound=%s on_expiry=fail_with_initiator_txn_and_last_port_state "
            "last_port_state=%s",
            kind,
            bound,
            self._port_state(),
        )

    # ---- stimulus builders -----------------------------------------------------
    def _words(self, n: int) -> list[int]:
        out = []
        while len(out) < n:
            w = self.rng.getrandbits(32)
            if w not in MAGIC_WORDS:
                out.append(w)
        return out

    def _txn(self, init: str, op: str, *, beats: int = 1, axi_id: int | None = None) -> Txn:
        c = self.c
        self.n_made += 1
        if axi_id is None:
            axi_id = self.rng.randrange(1, 8)
        wdata = b""
        if op == "wr":
            wdata = b"".join(w.to_bytes(4, "little") for w in self._words(2 * beats))
        return Txn(
            init=init,
            op=op,
            addr=self.layout.alloc(init, 8 * beats),
            beats=beats,
            axi_id=axi_id,
            user=c.lsu_user if init == "lsu" else c.sys_user,
            prot=LSU_PROT if init == "lsu" else SYS_PROT,
            wdata=wdata,
            name=f"{init}_{op}_{self.n_made}",
        )

    def _job(self, write: bool) -> DmaJob:
        self.n_jobs += 1
        slot = (self.n_jobs * 16) % DMA_STAGE_BYTES
        mem = (DMA_SRC if write else DMA_DST) + slot
        return DmaJob(
            write=write,
            words=1,
            out_addr=self.layout.alloc("dma", 4),
            mem_addr=mem,
            data=self._words(1) if write else [],
            name=f"dma_{'wr' if write else 'rd'}_{self.n_jobs}",
        )

    def _ops(self, kind: str, n: int) -> list[str]:
        if kind == "w":
            return ["wr"] * n
        if kind == "r":
            return ["rd"] * n
        ops = [self.rng.choice(["wr", "rd"]) for _ in range(n)]
        if len(set(ops)) == 1 and n > 1:
            ops[-1] = "rd" if ops[0] == "wr" else "wr"
        return ops

    def _plan(self, kind: str, inits) -> dict:
        plan: dict = {}
        for init in inits:
            if init == "dma":
                plan[init] = [self._job(op == "wr") for op in self._ops(kind, self.c.n_dma_jobs)]
            else:
                plan[init] = [self._txn(init, op) for op in self._ops(kind, self.c.n_conc)]
        return plan

    # ---- set-up --------------------------------------------------------------------
    async def _program_filters(self) -> None:
        c = self.c
        self.ibank = SepFilterBank(self, "in")
        self.obank = SepFilterBank(self, "out")
        await self.obank.program(
            OUT_ENTRY,
            FilterEntry(
                start=PAGE,
                end=PAGE + 0xFFF,
                enabled=True,
                read_allowed=True,
                write_allowed=True,
                allow_ns=False,
                allow_burst=True,
                src_id=0,
            ),
        )
        await self.ibank.program(
            IN_ENTRY,
            FilterEntry(
                start=PAGE,
                end=PAGE + 0xFFF,
                enabled=True,
                read_allowed=True,
                write_allowed=True,
                allow_ns=False,
                allow_burst=True,
                src_id=c.sys_user,
            ),
        )
        await self.tr.dma.program_range(0x0, 0xFFFF_FFFF, valid=True)
        await self.tr.dma.wr(_D.addr("ADDR_SPACE_ID"), ASID_RESET)
        self.logger.info(
            "SETUP outbound_entry=%d inbound_entry=%d page=0x%x lsu_user=%d sysif_user=%d",
            OUT_ENTRY,
            IN_ENTRY,
            PAGE,
            c.lsu_user,
            c.sys_user,
        )

    def _dump(self, name: str, marks) -> None:
        """The PR-OUT, PR-OUT-RSP and TB-master handshakes of a phase that did not complete."""
        for tap, mark in ((self.out, marks[0]), (self.rsp, marks[1])):
            for b in tap.beats[mark:]:
                self.logger.info("DUMP phase=%s tap=%s t_ps=%d %s", name, tap.name, b.t_ps, b.fmt())
        for pw, mark in ((self.pin_s, marks[2]), (self.pin_m, marks[3])):
            for k, label in enumerate(("aw", "b", "ar", "r")):
                for x in getattr(pw, label)[mark[k] :]:
                    self.logger.info("DUMP phase=%s bus=%s %s %s", name, pw.bus, label, x)

    def _stall_str(self) -> str:
        """Measured VALID-without-READY clocks at PR-OUT and hold clocks since the phase began."""
        s0, h0 = self._stall0
        s1 = self.pstall.snap()
        return (
            f"port_stall_aw={s1['aw'] - s0['aw']} port_stall_w={s1['w'] - s0['w']} "
            f"port_stall_ar={s1['ar'] - s0['ar']} hold_clocks={self.delay.hold_clocks - h0}"
        )

    def _marks(self):
        return (self.out.mark(), self.rsp.mark(), self.pin_s.mark(), self.pin_m.mark())

    # ---- one phase -------------------------------------------------------------------
    async def _init_task(self, init, items, *, serial: bool, spread: int, watch) -> None:
        rng = self.rng
        if init == "dma":
            for k, job in enumerate(items):
                if k:
                    await self.tr.dma_prepare(job)
                delay = rng.randrange(0, spread + 1) if (k == 0 and spread) else 0
                await self.tr.dma_run(job, delay=delay)
                await self.tr.dma_finish(job)
            return
        if serial:
            for t in items:
                delay = rng.randrange(0, spread + 1) if spread else 0
                await self.tr.run_txn(t, delay=delay, watch=watch)
            return
        coros = [
            self.tr.run_txn(t, delay=(rng.randrange(0, spread + 1) if spread else 0), watch=watch)
            for t in items
        ]
        await run_all(coros)

    async def _run_phase(self, name: str, plan: dict, *, serial: bool = False, spread=None):
        spread = self.c.offset_max if spread is None else spread
        self._wait_bound("txn", f"axi_timeout_ns={self.tr.timeout_ns}")
        self._wait_bound(
            "dma_done", f"status_polls={self.tr.dma.done_bound(4)} (size scaled, one word)"
        )
        marks = self._marks()
        self._stall0 = (self.pstall.snap(), self.delay.hold_clocks)
        jobs = plan.get("dma", [])
        if jobs:
            await self.tr.dma_prepare(jobs[0])
        coros = []
        for init in INITS:
            if init not in plan:
                continue
            watch = self.pin_s if init == "lsu" else self.pin_m
            coros.append(
                self._init_task(init, plan[init], serial=serial, spread=spread, watch=watch)
            )
        try:
            await run_all(coros)
        except AssertionError:
            self._dump(name, marks)
            raise
        await ClockCycles(self.dut_clk, 4)
        view = port_view(self.layout, self.out.since(marks[0]), self.rsp.since(marks[1]))
        return view, marks

    # ---- accounting ---------------------------------------------------------------------
    def _account(self, name: str, plan: dict, view, marks) -> dict:
        """Exact comparison of one phase; returns the counts it graded.

        The SMN inbound accesses of the phase are graded here by their no-path
        form only: DECERR at the master, nothing at PR-OUT.
        """
        pins = {"lsu": self.pin_s.since(marks[2]), "sysif": self.pin_m.since(marks[3])}
        st: dict = {}
        if view.unknown:
            self._fail("CHK-ACCOUNT", f"phase={name} x_or_z_beats={view.unknown}")
        for init in ("lsu", "sysif"):
            txns = plan.get(init, [])
            wr = [t for t in txns if t.op == "wr"]
            rd = [t for t in txns if t.op == "rd"]
            p = pins[init]
            acc_wr = wr if init == "lsu" else [t for t in wr if t.resp == RESP_OKAY]
            acc_rd = rd if init == "lsu" else [t for t in rd if t.resp == RESP_OKAY]
            s = {
                "wr": len(wr),
                "rd": len(rd),
                "acc_wr": len(acc_wr),
                "acc_rd": len(acc_rd),
                "aw": view.n_req(init, "wr"),
                "ar": view.n_req(init, "rd"),
                "w": view.w_by_init[init],
                "b_port": view.b_by_init[init],
                "r_port": view.r_beats_by_init[init],
                "b_master": p["b"],
                "r_master": p["r"],
                "rlast": p["rlast"],
                "r_master_beats": sum(len(t.words) for t in rd),
                "self_wr": len(wr) - len(acc_wr),
                "self_rd": len(rd) - len(acc_rd),
                "self_rd_beats": sum(len(t.words) for t in rd if t.resp != RESP_OKAY),
                "lens_w": view.lens(init, "wr"),
                "lens_r": view.lens(init, "rd"),
            }
            st[init] = s
            if not txns:
                continue
            if init == "lsu":
                bad = [t for t in txns if t.resp != RESP_OKAY]
                if bad:
                    self._fail(
                        "CHK-ACCOUNT",
                        f"phase={name} init=lsu non_okay txn={bad[0].name} resp={bad[0].resp}",
                    )
            else:
                chk = "CHK-SYSIF-NO-OUTBOUND-PATH"
                ctx = f"phase={name} init=sysif"
                if s["aw"] + s["ar"]:
                    self._fail(chk, f"{ctx} request reached PR-OUT aw={s['aw']} ar={s['ar']}")
                notdec = [t for t in txns if t.resp != RESP_DECERR]
                if notdec:
                    self._fail(
                        chk,
                        f"{ctx} answered {len(txns) - len(notdec)} of {len(txns)} with DECERR; "
                        f"first other txn={notdec[0].name} resp={notdec[0].resp}",
                    )
                if s["b_master"] != len(wr):
                    self._fail(chk, f"{ctx} B at master {s['b_master']} != {len(wr)}")
                beats = sum(t.beats for t in rd)
                if s["r_master"] != beats or s["rlast"] != len(rd):
                    self._fail(
                        chk, f"{ctx} R beats {s['r_master']}/{beats} rlast {s['rlast']}/{len(rd)}"
                    )
                short = [t for t in rd if len(t.words) != t.beats]
                if short:
                    self._fail(
                        chk,
                        f"{ctx} read txn={short[0].name} returned {len(short[0].words)} beats "
                        f"for {short[0].beats}",
                    )
                n = self.sys_neg
                n["issued"] += len(txns)
                n["decerr"] += len(txns) - len(notdec)
                n["writes"] += len(wr)
                n["reads"] += len(rd)
                n["beats"] += beats
                continue
            ctx = f"phase={name} init={init}"
            if view.addrs(init, "wr") != sorted(t.addr for t in acc_wr):
                self._fail("CHK-ACCOUNT", f"{ctx} write request missing or seen twice at PR-OUT")
            if view.addrs(init, "rd") != sorted(t.addr for t in acc_rd):
                self._fail("CHK-ACCOUNT", f"{ctx} read request missing or seen twice at PR-OUT")
            single_w = [t for t in acc_wr if t.beats == 1]
            if any(v != 0 for v in s["lens_w"]) and len(single_w) == len(acc_wr):
                self._fail("CHK-ACCOUNT", f"{ctx} AxLEN not 0 on AW {s['lens_w']}")
            if any(v != 0 for v in s["lens_r"]) and all(t.beats == 1 for t in acc_rd):
                self._fail("CHK-ACCOUNT", f"{ctx} AxLEN not 0 on AR {s['lens_r']}")
            if s["w"] != view.req_beats(init, "wr"):
                self._fail("CHK-ACCOUNT", f"{ctx} W beats {s['w']} != AW beats")
            if init == "lsu" and s["w"] != len(acc_wr):
                self._fail("CHK-ACCOUNT", f"{ctx} W beats {s['w']} != writes {len(acc_wr)}")
            if s["b_master"] != len(wr):
                self._fail("CHK-ACCOUNT", f"{ctx} B at master {s['b_master']} != writes {len(wr)}")
            if s["b_port"] != len(acc_wr):
                self._fail(
                    "CHK-ACCOUNT", f"{ctx} B at port {s['b_port']} != accepted {len(acc_wr)}"
                )
            if s["r_master"] != s["r_master_beats"]:
                self._fail(
                    "CHK-ACCOUNT",
                    f"{ctx} R beats at master {s['r_master']} != beats returned "
                    f"{s['r_master_beats']}",
                )
            if s["rlast"] != len(rd):
                self._fail("CHK-ACCOUNT", f"{ctx} RLAST count {s['rlast']} != reads {len(rd)}")
            want_r = sum(t.beats for t in acc_rd) if init == "lsu" else view.req_beats(init, "rd")
            if s["r_port"] != want_r:
                self._fail(
                    "CHK-ACCOUNT", f"{ctx} R beats at port {s['r_port']} != accepted beats {want_r}"
                )
            if view.rlast_ok[init] != len(acc_rd):
                self._fail("CHK-ACCOUNT", f"{ctx} RLAST misplaced at port")
            for t in acc_rd:
                if len(t.words) != t.beats or tuple(t.words) != t.expected_words():
                    got = _listfmt(f"0x{w:x}" for w in t.words)
                    want = _listfmt(f"0x{w:x}" for w in t.expected_words())
                    self._fail(
                        "CHK-ACCOUNT",
                        f"{ctx} wrong_target txn={t.name} addr=0x{t.addr:x} got={got} want={want}",
                    )
            s["non_okay"] = sum(1 for t in txns if t.resp != RESP_OKAY)
        jobs = plan.get("dma", [])
        nw = sum(j.words for j in jobs if j.write)
        nr = sum(j.words for j in jobs if not j.write)
        d = {
            "wr": nw,
            "rd": nr,
            "aw": view.n_req("dma", "wr"),
            "ar": view.n_req("dma", "rd"),
            "w": view.w_by_init["dma"],
            "b_port": view.b_by_init["dma"],
            "r_port": view.r_beats_by_init["dma"],
            "lens_w": view.lens("dma", "wr"),
            "lens_r": view.lens("dma", "rd"),
            "got_ok": sum(
                1 for j in jobs if not j.write for a, b in zip(j.got, j.expected_words()) if a == b
            ),
        }
        st["dma"] = d
        if jobs:
            ctx = f"phase={name} init=dma"
            want_w = sorted(j.out_addr + 4 * i for j in jobs if j.write for i in range(j.words))
            want_r = sorted(j.out_addr + 4 * i for j in jobs if not j.write for i in range(j.words))
            if view.addrs("dma", "wr") != want_w or view.addrs("dma", "rd") != want_r:
                self._fail(
                    "CHK-ACCOUNT",
                    f"{ctx} request missing or seen twice at PR-OUT aw={d['aw']}/{nw} "
                    f"ar={d['ar']}/{nr}",
                )
            if any(v != 0 for v in d["lens_w"] + d["lens_r"]):
                self._fail("CHK-ACCOUNT", f"{ctx} AxLEN not 0 {d['lens_w']} {d['lens_r']}")
            if d["w"] != nw or d["b_port"] != nw:
                self._fail("CHK-ACCOUNT", f"{ctx} W {d['w']} B {d['b_port']} != writes {nw}")
            if d["r_port"] != nr or view.rlast_ok["dma"] != nr:
                self._fail("CHK-ACCOUNT", f"{ctx} R {d['r_port']} / RLAST != reads {nr}")
            for j in jobs:
                if j.status_done != 1 or j.status_error != 0 or j.done_after_clear != 0:
                    self._fail(
                        "CHK-ACCOUNT",
                        f"{ctx} job={j.name} done={j.status_done} status_error={j.status_error} "
                        f"done_after_clear={j.done_after_clear}",
                    )
                if not j.write and j.got != j.expected_words():
                    self._fail(
                        "CHK-ACCOUNT",
                        f"{ctx} wrong_target job={j.name} got={_listfmt(hex(x) for x in j.got)} "
                        f"want={_listfmt(hex(x) for x in j.expected_words())}",
                    )
        n_aw = len([r for r in view.reqs if r.kind == "wr"])
        beats_aw = sum((r.length or 0) + 1 for r in view.reqs if r.kind == "wr")
        beats_ar = sum((r.length or 0) + 1 for r in view.reqs if r.kind == "rd")
        if (
            view.b_total != n_aw
            or view.w_total != beats_aw
            or view.r_total != beats_ar
            or view.b_unmatched
            or view.r_unmatched
        ):
            self._fail(
                "CHK-ACCOUNT",
                f"phase={name} port totals aw={n_aw} w={view.w_total}/{beats_aw} "
                f"b={view.b_total} r={view.r_total}/{beats_ar}",
            )
        lat = [t.latency_ns for init in ("lsu", "sysif") for t in plan.get(init, [])]
        lat += [j.latency_ns for j in jobs]
        st["max_latency_ns"] = max(lat) if lat else 0.0
        return st

    def _tally(self, st: dict) -> None:
        for init, s in st.items():
            if not isinstance(s, dict):
                continue
            t = self.tot[init]
            for k, v in s.items():
                if isinstance(v, int):
                    t[k] = t.get(k, 0) + v

    # ---- phases -------------------------------------------------------------------------
    async def _s2_lsu(self) -> None:
        c = self.c
        plan = {
            "lsu": [self._txn("lsu", "wr") for _ in range(c.n_single)]
            + [self._txn("lsu", "rd") for _ in range(c.n_single)]
        }
        view, marks = await self._run_phase("lsu_alone", plan, serial=True)
        st = self._account("lsu_alone", plan, view, marks)
        self._tally(st)
        s = st["lsu"]
        self._emit(
            "CHK-LSU-PATH",
            f"wr_aw={s['aw']} wr_w={s['w']} wr_b={s['b_master']} rd_ar={s['ar']} "
            f"rd_r={s['r_master']} rlast={s['rlast']} awlen={_setfmt(s['lens_w'])} "
            f"arlen={_setfmt(s['lens_r'])} delays={c.delays()} {self._stall_str()}",
        )
        self._fence("LSU_SINGLES")

    async def _s3_dma(self) -> None:
        rows = []
        for write in (True, False):
            job = self._job(write)
            plan = {"dma": [job]}
            view, marks = await self._run_phase("dma_alone", plan, serial=True, spread=0)
            st = self._account("dma_alone", plan, view, marks)
            self._tally(st)
            rows.append((job, st["dma"]))
        (wj, ws), (rj, rs) = rows
        done = {wj.status_done, rj.status_done}
        err = {wj.status_error, rj.status_error}
        clr = {wj.done_after_clear, rj.done_after_clear}
        self._emit(
            "CHK-DMA-PATH",
            f"wr_aw={ws['aw']} wr_b={ws['b_port']} rd_ar={rs['ar']} rd_r={rs['r_port']} "
            f"awlen={_setfmt(ws['lens_w'])} arlen={_setfmt(rs['lens_r'])} "
            f"status_done={_setfmt(done)} status_error={_setfmt(err)} "
            f"done_after_clear={_setfmt(clr)}",
        )
        self._fence("DMA_SINGLES")

    async def _s4_sysif(self) -> None:
        c = self.c
        plan = {
            "sysif": [self._txn("sysif", "wr") for _ in range(c.n_sys_single)]
            + [self._txn("sysif", "rd") for _ in range(c.n_sys_single)]
        }
        view, marks = await self._run_phase("sysif_alone", plan, serial=True)
        st = self._account("sysif_alone", plan, view, marks)
        self._tally(st)
        s = st["sysif"]
        self._obs_row(
            "SYSIF-SINGLE",
            f"wr_issued={s['wr']} b={s['b_master']} rd_issued={s['rd']} r={s['r_master']} "
            f"rlast={s['rlast']} resp={_setfmt(t.resp for t in plan['sysif'])} "
            f"reached_pr_out={s['aw'] + s['ar']} port_unattributed={view.unattributed}",
        )
        self._fence("SYSIF_SINGLES")

    async def _s5_bursts(self) -> None:
        c = self.c
        wr = [
            self._txn("sysif", "wr", beats=self.rng.randrange(2, c.burst_max + 1))
            for _ in range(c.n_bursts)
        ]
        rd = [
            self._txn("sysif", "rd", beats=self.rng.randrange(2, c.burst_max + 1))
            for _ in range(c.n_bursts)
        ]
        plan = {"sysif": wr + rd}
        view, marks = await self._run_phase("sysif_bursts", plan, serial=True)
        rlast_pos = []
        for t in rd:
            flags = [x[4] for x in self.pin_m.r if t.c0 < x[0] <= t.c1]
            rlast_pos.append(flags.index(1) if 1 in flags else -1)
            if len(flags) != t.beats or flags != [0] * (t.beats - 1) + [1]:
                self._fail(
                    "CHK-SYSIF-NO-OUTBOUND-PATH",
                    f"read burst txn={t.name} beats={t.beats} rlast_flags={_listfmt(flags)}",
                )
        st = self._account("sysif_bursts", plan, view, marks)
        self._tally(st)
        s = st["sysif"]
        self._obs_row(
            "SYSIF-BURST",
            f"wr_len={_listfmt(t.beats - 1 for t in wr)} b={s['b_master']} "
            f"rd_len={_listfmt(t.beats - 1 for t in rd)} r_beats={s['r_master']} "
            f"rlast_pos={_listfmt(rlast_pos)} resp={_setfmt(t.resp for t in wr + rd)} "
            f"reached_pr_out={s['aw'] + s['ar']}",
        )
        self._fence("SYSIF_BURSTS")

    def _conc_line(self, phase: str, plan: dict, st: dict, extra: str = "") -> None:
        def done(init):
            if init == "dma":
                jobs = plan.get("dma", [])
                return f"{sum(1 for j in jobs if j.done)}/{len(jobs)}"
            txns = plan.get(init, [])
            return f"{sum(1 for t in txns if t.done)}/{len(txns)}"

        for init in plan:
            n = len(plan[init])
            if n == 0 or any(not (x.done) for x in plan[init]):
                self._fail(
                    "CHK-CONC-ALL", f"phase={phase} init={init} transaction without response"
                )
        self._emit(
            "CHK-CONC-ALL",
            f"phase={phase} lsu_done={done('lsu')} dma_done={done('dma')} "
            f"sysif_done_decerr={done('sysif')} max_latency_ns={st['max_latency_ns']:.1f} "
            f"timeout_ns={self.tr.timeout_ns} {self._stall_str()}{extra}",
        )
        self.max_lat = max(self.max_lat, st["max_latency_ns"])

    async def _conc(self, phase: str, kind: str, inits=INITS, extra: str = ""):
        plan = self._plan(kind, inits)
        view, marks = await self._run_phase(f"conc_{phase}", plan)
        st = self._account(f"conc_{phase}", plan, view, marks)
        self._tally(st)
        self._conc_line(phase, plan, st, extra)
        return plan, st

    def _route_row(self, st_w: dict, st_r: dict) -> None:
        sw, sr = st_w, st_r
        wrong = 0
        parts = []
        for init in INITS:
            if init == "dma":
                bn, bd = sw["dma"]["b_port"], sw["dma"]["wr"]
                rn, rd = sr["dma"]["got_ok"], sr["dma"]["rd"]
            else:
                bn, bd = sw[init]["b_master"], sw[init]["acc_wr"] + sw[init]["self_wr"]
                rn = sr[init]["r_master"]
                rd = sr[init]["r_port"] + sr[init]["self_rd_beats"]
                if init == "sysif":
                    parts.append(f"b_to_{init}=n/a r_to_{init}=n/a no_outbound_path=1")
                    continue
            wrong += abs(bn - bd) + abs(rn - rd)
            parts.append(f"b_to_{init}={bn}/{bd} r_to_{init}={rn}/{rd}")
        if wrong:
            self._fail("CHK-RESP-ROUTE", " ".join(parts) + f" wrong_target={wrong}")
        self._emit("CHK-RESP-ROUTE", " ".join(parts) + " wrong_target=0")

    async def _s6_to_s9(self) -> None:
        _, st_w = await self._conc("w", "w")
        self._fence("WRITES_3WAY")
        _, st_r = await self._conc("r", "r")
        self._route_row(st_w, st_r)
        self._fence("READS_3WAY")
        await self._conc("mix", "mix")
        self._fence("MIX_3WAY")
        for a, b in (("lsu", "dma"), ("lsu", "sysif"), ("dma", "sysif")):
            await self._conc("pair", "mix", (a, b), extra=f" pair={a}+{b}")
        self._fence("PAIRS")

    async def _same_id(self, inits: tuple, op: str):
        c = self.c
        plan = {i: [self._txn(i, op, axi_id=c.same_id) for _ in range(c.same_id_n)] for i in inits}
        view, marks = await self._run_phase(f"same_id_{op}", plan, spread=0)
        st = self._account(f"same_id_{op}", plan, view, marks)
        self._tally(st)
        return plan, view, marks, st

    async def _s10_id_order(self) -> None:
        c = self.c
        for inits in (("lsu",), ("lsu", "sysif")):
            plan_r, view_r, marks_r, st_r = await self._same_id(inits, "rd")
            plan_w, view_w, marks_w, st_w = await self._same_id(inits, "wr")
            seq_ok = seq_n = 0
            distinct = set()
            conf = 0
            for init in inits:
                if init == "sysif":
                    continue
                pins = self.pin_s if init == "lsu" else self.pin_m
                pm = marks_r[2] if init == "lsu" else marks_r[3]
                lo = 1 if init == "lsu" else 0
                pin_data = [x[3] for x in pins.r[pm[3] :] if x[1] >= lo]
                port_data = view_r.r_data_by_init[init]
                match = sum(1 for a, b in zip(pin_data, port_data) if a == b)
                if len(pin_data) != len(port_data) or match != len(port_data):
                    self._fail(
                        "CHK-ID-ORDER",
                        f"id={c.same_id} init={init} master_r={_listfmt(hex(x) for x in pin_data)} "
                        f"port_r={_listfmt(hex(x) for x in port_data)}",
                    )
                seq_n += len(port_data)
                seq_ok += match
                distinct |= set(port_data)
                other = {
                    r_word(t.addr + 8 * k)
                    for i2 in inits
                    if i2 != init
                    for t in plan_r[i2]
                    for k in range(t.beats)
                }
                conf += sum(1 for t in plan_r[init] for w in t.words if w in other)
            if conf:
                self._fail("CHK-ID-ORDER", f"id={c.same_id} cross_initiator_confusions={conf}")
            wn = wd = 0
            for init in inits:
                if init == "sysif":
                    continue
                order = sorted(plan_w[init], key=lambda t: (t.c1, plan_w[init].index(t)))
                wd += len(order)
                wn += sum(1 for i, t in enumerate(order) if plan_w[init][i] is t)
            tag = " reads_distinct_words_below_2=LINKED-ISSUE" if len(distinct) < 2 else ""
            self.logger.info(
                "OBS-ID-ORDER: id=%d writes_completion_index=%s LINKED-ISSUE SF-007%s",
                c.same_id,
                _listfmt(
                    sorted(range(len(plan_w[inits[0]])), key=lambda i: plan_w[inits[0]][i].c1)
                ),
                tag,
            )
            self._emit(
                "CHK-ID-ORDER",
                f"id={c.same_id} inits={'+'.join(inits)} reads_in_order={seq_ok}/{seq_n} "
                f"writes_in_order={wn}/{wd} distinct_r_words={len(distinct)} "
                f"cross_initiator_confusions={conf}",
            )
        self._fence("ID_ORDER")

    # ---- final accounting -----------------------------------------------------------------
    async def _s11_attr_idle(self) -> None:
        c = self.c
        # idle window: the path is quiet, the delay driver is off
        self.delay.stop()
        idle = (self.rsp.mark(), self.pin_s.mark(), self.pin_m.mark())
        await ClockCycles(self.dut_clk, IDLE_CLOCKS)
        self._wait_bound("idle_window", f"clocks={IDLE_CLOCKS}")
        rsp_idle = self.rsp.since(idle[0])
        extra_b = sum(1 for b in rsp_idle if b.ch == "b")
        extra_r = sum(1 for b in rsp_idle if b.ch == "r")
        ps, pm = self.pin_s.since(idle[1]), self.pin_m.since(idle[2])
        extra_b += ps["b"] + pm["b"]
        extra_r += ps["r"] + pm["r"]

        whole = port_view(self.layout, self.out.since(self.m0[0]), self.rsp.since(self.m0[1]))
        reqs = [r for r in whole.reqs if r.init is not None]
        exp = {
            "lsu": (c.lsu_user, LSU_PROT),
            "dma": (DMA_USER, DMA_PROT),
            "sysif": (c.sys_user, SYS_PROT),
        }
        seen_u = {i: [] for i in INITS}
        seen_p = {i: [] for i in INITS}
        cross_u = cross_p = 0
        for r in reqs:
            if r.unknown:
                self._fail("CHK-ATTR-USER", f"X/Z on a PR-OUT request addr=0x{r.addr or 0:x}")
            seen_u[r.init].append(r.user)
            seen_p[r.init].append(r.prot)
            eu, ep = exp[r.init]
            others_u = {exp[i][0] for i in INITS if i != r.init}
            others_p = {exp[i][1] for i in INITS if i != r.init}
            if r.user != eu and r.user in others_u:
                cross_u += 1
            if r.prot != ep and r.prot in others_p:
                cross_p += 1
        for init in ("lsu", "dma"):
            if any(u != exp[init][0] for u in seen_u[init]):
                self._fail(
                    "CHK-ATTR-USER",
                    f"init={init} user_seen={_setfmt(seen_u[init])} want={exp[init][0]}",
                )
            if any(p != exp[init][1] for p in seen_p[init]):
                self._fail(
                    "CHK-ATTR-PROT",
                    f"init={init} prot_seen={_setfmt(seen_p[init])} want=0b{exp[init][1]:03b}",
                )
        for init in ("lsu", "dma"):
            if not seen_u[init]:
                self._fail("CHK-ATTR-USER", f"init={init} no request at PR-OUT")
        if cross_u:
            self._fail("CHK-ATTR-USER", f"crossings={cross_u}")
        if cross_p:
            self._fail("CHK-ATTR-PROT", f"crossings={cross_p}")
        self._emit(
            "CHK-ATTR-USER",
            f"lsu_user_issued={c.lsu_user} lsu_user_seen={_setfmt(seen_u['lsu'])} "
            f"dma_user_seen={_setfmt(seen_u['dma'])} crossings={cross_u}",
        )

        def pf(vals):
            return "{" + ",".join(f"0b{p:03b}" for p in sorted(set(vals))) + "}"

        lsu_aw = sorted({r.prot for r in reqs if r.init == "lsu" and r.kind == "wr"})
        lsu_ar = sorted({r.prot for r in reqs if r.init == "lsu" and r.kind == "rd"})
        dma_aw = sorted({r.prot for r in reqs if r.init == "dma" and r.kind == "wr"})
        dma_ar = sorted({r.prot for r in reqs if r.init == "dma" and r.kind == "rd"})
        self._emit(
            "CHK-ATTR-PROT",
            f"lsu_awprot={pf(lsu_aw)} lsu_arprot={pf(lsu_ar)} dma_awprot={pf(dma_aw)} "
            f"dma_arprot={pf(dma_ar)} crossings={cross_p}",
        )
        pairs, collisions, ids = id_overlap(whole)
        shared = [
            (a, b, sorted(ids[a] & ids[b]))
            for i, a in enumerate(INITS)
            for b in INITS[i + 1 :]
            if ids[a] & ids[b]
        ]
        if collisions or shared:
            self._fail(
                "CHK-ATTR-ID-DISTINCT",
                f"outstanding_pairs={pairs} id_collisions={collisions} "
                f"lsu_ids={_setfmt(ids['lsu'])} dma_ids={_setfmt(ids['dma'])} "
                f"sysif_ids={_setfmt(ids['sysif'])} shared_ids={shared}",
            )
        self._emit(
            "CHK-ATTR-ID-DISTINCT",
            f"outstanding_pairs={pairs} id_collisions={collisions} lsu_ids={_setfmt(ids['lsu'])} "
            f"dma_ids={_setfmt(ids['dma'])}",
        )

        # exactly-once B and R over the whole run
        whole_s, whole_m = self.pin_s.since(self.m0[2]), self.pin_m.since(self.m0[3])
        t = self.tot
        lsu_aw, lsu_ar_n = whole.n_req("lsu", "wr"), whole.n_req("lsu", "rd")
        dma_aw_n, dma_ar_n = whole.n_req("dma", "wr"), whole.n_req("dma", "rd")
        if whole_s["b"] != lsu_aw or whole.b_by_init["lsu"] != lsu_aw:
            self._fail("CHK-B-COUNT", f"lsu_aw={lsu_aw} lsu_b={whole_s['b']}")
        if whole.b_by_init["dma"] != dma_aw_n:
            self._fail("CHK-B-COUNT", f"dma_aw={dma_aw_n} dma_b={whole.b_by_init['dma']}")
        if whole.b_total != len([r for r in whole.reqs if r.kind == "wr"]):
            self._fail("CHK-B-COUNT", f"port_b={whole.b_total}")
        if extra_b:
            self._fail("CHK-B-COUNT", f"extra_b_after_idle={extra_b}")
        self._emit(
            "CHK-B-COUNT",
            f"lsu_aw={lsu_aw} lsu_b={whole_s['b']} dma_aw={dma_aw_n} "
            f"dma_b={whole.b_by_init['dma']} extra_b_after_idle={extra_b}",
        )
        reads_issued = t["lsu"].get("rd", 0)
        if whole_s["r"] != whole.r_beats_by_init["lsu"] or whole.r_beats_by_init["lsu"] != sum(
            (r.length or 0) + 1 for r in whole.reqs if r.init == "lsu" and r.kind == "rd"
        ):
            self._fail("CHK-R-COUNT", f"lsu_ar={lsu_ar_n} lsu_r={whole_s['r']}")
        if whole.r_beats_by_init["dma"] != dma_ar_n:
            self._fail("CHK-R-COUNT", f"dma_ar={dma_ar_n} dma_r={whole.r_beats_by_init['dma']}")
        if whole_s["rlast"] != reads_issued:
            self._fail("CHK-R-COUNT", f"rlast_ok={whole_s['rlast']} reads={reads_issued}")
        if extra_r:
            self._fail("CHK-R-COUNT", f"extra_r_after_idle={extra_r}")
        self._emit(
            "CHK-R-COUNT",
            f"lsu_ar={lsu_ar_n} lsu_r={whole_s['r']} dma_ar={dma_ar_n} "
            f"dma_r={whole.r_beats_by_init['dma']} rlast_ok={whole_s['rlast']} "
            f"extra_r_after_idle={extra_r}",
        )

        chk = "CHK-SYSIF-NO-OUTBOUND-PATH"
        n = self.sys_neg
        floor = 2 * c.n_sys_single + 2 * c.n_bursts
        reached = whole.n_req("sysif", "wr") + whole.n_req("sysif", "rd")
        if reached:
            self._fail(chk, f"sysif requests at PR-OUT={reached}")
        if n["issued"] < floor or n["decerr"] != n["issued"]:
            self._fail(chk, f"issued={n['issued']} floor={floor} decerr={n['decerr']}")
        if (
            whole_m["b"] != n["writes"]
            or whole_m["r"] != n["beats"]
            or whole_m["rlast"] != n["reads"]
        ):
            self._fail(
                chk,
                f"sysif_b={whole_m['b']} writes={n['writes']} sysif_r={whole_m['r']} "
                f"beats={n['beats']} rlast={whole_m['rlast']} reads={n['reads']}",
            )
        self._emit(
            chk,
            f"issued={n['issued']} floor={floor} decerr={n['decerr']} reached_pr_out={reached} "
            f"b_at_master={whole_m['b']} writes={n['writes']} r_at_master={whole_m['r']} "
            f"beats={n['beats']} rlast={whole_m['rlast']} reads={n['reads']}",
        )
        self._fence("ATTR_AND_IDLE")

    # ---- scenario --------------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.c = c = _Cfg(seed)
        self.rng = SepSeededRng(seed ^ 0x0C0FFEE)
        self.dut_clk = cocotb.top.clk_i
        self.fence_seen: list[str] = []
        self.waits_logged: set[str] = set()
        self.n_made = self.n_jobs = 0
        self.max_lat = 0.0
        self.sys_neg = {"issued": 0, "decerr": 0, "writes": 0, "reads": 0, "beats": 0}
        self.tot = {i: {} for i in INITS}
        self.logger.info("SEED seed=%d", seed)
        for line in c.draw_lines():
            self.logger.info("DRAW %s", line)

        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.out = SepFabricTap("PR-OUT").start()
        self.rsp = SepFabricTap("PR-OUT-RSP").start()
        self.pin_s = PinWatch("s_axi").start()
        self.pin_m = PinWatch("m_axi").start()
        self.layout = Layout(PAGE)
        self.tr = OutboundTraffic(self, self.layout, self._port_state)
        await self._program_filters()
        cocotb.top.smn_outbound_rd_addr_data_i.value = 1
        self.delay = ResponderDelay(SepSeededRng(seed ^ 0x5EED5), c.p_stall, c.p_hold, c.hold_max)
        self.pstall = PortStall().start()
        self._stall0 = (self.pstall.snap(), 0)
        self.delay.start()
        await ClockCycles(self.dut_clk, 4)
        self.m0 = self._marks()
        self.logger.info("DELAYS %s", self.delay.describe())
        self._fence("BRINGUP_DONE")

        await self._s2_lsu()
        await self._s3_dma()
        await self._s4_sysif()
        await self._s5_bursts()
        await self._s6_to_s9()
        await self._s10_id_order()
        await self._s11_attr_idle()

        cocotb.top.smn_outbound_rd_addr_data_i.value = 0
        total_stall = sum(self.pstall.snap().values())
        if (any(c.p_stall) and total_stall == 0) or (c.p_hold and self.delay.hold_clocks == 0):
            self._fail(
                "CHK-LSU-PATH",
                f"drawn delays not exercised port_stall_total={total_stall} "
                f"hold_clocks={self.delay.hold_clocks}",
            )
        self.logger.info(
            "DELAYS-MEASURED port_stall=%s resp_stall_clocks=%s hold_clocks=%d",
            self.pstall.snap(),
            self.delay.stall_clocks,
            self.delay.hold_clocks,
        )
        self.pstall.stop()
        self.pin_s.stop()
        self.pin_m.stop()
        await self.out.stop()
        await self.rsp.stop()
        if self.fence_seen != list(FENCE):
            self._fail("CHK-NONVAC", f"fence order {self.fence_seen}")
        self._emit("CHK-NONVAC", "fence=" + "<".join(self.fence_seen) + f" terms={len(FENCE)}")
        self._emit(
            "CHK-TIMEOUT-PATHS",
            f"waits={_setfmt(sorted(self.waits_logged))} txn_bound_ns={self.tr.timeout_ns} "
            f"idle_clocks={IDLE_CLOCKS} max_latency_ns={self.max_lat:.1f} "
            f"dma_polls_max={self.tr.dma_polls_max}",
        )
        self.logger.info("RESULT %s seed=%d PASS", TEST, seed)
