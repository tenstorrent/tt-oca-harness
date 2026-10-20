# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound target stall, hold-then-release and outstanding-limit saturation.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+sep_outbound_depth=64``. DIRECTED with seed-drawn delays.

Contract (``hw/sys/sep/doc/fabric.adoc``, "Fabric Topology", "Transaction
Routing", "Filtering and Protection"; ``hw/sys/sep/doc/cpu.adoc``, LSU master
and AxPROT table; ``hw/sys/sep/doc/dma.adoc``, master path): the CPU LSU (the
TB master on ``s_axi``) and the Secure DMA (programmed over that master) issue
to one outbound window while the responder (``tb/sep_outbound_mbx.sv``) delays
AW, W and AR READY, delays or holds B and R VALID, and is then released; the
local crossbar stops accepting at its outstanding limit and every request
completes after the release. The SMN inbound master (``m_axi``) issues toward
the same window alongside them; it has no route to the outbound port, so its
accesses are the stimulus of one no-path check and never contend at the port.

Stimulus only through the two TB masters, the DMA CSRs and the responder top
ports (``smn_outbound_resp_hold_i``, ``smn_outbound_ready_stall_i``); the PR-OUT
and PR-OUT-RSP taps, the master handshakes and the DMA STATUS reads are
observation only. The responder queues ``+sep_outbound_depth`` write bursts,
pending B responses and reads, which the leaf requires to be at least the
requests it issues in one hold, so every finite stop it grades at the port is
the DUT's, not the responder's. The LSU master stops at the same count whether
or not the port accepts, so the outbound chain limit is not separable from the
crossbar limit at the pins: the three-initiator hold at that stop is reported
as OBS-CHAIN-HELD and the finite stop and the drain of the chain are graded by
CHK-CHAIN-LIMIT.

The SMN inbound master has no route to the outbound port:
``hw/sys/sep/doc/fabric.adoc`` (Routing) states that the peripheral crossbar
answers any inbound address at or above ``0x4000_0000`` with DECERR, and the
outbound window lies above it. Every access that master issues, in every phase,
is stimulus of the one no-path check CHK-SYSIF-NO-OUTBOUND-PATH; no other
checker counts it.

Printed as measured and never compared: the limit counts, the completion
latency, the response during a hold, the delay range, and the acceptance
point of a request the filters answer themselves.

Checkers (printed as ``CHK-<NAME>: <fields>`` after the exact comparison and
``CHK-<NAME> PASS`` once every comparison of that checker is done):
  CHK-DELAYS        zero-delay baseline, one-channel and all-channel delays.
  CHK-HOLD-DRAIN    requests accepted in a hold, no response in it, drain.
  CHK-XBAR-LIMITS   master-side crossbar limit count for writes and reads, and
                    the drain of every limit session.
  CHK-XBAR-HELD     a request at the crossbar limit is held, then completes.
  CHK-XBAR-POSTDRAIN fresh transactions after the saturation drains.
  CHK-CHAIN-LIMIT   finite outbound acceptance of writes and reads, drain;
                    the writes-and-reads hold under both limits drains.
  CHK-SAT-B-COUNT, CHK-SAT-R-COUNT
                    exactly one B per accepted write, the beats of each
                    accepted read, and none after the idle window.
  CHK-SYSIF-NO-OUTBOUND-PATH
                    every access of the SMN inbound master answers DECERR with
                    one B or its R beats, and none reaches PR-OUT.
  CHK-ATTR-USER     AxUSER[3:0] of every LSU and DMA request at PR-OUT is
                    known, is not OTHERS (0) and is the same on every request
                    of the leaf, although the LSU alternates two distinct
                    non-zero values and the DMA issues OTHERS: the SMU path
                    sets SEP's ID. A request that breaks the first two counts
                    as altered in the check of its session, as does an AxPROT
                    other than bits 0 and 2 as issued with NS 1. The number is
                    logged (OBS-SAT-SRC-ID), with AxUSER[11:4].
  CHK-NONVAC        the ordered fence of the phases.
  CHK-TIMEOUT-PATHS the bound of each wait.
"""

from __future__ import annotations

import math
from types import SimpleNamespace

import cocotb
import pyuvm
from cocotb.triggers import ClockCycles
from cocotb.utils import get_sim_time
from env.sep_fabric_common import SepSrcIdGrade, draw_src_users
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_outbound_contention_seq import (
    DMA_DST,
    DMA_PROT,
    DMA_SRC,
    IDLE_CLOCKS,
    INITS,
    LSU_PROT,
    RESP_DECERR,
    RESP_OKAY,
    RESP_SLVERR,
    SYS_PROT,
    DmaJob,
    OutboundLeaf,
    PinWatch,
    ResponderDelay,
    Txn,
    out_prot,
    port_view,
    run_all,
)
from seq_lib.sep_outbound_stall_seq import CH_MASK, Meter, RespCtl, altered_requests

TEST = "sep_outbound_stall_saturation_test"

DEPTH_PLUSARG = "sep_outbound_depth"
WINDOW = 256
LSU_ISSUE = 20
DMA_WORDS = 16
# One response beat per channel leaves per release, so the releases of a held
# session are bounded by the responses it can have queued.
ONE_RELEASE_POLLS = LSU_ISSUE + DMA_WORDS
ONE_RELEASE_WAIT = 48
MAX_ID = 7
# The MaxTrans parameter of the SEP crossbar instance (hw/sys/sep/rtl/sep.sv);
# printed beside the measured count, never compared.
RTL_MAX_TRANS = 4
# SMN inbound accesses of the baseline, channel, all-channel and hold phases.
SYSIF_ISSUE_FLOOR = 13

FENCE = (
    "BRINGUP_DONE",
    "BASELINE",
    "CHANNEL_DELAYS",
    "ALL_DELAYED",
    "HOLD_RELEASED",
    "MST_LIMIT",
    "SLV_LIMIT",
    "LIMIT_HELD",
    "CHAIN_LIMIT",
    "BOTH_LIMITS",
    "POST_DRAIN",
)
CHECKS = (
    "CHK-DELAYS",
    "CHK-HOLD-DRAIN",
    "CHK-XBAR-LIMITS",
    "CHK-XBAR-HELD",
    "CHK-XBAR-POSTDRAIN",
    "CHK-CHAIN-LIMIT",
    "CHK-SAT-B-COUNT",
    "CHK-SAT-R-COUNT",
    "CHK-SYSIF-NO-OUTBOUND-PATH",
    "CHK-ATTR-USER",
    "CHK-NONVAC",
    "CHK-TIMEOUT-PATHS",
)


class _Cfg:
    """The seed-drawn knobs."""

    def __init__(self, seed: int) -> None:
        rng = SepSeededRng(seed)
        self.seed = seed
        self.lsu_users = draw_src_users(rng)
        lsu_ids = {u & 0xF for u in self.lsu_users}
        self.sys_user = rng.choice([u for u in range(1, 16) if u not in lsu_ids])
        self.delay_max = rng.randrange(8, 33)
        self.p_stall = (rng.randrange(20, 51), rng.randrange(20, 51), rng.randrange(20, 51))
        self.p_hold = rng.randrange(3, 11)
        self.hold_max = rng.randrange(4, 17)
        self.depth = int(cocotb.plusargs.get(DEPTH_PLUSARG, 0))

    def draw_lines(self) -> list[str]:
        return [
            f"responder_depth={self.depth} (+{DEPTH_PLUSARG}) hold_demand={LSU_ISSUE + DMA_WORDS}",
            f"lsu_users=0x{self.lsu_users[0]:03x},0x{self.lsu_users[1]:03x} "
            f"lsu_prot=0b{LSU_PROT:03b}",
            f"sysif_user={self.sys_user} sysif_prot=0b{SYS_PROT:03b}",
            f"one_channel_delay_cycles=1..{self.delay_max}",
            f"all_channels ready_stall_percent aw={self.p_stall[0]} w={self.p_stall[1]} "
            f"ar={self.p_stall[2]} resp_hold_percent={self.p_hold} hold_max_clocks={self.hold_max}",
            f"observation_window_clocks={WINDOW} lsu_issue={LSU_ISSUE} dma_words={DMA_WORDS}",
        ]


@pyuvm.test()
class sep_outbound_stall_saturation_test(OutboundLeaf, sep_base_test):
    """Delays, hold-then-release and limit saturation toward the outbound port."""

    required_evidence = CHECKS

    @staticmethod
    def _now_ps() -> int:
        return int(get_sim_time("ps"))

    # ---- stimulus builders -------------------------------------------------------------
    def _txn(self, init: str, op: str, axi_id: int) -> Txn:
        c = self.c
        self.n_made += 1
        wdata = b""
        if op == "wr":
            wdata = b"".join(self.rng.getrandbits(32).to_bytes(4, "little") for _ in range(2))
        addr = self.layout.alloc(init, 8)
        user = c.lsu_users[len(self.lsu_issued) % 2] if init == "lsu" else c.sys_user
        if init == "lsu":
            self.lsu_issued[addr] = user
        t = Txn(
            init=init,
            op=op,
            addr=addr,
            beats=1,
            axi_id=axi_id,
            user=user,
            prot=LSU_PROT if init == "lsu" else SYS_PROT,
            wdata=wdata,
            name=f"{init}_{op}_{self.n_made}",
        )
        self._note_issue(init, op, [t.addr])
        return t

    def _job(self, write: bool, words: int) -> DmaJob:
        self.n_jobs += 1
        mem = (DMA_SRC if write else DMA_DST) + (self.n_jobs % 4) * 0x40
        job = DmaJob(
            write=write,
            words=words,
            out_addr=self.layout.alloc("dma", 4 * words),
            mem_addr=mem,
            data=[self.rng.getrandbits(32) | 1 for _ in range(words)] if write else [],
            name=f"dma_{'wr' if write else 'rd'}_{self.n_jobs}",
        )
        self._note_issue("dma", job.op, [job.out_addr + 4 * i for i in range(words)])
        return job

    def _note_issue(self, init: str, op: str, addrs: list[int]) -> None:
        self.issued_all.setdefault((init, op), []).extend(addrs)
        if init == "dma":
            self.dma_addrs.update(addrs)
        sess = self.cur
        if sess is not None:
            sess.issued.setdefault((init, op), []).extend(addrs)

    def _pin(self, init: str) -> PinWatch:
        return self.pin_s if init == "lsu" else self.pin_m

    async def _run_t(self, t: Txn) -> Txn:
        return await self.tr.run_txn(t, watch=self._pin(t.init))

    async def _run_t_held(self, t: Txn) -> AssertionError | None:
        """One access of a hold session; its failure is returned for the drain to report."""
        try:
            await self._run_t(t)
        except AssertionError as exc:
            return exc
        return None

    async def _dma_start(self, job: DmaJob) -> None:
        await self.tr.dma_prepare(job)
        await self.tr.dma_go(job)

    async def _dma_finish(self, job: DmaJob, chk: str) -> None:
        """Wait for DONE, clear it and take the copied words; grades the job for ``chk``."""
        self._wait_bound("dma_done", f"status_polls={self.tr.dma.done_bound(4 * job.words)}")
        await self.tr.dma_wait(job)
        await self.tr.dma_finish(job)
        if job.status_done != 1 or job.status_error != 0 or job.done_after_clear != 0:
            self._fail(
                chk,
                f"job={job.name} done={job.status_done} status_err={job.status_error} "
                f"done_after_clear={job.done_after_clear}",
            )
        if not job.write and job.got != job.expected_words():
            self._fail(chk, f"wrong_target job={job.name}")

    def _check_txn(self, t: Txn, chk: str) -> None:
        if t.init == "sysif":
            self._check_sysif_txn(t)
            return
        if not t.done:
            self._fail(chk, f"txn={t.name} not complete")
        if t.resp != RESP_OKAY:
            self._fail(chk, f"txn={t.name} resp={t.resp} not OKAY")
        if t.op == "rd" and tuple(t.words) != t.expected_words():
            self._fail(chk, f"wrong_target txn={t.name} addr=0x{t.addr:x}")

    def _check_sysif_txn(self, t: Txn) -> None:
        """One SMN inbound access: answered DECERR, counted once."""
        chk = "CHK-SYSIF-NO-OUTBOUND-PATH"
        if not t.done:
            self._fail(chk, f"txn={t.name} not complete")
        if t.resp != RESP_DECERR:
            self._fail(chk, f"txn={t.name} resp={t.resp} not DECERR")
        self.sys_checked.add(t.name)

    # ---- one transaction on a quiet path --------------------------------------------------
    async def _lone(
        self, init: str, op: str, chk: str, *, chan: str = "none", delay: int = 0, lead: int = 0
    ):
        """One access of one initiator; the stall or hold of ``chan`` is raised at its start."""
        meter = Meter(self)
        self._wait_bound("txn", f"axi_timeout_ns={self.tr.timeout_ns}")
        rel = None
        job = t = None
        if init == "dma":
            job = self._job(op == "wr", 1)
            await self.tr.dma_prepare(job)
        else:
            t = self._txn(init, op, 1)

        def arm() -> None:
            nonlocal rel
            if chan == "none":
                return
            if chan in CH_MASK:
                self.ctl.stall(CH_MASK[chan])
            else:
                self.ctl.hold(True)
            self._wait_bound("delay_release", f"cycles=baseline+delay (<= {self.c.delay_max}+path)")
            rel = cocotb.start_soon(self.ctl.release_after(lead + delay))

        if init == "dma":
            ri = len(self.rsp.beats)
            arm()
            await self.tr.dma_go(job)
            await self._dma_finish(job, chk)
            beats = [b for b in self.rsp.beats[ri:] if b.ch == ("b" if job.write else "r")]
            if not beats:
                self._fail(chk, f"dma response never seen at PR-OUT-RSP chan={chan}")
            lat = (beats[-1].t_ps - job.t0_ps) / 1000.0
        else:
            arm()
            await self._run_t(t)
            self._check_txn(t, chk)
            lat = t.latency_ns
        if rel is not None:
            await rel
        self.ctl.clear()
        snap = meter.read()
        return SimpleNamespace(
            lat=lat,
            resp=(RESP_OKAY if job.status_error == 0 else RESP_SLVERR) if init == "dma" else t.resp,
            done=int(job.done if init == "dma" else t.done),
            reached=snap["port"][init]["aw"] + snap["port"][init]["ar"] > 0,
        )

    def _delays_line(self, chan, delay, init, op, lat, base, done, total, reached) -> None:
        emit = self._obs_row if init == "sysif" and not reached else self._line
        emit(
            "CHK-DELAYS",
            f"chan={chan} delay_cycles={delay} init={init} latency_ns={lat:.1f} "
            f"baseline_ns={base:.1f} completed={done}/{total} op={op} reached={int(reached)}",
        )

    async def _s2_baseline(self) -> None:
        chk = "CHK-DELAYS"
        for init in INITS:
            for op in ("wr", "rd"):
                r = await self._lone(init, op, chk)
                if init != "sysif" and (r.resp != RESP_OKAY or not r.reached):
                    self._fail(chk, f"baseline init={init} op={op} resp={r.resp}")
                self.base[(init, op)] = r.lat
                self._delays_line("none", 0, init, op, r.lat, r.lat, r.done, 1, r.reached)
        self._fence("BASELINE")

    async def _s3_channels(self) -> None:
        chk = "CHK-DELAYS"
        period = self.cfg.sys_clk_period_ns
        for chan, op in (("aw", "wr"), ("w", "wr"), ("ar", "rd"), ("b", "wr"), ("r", "rd")):
            for init in INITS:
                d = self.rng.randrange(1, self.c.delay_max + 1)
                base = self.base[(init, op)]
                lead = math.ceil(base / period)
                r = await self._lone(init, op, chk, chan=chan, delay=d, lead=lead)
                grade = init != "sysif" or r.reached
                if grade and r.lat - base < d * period:
                    self._fail(
                        chk,
                        f"chan={chan} init={init} delay_cycles={d} latency_ns={r.lat:.1f} "
                        f"baseline_ns={base:.1f} period_ns={period}: the delay never reached "
                        "the path",
                    )
                if not grade:
                    self.logger.info(
                        "OBS-SYSIF-DELAY: chan=%s init=sysif reached=0 no_outbound_path=1", chan
                    )
                self._delays_line(chan, d, init, op, r.lat, base, r.done, 1, r.reached)
        self._fence("CHANNEL_DELAYS")

    async def _s4_all(self) -> None:
        c = self.c
        chk = "CHK-DELAYS"
        self._wait_bound("txn", f"axi_timeout_ns={self.tr.timeout_ns}")
        delay = ResponderDelay(SepSeededRng(c.seed ^ 0x5EED5), c.p_stall, c.p_hold, c.hold_max)
        lsu = [self._txn("lsu", op, 1 + k) for k, op in enumerate(("wr", "wr", "rd", "rd"))]
        sysif = [self._txn("sysif", op, 1 + k) for k, op in enumerate(("wr", "wr", "rd", "rd"))]
        jobs = [self._job(True, 2), self._job(False, 2)]

        async def dma_seq() -> None:
            for j in jobs:
                await self._dma_start(j)
                await self._dma_finish(j, chk)

        meter = Meter(self)
        delay.start()
        try:
            await run_all(
                [
                    run_all([self._run_t(t) for t in lsu]),
                    run_all([self._run_t(t) for t in sysif]),
                    dma_seq(),
                ]
            )
        finally:
            delay.stop()
        snap = meter.read()
        reach = {i: snap["port"][i]["aw"] + snap["port"][i]["ar"] > 0 for i in INITS}
        for t in lsu + sysif:
            self._check_txn(t, chk)
        for init, items in (("lsu", lsu), ("sysif", sysif)):
            if any(not t.done for t in items):
                self._fail(chk, f"chan=all init={init} transaction without response")
            self._delays_line(
                "all",
                sum(delay.stall_clocks) + delay.hold_clocks,
                init,
                "mix",
                max(t.latency_ns for t in items),
                max(self.base[(init, "wr")], self.base[(init, "rd")]),
                sum(1 for t in items if t.done),
                len(items),
                reach[init],
            )
        self._delays_line(
            "all",
            sum(delay.stall_clocks) + delay.hold_clocks,
            "dma",
            "mix",
            max(j.latency_ns for j in jobs),
            max(self.base[("dma", "wr")], self.base[("dma", "rd")]),
            sum(1 for j in jobs if j.done),
            len(jobs),
            reach["dma"],
        )
        self.logger.info("DELAYS %s", delay.describe())
        self._pass(chk)
        self._fence("ALL_DELAYED")

    # ---- hold sessions ---------------------------------------------------------------------
    async def _open(self, name: str, *, lsu_w=0, lsu_r=0, sys_w=0, sys_r=0, dma=None):
        s = SimpleNamespace(
            name=name,
            txns=[],
            tasks=[],
            job=None,
            issued={},
            demand=0,
            next_id={("lsu", "wr"): 1, ("lsu", "rd"): 1, ("sysif", "wr"): 1, ("sysif", "rd"): 1},
        )
        self.cur = s
        s.meter = Meter(self)
        s.t_open_ps = self._now_ps()
        self.ctl.hold(True)
        if dma is not None:
            s.job = self._job(dma[0] == "wr", dma[1])
            await self._dma_start(s.job)
            s.demand += dma[1]
        for init, op, n in (
            ("lsu", "wr", lsu_w),
            ("lsu", "rd", lsu_r),
            ("sysif", "wr", sys_w),
            ("sysif", "rd", sys_r),
        ):
            self._launch(s, init, op, n)
        return s

    def _launch(self, s, init: str, op: str, n: int) -> list:
        made = []
        for _ in range(n):
            ident = (s.next_id[(init, op)] - 1) % MAX_ID + 1
            s.next_id[(init, op)] += 1
            t = self._txn(init, op, ident)
            s.txns.append(t)
            s.tasks.append(cocotb.start_soon(self._run_t_held(t)))
            if init == "lsu":
                s.demand += 1
            made.append(t)
        return made

    async def _window(self, s, chk: str) -> dict:
        """Two observation windows under the hold; the accepted counts stop rising by the second."""
        self._wait_bound("hold_window", f"clocks={2 * WINDOW}")
        await ClockCycles(self.dut_clk, WINDOW)
        a = s.meter.read()
        await ClockCycles(self.dut_clk, WINDOW)
        b = s.meter.read()
        if Meter.key(a) != Meter.key(b):
            self._fail(
                chk,
                f"session={s.name} accepted counts still rising after {WINDOW} clocks "
                f"{Meter.key(a)} -> {Meter.key(b)}",
            )
        return b

    async def _drain(self, s, chk: str, *, release: bool = True):
        """Single release of the hold; every transaction of the session must complete.

        The drained count covers the LSU and DMA transactions; the SMN inbound ones
        are checked by CHK-SYSIF-NO-OUTBOUND-PATH.
        """
        t_rel = self._now_ps()
        if release:
            self.ctl.hold(False)
        fails = []
        for task in s.tasks:
            exc = await task
            if exc is not None:
                fails.append(str(exc))
        if s.job is not None and not fails:
            try:
                await self._dma_finish(s.job, chk)
            except AssertionError as exc:
                fails.append(str(exc))
        graded = [t for t in s.txns if t.init != "sysif"]
        total = len(graded) + (1 if s.job is not None else 0)
        done = sum(1 for t in graded if t.done) + (1 if s.job is not None and s.job.done else 0)
        if fails or done != total:
            self._fail(
                chk,
                f"session={s.name} drained={done}/{total} deadlock=1 detail={fails[:1]}",
            )
        for t in s.txns:
            self._check_txn(t, chk)
        t_last = max([t.t1_ps for t in s.txns] + ([s.job.t1_ps] if s.job is not None else []))
        self._check_session_requests(s, chk)
        self.cur = None
        return done, total, max(0.0, (t_last - t_rel) / 1000.0)

    def _expect_prot(self) -> dict:
        return {"lsu": out_prot(LSU_PROT), "dma": out_prot(DMA_PROT)}

    def _issued_user(self) -> dict:
        """AxUSER issued per address: the LSU draws, and OTHERS (0) for the DMA,
        which drives OTHERS (hw/sys/sep/doc/fabric.adoc, Transaction Routing)."""
        return {**{a: 0 for a in self.dma_addrs}, **self.lsu_issued}

    def _check_session_requests(self, s, chk: str) -> None:
        beats = self.out.beats[s.meter.out0 :]
        reached = sum(
            1
            for b in beats
            if b.ch in ("aw", "ar") and self.layout.owner(b.fields.get("addr")) == "sysif"
        )
        if reached:
            self._fail(
                "CHK-SYSIF-NO-OUTBOUND-PATH", f"session={s.name} sysif requests at PR-OUT={reached}"
            )
        issued = {k: v for k, v in s.issued.items() if k[0] != "sysif"}
        alt, miss = altered_requests(
            self.layout, beats, issued, self._expect_prot(), self.src_grade, self._issued_user()
        )
        if alt or miss:
            self._fail(chk, f"session={s.name} altered={alt} lost={miss} at PR-OUT")

    # ---- S5 ------------------------------------------------------------------------------------
    async def _s5_hold_drain(self) -> None:
        chk = "CHK-HOLD-DRAIN"
        for name, kw, want in (
            ("hold_writes", {"lsu_w": 1, "sys_w": 1, "dma": ("wr", 1)}, 2),
            ("hold_reads", {"lsu_r": 1, "sys_r": 1, "dma": ("rd", 1)}, 2),
        ):
            s = await self._open(name, **kw)
            snap = await self._window(s, chk)
            acc = snap["port_aw"] + snap["port_ar"]
            resp = (
                snap["port_b"] + snap["port_r"] + snap["mst"]["lsu"]["b"] + snap["mst"]["lsu"]["r"]
            )
            if resp:
                self._fail(chk, f"session={name} responses_in_hold={resp}")
            if acc != want:
                self._fail(
                    chk,
                    f"session={name} accepted_in_hold={acc} want={want} per_init="
                    f"{ {i: snap['port'][i] for i in INITS} }",
                )
            sys_resp = snap["mst"]["sysif"]["b"] + snap["mst"]["sysif"]["r"]
            self.logger.info(
                "OBS-HOLD-SYSIF: session=%s sysif_decerr_in_hold=%d no_outbound_path=1 "
                "(the DECERR of the inbound path is not held by the responder)",
                name,
                sys_resp,
            )
            done, total, to_last = await self._drain(s, chk)
            self._line(
                chk,
                f"accepted_in_hold={acc} responses_in_hold={resp} "
                f"responses_after_release={done}/{total} release_to_last_ns={to_last:.1f} "
                f"session={name}",
            )
        self._pass(chk)
        self._fence("HOLD_RELEASED")

    # ---- S6, S7 --------------------------------------------------------------------------------
    async def _s6_mst(self) -> None:
        chk = "CHK-XBAR-LIMITS"
        res = {}
        for op, kw in (("wr", {"lsu_w": LSU_ISSUE}), ("rd", {"lsu_r": LSU_ISSUE})):
            s = await self._open(f"mst_{op}", **kw)
            snap = await self._window(s, chk)
            m = snap["mst"]["lsu"]
            acc, stall = (m["aw"], m["aw_stall"]) if op == "wr" else (m["ar"], m["ar_stall"])
            if stall == 0 or acc >= LSU_ISSUE:
                self._fail(
                    chk,
                    f"session={s.name} no finite stop: accepted={acc} issued={LSU_ISSUE} "
                    f"stall_cycles={stall}",
                )
            self.logger.info(
                "OBS-LIMIT: mst_%s_accepted_before_stall=%d rtl_max_trans=%d stall_cycles=%d "
                "port_accepted=%d (the count is printed, not compared)",
                op,
                acc,
                RTL_MAX_TRANS,
                stall,
                snap["port_aw"] + snap["port_ar"],
            )
            res[op] = acc
            self.drain_acc.append(await self._drain(s, chk))
        self.mst_n = res["wr"]
        self.mst_n_rd = res["rd"]
        self._fence("MST_LIMIT")

    async def _s7_slv(self) -> None:
        chk = "CHK-XBAR-LIMITS"
        slv_lsu = max(1, self.mst_n // 2)
        for name, kw in (
            ("slv_from_2", {"lsu_w": slv_lsu, "dma": ("wr", DMA_WORDS)}),
            ("slv_from_3", {"lsu_w": slv_lsu, "dma": ("wr", DMA_WORDS), "sys_w": slv_lsu}),
        ):
            s = await self._open(name, **kw)
            snap = await self._window(s, chk)
            acc = snap["port_aw"]
            sys_n = snap["mst"]["sysif"]["aw"]
            self.logger.info(
                "OBS-SYSIF-REACH: session=%s sysif_port_accepted=%d sysif_master_aw=%d reached=0 "
                "no_outbound_path=1 (observation only)",
                name,
                snap["port"]["sysif"]["aw"],
                sys_n,
            )
            self.logger.info(
                "OBS-LIMIT: session=%s accepted_at_port=%d demand=%d per_init=%s "
                "rtl_max_trans=%d (the LSU and DMA total at the port; the DMA issues one "
                "write at a time on its held B, so this stop is the DMA's issue policy, not "
                "a slave-port limit)",
                name,
                acc,
                slv_lsu + DMA_WORDS,
                {i: snap["port"][i]["aw"] for i in INITS},
                RTL_MAX_TRANS,
            )
            self.drain_acc.append(await self._drain(s, chk))
        done = sum(d[0] for d in self.drain_acc)
        total = sum(d[1] for d in self.drain_acc)
        self._emit(
            chk,
            f"mst_wr_accepted_before_stall={self.mst_n} "
            f"mst_rd_accepted_before_stall={self.mst_n_rd} issued={LSU_ISSUE} "
            f"drained={done}/{total} deadlock=0",
        )
        self._fence("SLV_LIMIT")

    # ---- S8 ------------------------------------------------------------------------------------
    async def _release_until(self, ok_fn) -> tuple[int, int]:
        """Release one beat per channel at a time until ``ok_fn`` holds.

        Returns (releases used, response beats that left), (0, beats) when the
        bound ran out.
        """
        self._wait_bound(
            "one_release", f"releases={ONE_RELEASE_POLLS} wait_clocks={ONE_RELEASE_WAIT} each"
        )
        beats = 0
        for k in range(1, ONE_RELEASE_POLLS + 1):
            got = await self.ctl.release_one(self.rsp)
            beats += got
            await ClockCycles(self.dut_clk, ONE_RELEASE_WAIT)
            if ok_fn():
                return k, beats
            if not got:
                self.logger.info("OBS-RELEASE: release=%d no response beat left", k)
        return 0, beats

    async def _held(self, name: str, *, lsu_w=0, dma_words=0, sys_w=0, graded: bool) -> None:
        """One hold at the crossbar limit with one extra request per initiator.

        Graded for CHK-XBAR-HELD; the three-initiator session is reported as
        OBS-CHAIN-HELD, since its stop is the same crossbar stop.
        """
        chk = "CHK-XBAR-HELD"
        kw = {"lsu_w": lsu_w, "sys_w": sys_w}
        if dma_words:
            kw["dma"] = ("wr", dma_words)
        s = await self._open(name, **kw)
        before = await self._window(s, chk)
        n_out = len(self.out.beats)
        issued_before = {k: list(v) for k, v in s.issued.items()}
        alt_before, _ = altered_requests(
            self.layout,
            self.out.beats[s.meter.out0 : n_out],
            issued_before,
            self._expect_prot(),
            SepSrcIdGrade("SAT-HELD"),
            self._issued_user(),
        )
        rows = []
        if lsu_w:
            extra = self._launch(s, "lsu", "wr", 1)
            await ClockCycles(self.dut_clk, WINDOW)
            now = s.meter.read()
            stall = now["mst"]["lsu"]["aw_stall"] - before["mst"]["lsu"]["aw_stall"]
            if stall == 0 or now["mst"]["lsu"]["aw"] != before["mst"]["lsu"]["aw"]:
                self._fail(
                    chk,
                    f"session={name} init=lsu stall_cycles={stall} "
                    f"accepted_before={before['mst']['lsu']['aw']} "
                    f"accepted_now={now['mst']['lsu']['aw']}: the extra request met no limit",
                )
            rel = await self._release_until(
                lambda: s.meter.read()["mst"]["lsu"]["aw"] > before["mst"]["lsu"]["aw"]
            )
            rows.append(("lsu", stall, rel, extra))
        if dma_words:
            base_aw = s.meter.read()["port"]["dma"]["aw"]
            rel = await self._release_until(lambda: s.meter.read()["port"]["dma"]["aw"] > base_aw)
            rows.append(("dma", "n/a", rel, None))
        if sys_w:
            extra = self._launch(s, "sysif", "wr", 1)
            await ClockCycles(self.dut_clk, WINDOW)
            now = s.meter.read()
            stall = now["mst"]["sysif"]["aw_stall"] - before["mst"]["sysif"]["aw_stall"]
            rows.append(("sysif", stall, (-1, 0), extra))
        done, total, _ = await self._drain(s, chk)
        for init, stall, (releases, beats), extra in rows:
            if init == "sysif":
                self.logger.info(
                    "OBS-SYSIF-REACH: session=%s reached=0 no_outbound_path=1 (observation only)",
                    name,
                )
                comp = int(all(t.done for t in extra))
                note = " reached=0 no_outbound_path=1 not_graded=observation_only"
            elif init == "dma":
                comp = int(s.job.done)
                note = " stall_src=not_observable_at_a_pin not_graded=observation_only"
            else:
                if releases == 0:
                    self._fail(
                        chk,
                        f"session={name} init=lsu held request never accepted after "
                        f"{ONE_RELEASE_POLLS} releases released_beats={beats}",
                    )
                comp = int(all(t.done for t in extra))
                note = ""
                if not comp:
                    self._fail(chk, f"session={name} init=lsu held request never completed")
            emit = self._line if graded and init == "lsu" else self._obs_row
            emit(
                chk if graded else "CHAIN-HELD",
                f"init={init} stall_cycles={stall} earlier_altered={alt_before} "
                f"releases_to_admit={releases} released_beats={beats} completed={comp} "
                f"session={name} drained={done}/{total}{note}",
            )
        if not graded:
            self._obs_row(
                "CHAIN-HELD",
                f"session={name} port_accepted_writes={before['port_aw']} "
                f"responder_wr_limit={self.c.depth} (the chain stop is the crossbar stop; "
                "the chain limit is not separable at the pins)",
            )

    async def _s8_held(self) -> None:
        n = max(1, self.mst_n)
        await self._held("xbar_held_lsu", lsu_w=n, graded=True)
        await self._held("xbar_held_dma", dma_words=DMA_WORDS, graded=True)
        await self._held("xbar_held_sysif", sys_w=n, graded=True)
        await self._held("chain_held", lsu_w=n, dma_words=DMA_WORDS, sys_w=n, graded=False)
        self._pass("CHK-XBAR-HELD")
        self._fence("LIMIT_HELD")

    # ---- S9, S10 -------------------------------------------------------------------------------
    async def _s9_chain(self) -> None:
        chk = "CHK-CHAIN-LIMIT"
        acc = {}
        done = total = 0
        demand = LSU_ISSUE + DMA_WORDS
        for op, kw in (
            ("write", {"lsu_w": LSU_ISSUE, "dma": ("wr", DMA_WORDS), "sys_w": LSU_ISSUE}),
            ("read", {"lsu_r": LSU_ISSUE, "dma": ("rd", DMA_WORDS), "sys_r": LSU_ISSUE}),
        ):
            s = await self._open(f"chain_{op}", **kw)
            snap = await self._window(s, chk)
            n = snap["port_aw"] if op == "write" else snap["port_ar"]
            if n >= demand:
                self._fail(
                    chk,
                    f"session={s.name} chain_accepted_{op}={n} >= {op} demand {demand} "
                    f"(lsu {LSU_ISSUE} + dma {DMA_WORDS}): no finite stop",
                )
            acc[op] = n
            self.logger.info(
                "OBS-CHAIN-LIMIT: %s_accepted=%d per_init=%s (the count is printed, not compared)",
                op,
                n,
                {i: snap["port"][i] for i in INITS},
            )
            d, t, _ = await self._drain(s, chk)
            done += d
            total += t
        self._line(
            chk,
            f"chain_accepted_write={acc['write']} chain_accepted_read={acc['read']} "
            f"demand={demand} drained={done}/{total} deadlock=0 "
            f"responder_wr_limit={self.c.depth} responder_rd_limit={self.c.depth} "
            "responder_limit_reached=0 chain_stop_cause=not_separable_from_xbar",
        )
        self._fence("CHAIN_LIMIT")

    async def _s10_both(self) -> None:
        chk = "CHK-CHAIN-LIMIT"
        s = await self._open(
            "both",
            lsu_w=LSU_ISSUE,
            lsu_r=LSU_ISSUE,
            sys_w=LSU_ISSUE,
            sys_r=LSU_ISSUE,
            dma=("wr", DMA_WORDS),
        )
        snap = await self._window(s, chk)
        m = snap["mst"]["lsu"]
        xbar = int(m["aw_stall"] > 0 or m["ar_stall"] > 0)
        if not xbar:
            self._fail(chk, "session=both crossbar limit not reached in the hold")
        done, total, to_last = await self._drain(s, chk)
        self._obs_row(
            "BOTH-LIMITS",
            f"xbar_reached={xbar} chain_reached=not_separable_from_xbar port_aw={snap['port_aw']} "
            f"port_ar={snap['port_ar']} responder_wr_limit={self.c.depth} "
            f"responder_rd_limit={self.c.depth} drained={done}/{total} "
            f"release_to_last_ns={to_last:.1f} deadlock=0 (the crossbar stall and the drain "
            "are graded by CHK-CHAIN-LIMIT; the chain limit is not separable at the pins)",
        )
        self._pass(chk)
        self._fence("BOTH_LIMITS")

    # ---- S11 -----------------------------------------------------------------------------------
    async def _s11_post(self) -> None:
        chk = "CHK-XBAR-POSTDRAIN"
        resp = {}
        lats = []
        for init in INITS:
            for op in ("wr", "rd"):
                r = await self._lone(init, op, chk)
                key = f"{init}_{'w' if op == 'wr' else 'r'}"
                if init == "sysif":
                    self._obs_row(
                        chk, f"{key}={r.resp} reached={int(r.reached)} no_outbound_path=1"
                    )
                    continue
                if r.resp != RESP_OKAY:
                    self._fail(chk, f"init={init} op={op} resp={r.resp}")
                resp[key] = r.resp
                lats.append(r.lat)
        base = max(self.base.values())
        self._emit(
            chk,
            " ".join(f"{k}={v}" for k, v in resp.items())
            + f" latency_ns={max(lats):.1f} baseline_ns={base:.1f}",
        )
        self._fence("POST_DRAIN")

    async def _final_accounting(self) -> None:
        bchk, rchk = "CHK-SAT-B-COUNT", "CHK-SAT-R-COUNT"
        self.ctl.clear()
        idle = (self.rsp.mark(), self.pin_s.mark(), self.pin_m.mark())
        await ClockCycles(self.dut_clk, IDLE_CLOCKS)
        self._wait_bound("idle_window", f"clocks={IDLE_CLOCKS}")
        ps, pm = self.pin_s.since(idle[1]), self.pin_m.since(idle[2])
        rsp_idle = self.rsp.beats[idle[0] :]
        extra_b = sum(1 for b in rsp_idle if b.ch == "b") + ps["b"] + pm["b"]
        extra_r = sum(1 for b in rsp_idle if b.ch == "r") + ps["r"] + pm["r"]

        self._check_pin_xz(bchk, rchk)
        whole = port_view(self.layout, self.out.beats[self.m0[0] :], self.rsp.beats[self.m0[1] :])
        ws, wm = self.pin_s.since(self.m0[2]), self.pin_m.since(self.m0[3])
        iss = {k: len(v) for k, v in self.issued_all.items()}
        if whole.unknown:
            self._fail(bchk, f"x_or_z_beats={whole.unknown}")
        lsu_aw, lsu_ar = whole.n_req("lsu", "wr"), whole.n_req("lsu", "rd")
        dma_aw, dma_ar = whole.n_req("dma", "wr"), whole.n_req("dma", "rd")
        sys_aw, sys_ar = whole.n_req("sysif", "wr"), whole.n_req("sysif", "rd")
        if (lsu_aw, lsu_ar) != (iss.get(("lsu", "wr"), 0), iss.get(("lsu", "rd"), 0)):
            self._fail(bchk, f"lsu requests at PR-OUT {lsu_aw}/{lsu_ar} != issued {iss}")
        if (dma_aw, dma_ar) != (iss.get(("dma", "wr"), 0), iss.get(("dma", "rd"), 0)):
            self._fail(bchk, f"dma requests at PR-OUT {dma_aw}/{dma_ar} != issued {iss}")
        if ws["b"] != lsu_aw or whole.b_by_init["lsu"] != lsu_aw:
            self._fail(bchk, f"lsu_aw={lsu_aw} lsu_b={ws['b']}")
        if whole.b_by_init["dma"] != dma_aw:
            self._fail(bchk, f"dma_aw={dma_aw} dma_b={whole.b_by_init['dma']}")
        if whole.b_total != len([r for r in whole.reqs if r.kind == "wr"]):
            self._fail(bchk, f"port_b={whole.b_total}")
        if extra_b:
            self._fail(bchk, f"extra_b_after_idle={extra_b}")
        self._emit(
            bchk,
            f"lsu_aw={lsu_aw} lsu_b={ws['b']} dma_aw={dma_aw} dma_b={whole.b_by_init['dma']} "
            f"extra_b_after_idle={extra_b}",
        )
        if ws["r"] != whole.r_beats_by_init["lsu"] or ws["r"] != lsu_ar:
            self._fail(rchk, f"lsu_ar={lsu_ar} lsu_r={ws['r']}")
        if whole.r_beats_by_init["dma"] != dma_ar:
            self._fail(rchk, f"dma_ar={dma_ar} dma_r={whole.r_beats_by_init['dma']}")
        if ws["rlast"] != lsu_ar:
            self._fail(rchk, f"rlast={ws['rlast']} reads={lsu_ar}")
        if (
            whole.rlast_ok["lsu"] != lsu_ar
            or whole.rlast_ok["dma"] != dma_ar
            or whole.r_total != lsu_ar + dma_ar
        ):
            self._fail(rchk, f"rlast_ok_port={whole.rlast_ok} r_total={whole.r_total}")
        if extra_r:
            self._fail(rchk, f"extra_r_after_idle={extra_r}")
        self._emit(
            rchk,
            f"lsu_ar={lsu_ar} lsu_r={ws['r']} dma_ar={dma_ar} dma_r={whole.r_beats_by_init['dma']} "
            f"extra_r_after_idle={extra_r}",
        )

        chk = "CHK-SYSIF-NO-OUTBOUND-PATH"
        sys_w, sys_r = iss.get(("sysif", "wr"), 0), iss.get(("sysif", "rd"), 0)
        sys_issued = sys_w + sys_r
        if sys_aw + sys_ar:
            self._fail(chk, f"sysif requests at PR-OUT aw={sys_aw} ar={sys_ar}")
        if sys_issued < SYSIF_ISSUE_FLOOR or len(self.sys_checked) != sys_issued:
            self._fail(
                chk,
                f"issued={sys_issued} floor={SYSIF_ISSUE_FLOOR} decerr={len(self.sys_checked)}",
            )
        if wm["b"] != sys_w or wm["r"] != sys_r or wm["rlast"] != sys_r:
            self._fail(
                chk,
                f"sysif_b={wm['b']} writes={sys_w} sysif_r={wm['r']} rlast={wm['rlast']} "
                f"reads={sys_r}",
            )
        self._emit(
            chk,
            f"issued={sys_issued} floor={SYSIF_ISSUE_FLOOR} decerr={len(self.sys_checked)} "
            f"reached_pr_out={sys_aw + sys_ar} b_at_master={wm['b']} writes={sys_w} "
            f"r_at_master={wm['r']} rlast={wm['rlast']} reads={sys_r}",
        )

    def _chk_attr_user(self) -> None:
        """CHK-ATTR-USER over every LSU and DMA request the sessions graded."""
        g = self.src_grade
        why = g.finish(min_nonzero_issued=2)
        if why is not None:
            self._fail("CHK-ATTR-USER", why)
        self.logger.info("%s", g.obs_line())
        c = self.c
        self._emit(
            "CHK-ATTR-USER",
            f"lsu_users_issued=0x{c.lsu_users[0]:03x},0x{c.lsu_users[1]:03x} "
            f"dma_user_issued=0 {g.summary()}",
        )

    # ---- scenario --------------------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.c = c = _Cfg(seed)
        self.rng = SepSeededRng(seed ^ 0x0C0FFEE)
        self.n_made = self.n_jobs = 0
        self.lsu_issued: dict[int, int] = {}
        self.dma_addrs: set[int] = set()
        self.src_grade = SepSrcIdGrade("SAT")
        self.sys_checked: set[str] = set()
        self.cur = None
        self.base: dict = {}
        self.issued_all: dict = {}
        self.drain_acc: list = []
        self.logger.info("SEED seed=%d", seed)
        for line in c.draw_lines():
            self.logger.info("DRAW %s", line)
        if c.depth < LSU_ISSUE + DMA_WORDS:
            raise AssertionError(
                f"SETUP responder_depth={c.depth} below the {LSU_ISSUE + DMA_WORDS} requests of "
                f"one hold: run with +{DEPTH_PLUSARG}={LSU_ISSUE + DMA_WORDS} or more"
            )

        await self.bring_up_no_cpu()
        self.suppress_host_axi_transaction_info()
        self.ctl = RespCtl()
        await self.bench_start()
        await ClockCycles(self.dut_clk, 4)
        self.m0 = (self.out.mark(), self.rsp.mark(), self.pin_s.mark(), self.pin_m.mark())
        self._fence("BRINGUP_DONE")

        await self._s2_baseline()
        await self._s3_channels()
        await self._s4_all()
        await self._s5_hold_drain()
        await self._s6_mst()
        await self._s7_slv()
        await self._s8_held()
        await self._s9_chain()
        await self._s10_both()
        await self._s11_post()
        await self._final_accounting()
        self._chk_attr_user()

        await self.bench_stop()
        self._check_fence(FENCE)
        waits = "{" + ",".join(sorted(self.waits_logged)) + "}"
        self._emit(
            "CHK-TIMEOUT-PATHS",
            f"waits={waits} txn_bound_ns={self.tr.timeout_ns} window_clocks={WINDOW} "
            f"idle_clocks={IDLE_CLOCKS} dma_polls_max={self.tr.dma_polls_max}",
        )
        self.result_pass(TEST, seed, len(CHECKS))
