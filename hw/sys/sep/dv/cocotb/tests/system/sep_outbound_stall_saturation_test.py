# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Outbound target stall, hold-then-release and outstanding-limit saturation.

Run mode: no_cpu (``lsu_stub_all_live``), ``+skip_fuse_sense``,
``+sep_outbound_depth=64``. DIRECTED with seed-drawn delays.

Contract (``hw/sys/sep/doc/fabric.adoc``, "Fabric Topology", "Transaction
Routing", "Filtering and Protection"; the issue text for the local crossbar and
outbound mux/filter outstanding limits under a held outbound target): the CPU
LSU (the TB master on ``s_axi``), the Secure DMA (programmed over that master)
and the SMN inbound master (``m_axi``) issue to one outbound window while the
responder (``tb/sep_outbound_mbx.sv``) delays AW, W and AR READY, delays or
holds B and R VALID, and is then released.

Stimulus only through the two TB masters, the DMA CSRs and the responder top
ports (``smn_outbound_resp_hold_i``, ``smn_outbound_ready_stall_i``); the PR-OUT
and PR-OUT-RSP taps, the master handshakes and the DMA STATUS reads are
observation only. The responder queues ``+sep_outbound_depth`` write bursts,
pending B responses and reads, which the leaf requires to be at least the
requests it issues in one hold, so every finite stop it grades at the port is
the DUT's, not the responder's. The LSU master stops at the same count whether
or not the port accepts, so the outbound chain limit is not separable from the
crossbar limit at the pins: CHK-CHAIN-HELD grades the held request at that
stop and CHK-CHAIN-LIMIT the finite stop and the drain, both tagged SF-003.

Open findings are printed as measured and never compared: the limit counts
(SF-002, SF-003), the System Interface reachability of the outbound port
(SF-009), the completion latency (SF-004), the response during a hold
(SF-005), the delay range (SF-006) and the acceptance point of a request the
filters answer themselves (SF-015).

Checkers (printed as ``CHK-<NAME>: <fields>`` after the exact comparison):
  CHK-DELAYS        zero-delay baseline, one-channel and all-channel delays.
  CHK-HOLD-DRAIN    requests accepted in a hold, no response in it, drain.
  CHK-XBAR-LIMITS   master-side and slave-side crossbar limit counts, drain.
  CHK-XBAR-HELD     a request at the crossbar limit is held, then completes.
  CHK-CHAIN-HELD    a request at the outbound chain limit is held, then completes.
  CHK-XBAR-POSTDRAIN fresh transactions after the saturation drains.
  CHK-CHAIN-LIMIT   finite outbound acceptance of writes and reads, drain.
  CHK-BOTH-LIMITS   both limits in one hold, one release, drain.
  CHK-SAT-B-COUNT, CHK-SAT-R-COUNT
                    exactly one B per accepted write, the beats of each
                    accepted read, and none after the idle window.
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
from env.sep_fabric_tap import SepFabricTap
from env.sep_filter_model import FilterEntry
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import SEP_CPU_CTRL, sym
from seq_lib.sep_dma_ops import _D, DmaTimeout
from seq_lib.sep_fabric_filter_bank_seq import SepFilterBank
from seq_lib.sep_outbound_contention_seq import (
    INITS,
    RESP_OKAY,
    DmaJob,
    Layout,
    OutboundTraffic,
    PinWatch,
    ResponderDelay,
    Txn,
    port_view,
    run_all,
)
from seq_lib.sep_outbound_stall_seq import CH_MASK, Meter, RespCtl, altered_requests

TEST = "sep_outbound_stall_saturation_test"

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
# Expected PR-OUT attributes of the Secure DMA master: AxUSER 0 (hw/sys/sep/doc/fabric.adoc,
# the DMA master leaves AxUSER at zero) and AxPROT 0b001 (hw/sys/sep/doc/cpu.adoc AxPROT
# table and hw/sys/sep/doc/dma.adoc, master path).
DMA_PROT = 0b001
DMA_USER = 0
DEPTH_PLUSARG = "sep_outbound_depth"
WINDOW = 256
IDLE_CLOCKS = 256
ONE_RELEASE_POLLS = 12
ONE_RELEASE_WAIT = 48
LSU_ISSUE = 20
DMA_WORDS = 16
MAX_ID = 7
EXPECTED_LIMIT = 4

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
    "CHK-CHAIN-HELD",
    "CHK-XBAR-POSTDRAIN",
    "CHK-CHAIN-LIMIT",
    "CHK-BOTH-LIMITS",
    "CHK-SAT-B-COUNT",
    "CHK-SAT-R-COUNT",
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
        self.delay_max = rng.randrange(8, 33)
        self.p_stall = (rng.randrange(20, 51), rng.randrange(20, 51), rng.randrange(20, 51))
        self.p_hold = rng.randrange(3, 11)
        self.hold_max = rng.randrange(4, 17)
        self.depth = int(cocotb.plusargs.get(DEPTH_PLUSARG, 0))

    def draw_lines(self) -> list[str]:
        return [
            f"responder_depth={self.depth} (+{DEPTH_PLUSARG}) hold_demand={LSU_ISSUE + DMA_WORDS}",
            f"lsu_user={self.lsu_user} lsu_prot=0b{LSU_PROT:03b}",
            f"sysif_user={self.sys_user} sysif_prot=0b{SYS_PROT:03b}",
            f"one_channel_delay_cycles=1..{self.delay_max}",
            f"all_channels ready_stall_percent aw={self.p_stall[0]} w={self.p_stall[1]} "
            f"ar={self.p_stall[2]} resp_hold_percent={self.p_hold} hold_max_clocks={self.hold_max}",
            f"observation_window_clocks={WINDOW} lsu_issue={LSU_ISSUE} dma_words={DMA_WORDS}",
        ]


@pyuvm.test()
class sep_outbound_stall_saturation_test(sep_base_test):
    """Delays, hold-then-release and limit saturation toward the outbound port."""

    required_evidence = CHECKS

    # ---- log helpers ---------------------------------------------------------
    def _emit(self, chk: str, line: str) -> None:
        self.logger.info("%s: %s", chk, line)
        self.logger.info("%s PASS: compared as stated seed=%d", chk, self.c.seed)

    def _obs_row(self, chk: str, line: str) -> None:
        self.logger.info("OBS-%s: %s", chk[4:], line)

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

    @staticmethod
    def _now_ps() -> int:
        return int(get_sim_time("ps"))

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

    # ---- stimulus builders -------------------------------------------------------------
    def _txn(self, init: str, op: str, axi_id: int) -> Txn:
        c = self.c
        self.n_made += 1
        wdata = b""
        if op == "wr":
            wdata = b"".join(self.rng.getrandbits(32).to_bytes(4, "little") for _ in range(2))
        t = Txn(
            init=init,
            op=op,
            addr=self.layout.alloc(init, 8),
            beats=1,
            axi_id=axi_id,
            user=c.lsu_user if init == "lsu" else c.sys_user,
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
        sess = self.cur
        if sess is not None:
            sess.issued.setdefault((init, op), []).extend(addrs)

    def _pin(self, init: str) -> PinWatch:
        return self.pin_s if init == "lsu" else self.pin_m

    async def _run_t(self, t: Txn) -> Txn:
        return await self.tr.run_txn(t, watch=self._pin(t.init))

    async def _dma_start(self, job: DmaJob) -> None:
        await self.tr.dma_prepare(job)
        job.t0_ps = self._now_ps()
        await self.tr.dma.go()

    async def _dma_finish(self, job: DmaJob) -> None:
        total = 4 * job.words
        self._wait_bound("dma_done", f"status_polls={self.tr.dma.done_bound(total)}")
        try:
            res = await self.tr.dma.run_to_done(total, tag=f" {job.name}")
        except DmaTimeout as exc:
            raise AssertionError(
                f"TIMEOUT initiator=dma txn={job.name} {job.op} words={job.words} "
                f"bound_polls={self.tr.dma.done_bound(total)} "
                f"last_port_state={self._port_state()} detail={exc}"
            ) from exc
        job.t1_ps = self._now_ps()
        job.status_done = res.status.done
        job.status_error = res.status.error
        await self.tr.dma_finish(job)
        job.done = True
        if job.status_done != 1 or job.status_error != 0 or job.done_after_clear != 0:
            self._fail(
                "CHK-DELAYS",
                f"job={job.name} done={job.status_done} status_err={job.status_error} "
                f"done_after_clear={job.done_after_clear}",
            )
        if not job.write and job.got != job.expected_words():
            self._fail("CHK-DELAYS", f"wrong_target job={job.name}")

    def _check_txn(self, t: Txn, chk: str) -> None:
        if not t.done:
            self._fail(chk, f"txn={t.name} not complete")
        if t.init != "lsu":
            return
        if t.resp != RESP_OKAY:
            self._fail(chk, f"txn={t.name} resp={t.resp} not OKAY")
        if t.op == "rd" and tuple(t.words) != t.expected_words():
            self._fail(chk, f"wrong_target txn={t.name} addr=0x{t.addr:x}")

    # ---- one transaction on a quiet path --------------------------------------------------
    async def _lone(self, init: str, op: str, *, chan: str = "none", delay: int = 0, lead: int = 0):
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
            job.t0_ps = self._now_ps()
            await self.tr.dma.go()
            await self._dma_finish(job)
            beats = [b for b in self.rsp.beats[ri:] if b.ch == ("b" if job.write else "r")]
            if not beats:
                self._fail("CHK-DELAYS", f"dma response never seen at PR-OUT-RSP chan={chan}")
            lat = (beats[-1].t_ps - job.t0_ps) / 1000.0
        else:
            arm()
            await self._run_t(t)
            self._check_txn(t, "CHK-DELAYS")
            lat = t.latency_ns
        if rel is not None:
            await rel
        self.ctl.clear()
        snap = meter.read()
        return SimpleNamespace(
            lat=lat,
            resp=(RESP_OKAY if job.status_error == 0 else 2) if init == "dma" else t.resp,
            reached=snap["port"][init]["aw"] + snap["port"][init]["ar"] > 0,
        )

    def _delays_line(self, chan, delay, init, op, lat, base, done, reached) -> None:
        emit = self._obs_row if init == "sysif" and not reached else self._emit
        emit(
            "CHK-DELAYS",
            f"chan={chan} delay_cycles={delay} init={init} latency_ns={lat:.1f} "
            f"baseline_ns={base:.1f} completed={done}/{done} op={op} reached={int(reached)}",
        )

    async def _s2_baseline(self) -> None:
        for init in INITS:
            for op in ("wr", "rd"):
                r = await self._lone(init, op)
                if init == "sysif":
                    self.sys_reached = self.sys_reached or r.reached
                    if not r.reached:
                        self.logger.info(
                            "OBS-SYSIF-REACH: op=%s resp=%d reached=0 LINKED-ISSUE SF-009 "
                            "(observation only)",
                            op,
                            r.resp,
                        )
                elif r.resp != RESP_OKAY or not r.reached:
                    self._fail("CHK-DELAYS", f"baseline init={init} op={op} resp={r.resp}")
                self.base[(init, op)] = r.lat
                self._delays_line("none", 0, init, op, r.lat, r.lat, 1, r.reached)
        self._fence("BASELINE")

    async def _s3_channels(self) -> None:
        period = self.cfg.sys_clk_period_ns
        for chan, op in (("aw", "wr"), ("w", "wr"), ("ar", "rd"), ("b", "wr"), ("r", "rd")):
            for init in INITS:
                d = self.rng.randrange(1, self.c.delay_max + 1)
                base = self.base[(init, op)]
                lead = math.ceil(base / period)
                r = await self._lone(init, op, chan=chan, delay=d, lead=lead)
                grade = init != "sysif" or r.reached
                if grade and r.lat - base < d * period:
                    self._fail(
                        "CHK-DELAYS",
                        f"chan={chan} init={init} delay_cycles={d} latency_ns={r.lat:.1f} "
                        f"baseline_ns={base:.1f} period_ns={period}: the delay never reached the path",
                    )
                if not grade:
                    self.logger.info(
                        "OBS-SYSIF-DELAY: chan=%s init=sysif reached=0 LINKED-ISSUE SF-009", chan
                    )
                self._delays_line(chan, d, init, op, r.lat, base, 1, r.reached)
        self._fence("CHANNEL_DELAYS")

    async def _s4_all(self) -> None:
        c = self.c
        self._wait_bound("txn", f"axi_timeout_ns={self.tr.timeout_ns}")
        delay = ResponderDelay(SepSeededRng(c.seed ^ 0x5EED5), c.p_stall, c.p_hold, c.hold_max)
        lsu = [self._txn("lsu", op, 1 + k) for k, op in enumerate(("wr", "wr", "rd", "rd"))]
        sysif = [self._txn("sysif", op, 1 + k) for k, op in enumerate(("wr", "wr", "rd", "rd"))]
        jobs = [self._job(True, 2), self._job(False, 2)]

        async def dma_seq() -> None:
            for j in jobs:
                await self._dma_start(j)
                await self._dma_finish(j)

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
        for t in lsu:
            self._check_txn(t, "CHK-DELAYS")
        for init, items in (("lsu", lsu), ("sysif", sysif)):
            if any(not t.done for t in items):
                self._fail("CHK-DELAYS", f"chan=all init={init} transaction without response")
            self._delays_line(
                "all",
                sum(delay.stall_clocks) + delay.hold_clocks,
                init,
                "mix",
                max(t.latency_ns for t in items),
                max(self.base[(init, "wr")], self.base[(init, "rd")]),
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
            len(jobs),
            reach["dma"],
        )
        self.logger.info("DELAYS %s", delay.describe())
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
            s.tasks.append(cocotb.start_soon(self._run_t(t)))
            if init == "lsu":
                s.demand += 1
            made.append(t)
        return made

    async def _window(self, s, chk: str) -> dict:
        """Two observation windows under the hold; the accepted counts must not rise in the second."""
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
        """Single release of the hold; every transaction of the session must complete."""
        t_rel = self._now_ps()
        if release:
            self.ctl.hold(False)
        fails = []
        for task in s.tasks:
            try:
                await task
            except AssertionError as exc:
                fails.append(str(exc))
        if s.job is not None and not fails:
            try:
                await self._dma_finish(s.job)
            except AssertionError as exc:
                fails.append(str(exc))
        total = len(s.txns) + (1 if s.job is not None else 0)
        done = sum(1 for t in s.txns if t.done) + (1 if s.job is not None and s.job.done else 0)
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

    def _expect_attr(self) -> dict:
        return {"lsu": (self.c.lsu_user, LSU_PROT), "dma": (DMA_USER, DMA_PROT)}

    def _check_session_requests(self, s, chk: str) -> None:
        alt, miss = altered_requests(
            self.layout, self.out.beats[s.meter.out0 :], s.issued, self._expect_attr()
        )
        reached_sys = any(
            self.layout.owner(b.fields.get("addr")) == "sysif"
            for b in self.out.beats[s.meter.out0 :]
            if b.ch in ("aw", "ar")
        )
        sys_missing = sum(len(v) for (i, _), v in s.issued.items() if i == "sysif")
        if not reached_sys:
            miss -= sys_missing
        if alt or miss:
            self._fail(chk, f"session={s.name} altered={alt} lost={miss} at PR-OUT")

    # ---- S5 ------------------------------------------------------------------------------------
    async def _s5_hold_drain(self) -> None:
        for name, kw, want in (
            ("hold_writes", {"lsu_w": 1, "sys_w": 1, "dma": ("wr", 1)}, 2),
            ("hold_reads", {"lsu_r": 1, "sys_r": 1, "dma": ("rd", 1)}, 2),
        ):
            s = await self._open(name, **kw)
            snap = await self._window(s, "CHK-HOLD-DRAIN")
            acc = snap["port_aw"] + snap["port_ar"]
            resp = (
                snap["port_b"] + snap["port_r"] + snap["mst"]["lsu"]["b"] + snap["mst"]["lsu"]["r"]
            )
            if resp:
                self._fail("CHK-HOLD-DRAIN", f"session={name} responses_in_hold={resp}")
            if acc != want:
                self._fail(
                    "CHK-HOLD-DRAIN",
                    f"session={name} accepted_in_hold={acc} want={want} per_init="
                    f"{ {i: snap['port'][i] for i in INITS} }",
                )
            sys_resp = snap["mst"]["sysif"]["b"] + snap["mst"]["sysif"]["r"]
            self.logger.info(
                "OBS-HOLD-SYSIF: session=%s sysif_responses_in_hold=%d reached=0 "
                "LINKED-ISSUE SF-009 SF-005 (observation only)",
                name,
                sys_resp,
            )
            done, total, to_last = await self._drain(s, "CHK-HOLD-DRAIN")
            self._emit(
                "CHK-HOLD-DRAIN",
                f"accepted_in_hold={acc} responses_in_hold={resp} "
                f"responses_after_release={done}/{total} release_to_last_ns={to_last:.1f} "
                f"session={name}",
            )
        self._fence("HOLD_RELEASED")

    # ---- S6, S7 --------------------------------------------------------------------------------
    def _lim_note(self, what: str, n: int, sf: str) -> None:
        tag = (
            "matches_expected"
            if n == EXPECTED_LIMIT
            else f"expected={EXPECTED_LIMIT} LINKED-ISSUE {sf}"
        )
        self.logger.info("OBS-LIMIT: %s measured=%d %s", what, n, tag)

    async def _s6_mst(self) -> None:
        res = {}
        for op, kw in (("wr", {"lsu_w": LSU_ISSUE}), ("rd", {"lsu_r": LSU_ISSUE})):
            s = await self._open(f"mst_{op}", **kw)
            snap = await self._window(s, "CHK-XBAR-LIMITS")
            m = snap["mst"]["lsu"]
            acc, stall = (m["aw"], m["aw_stall"]) if op == "wr" else (m["ar"], m["ar_stall"])
            if stall == 0 or acc >= LSU_ISSUE:
                self._fail(
                    "CHK-XBAR-LIMITS",
                    f"session={s.name} no finite stop: accepted={acc} issued={LSU_ISSUE} "
                    f"stall_cycles={stall}",
                )
            self._lim_note(f"mst_{op}_accepted_before_stall", acc, "SF-002")
            self.logger.info(
                "OBS-LIMIT: mst_%s stall_cycles=%d port_accepted=%d",
                op,
                stall,
                snap["port_aw"] + snap["port_ar"],
            )
            res[op] = acc
            self.drain_acc.append(await self._drain(s, "CHK-XBAR-LIMITS"))
        self.mst_n = res["wr"]
        self.mst_n_rd = res["rd"]
        self._fence("MST_LIMIT")

    async def _s7_slv(self) -> None:
        res = {}
        slv_lsu = max(1, self.mst_n // 2)
        for name, kw in (
            ("slv_from_2", {"lsu_w": slv_lsu, "dma": ("wr", DMA_WORDS)}),
            ("slv_from_3", {"lsu_w": slv_lsu, "dma": ("wr", DMA_WORDS), "sys_w": slv_lsu}),
        ):
            s = await self._open(name, **kw)
            snap = await self._window(s, "CHK-XBAR-LIMITS")
            acc = snap["port_aw"]
            demand = slv_lsu + DMA_WORDS
            if acc >= demand:
                self._fail(
                    "CHK-XBAR-LIMITS",
                    f"session={name} no finite stop: accepted={acc} demand={demand}",
                )
            sys_n = snap["mst"]["sysif"]["aw"]
            self.logger.info(
                "OBS-SYSIF-REACH: session=%s sysif_port_accepted=%d sysif_master_aw=%d reached=0 "
                "LINKED-ISSUE SF-009 (observation only)",
                name,
                snap["port"]["sysif"]["aw"],
                sys_n,
            )
            self.logger.info(
                "OBS-LIMIT: %s issuers_total_accepted_at_port=%d per_init=%s (lsu+dma total, not "
                "a slave-port limit; MaxSlvTrans not evaluated) LINKED-ISSUE SF-002",
                name,
                acc,
                {i: snap["port"][i]["aw"] for i in INITS},
            )
            res[name] = acc
            self.drain_acc.append(await self._drain(s, "CHK-XBAR-LIMITS"))
        done = sum(d[0] for d in self.drain_acc)
        total = sum(d[1] for d in self.drain_acc)
        self._emit(
            "CHK-XBAR-LIMITS",
            f"mst_limit_expected={EXPECTED_LIMIT} mst_accepted_before_stall={self.mst_n} "
            f"slv_limit_expected={EXPECTED_LIMIT} slv_accepted_from_2={res['slv_from_2']} "
            f"slv_accepted_from_3={res['slv_from_3']} drained={done}/{total} deadlock=0",
        )
        self._fence("SLV_LIMIT")

    # ---- S8 ------------------------------------------------------------------------------------
    async def _pulse_until(self, ok_fn) -> int:
        """Release responses a few at a time until ``ok_fn`` holds; returns the pulses used."""
        self._wait_bound(
            "one_release", f"pulses={ONE_RELEASE_POLLS} wait_clocks={ONE_RELEASE_WAIT} each"
        )
        for k in range(1, ONE_RELEASE_POLLS + 1):
            got = await self.ctl.pulse_hold_low(self.rsp)
            await ClockCycles(self.dut_clk, ONE_RELEASE_WAIT)
            if ok_fn():
                return k
            if not got:
                self.logger.info("OBS-RELEASE: pulse=%d no response beat appeared", k)
        return 0

    async def _held(self, chk: str, name: str, *, lsu_w=0, dma_words=0, sys_w=0) -> None:
        kw = {"lsu_w": lsu_w, "sys_w": sys_w}
        if dma_words:
            kw["dma"] = ("wr", dma_words)
        s = await self._open(name, **kw)
        before = await self._window(s, chk)
        n_out = len(self.out.beats)
        issued_before = {k: list(v) for k, v in s.issued.items()}
        alt_before, _ = altered_requests(
            self.layout, self.out.beats[s.meter.out0 : n_out], issued_before, self._expect_attr()
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
                    f"init=lsu stall_cycles={stall} accepted_before={before['mst']['lsu']['aw']} "
                    f"accepted_now={now['mst']['lsu']['aw']}: the extra request met no limit",
                )
            pulses = await self._pulse_until(
                lambda: s.meter.read()["mst"]["lsu"]["aw"] > before["mst"]["lsu"]["aw"]
            )
            rows.append(("lsu", stall, pulses, extra))
        if dma_words:
            pend = dma_words - before["port"]["dma"]["aw"]
            if pend <= 0:
                self._fail(
                    chk,
                    f"init=dma accepted={before['port']['dma']['aw']} of {dma_words}: no limit reached",
                )
            base_aw = s.meter.read()["port"]["dma"]["aw"]
            pulses = await self._pulse_until(lambda: s.meter.read()["port"]["dma"]["aw"] > base_aw)
            rows.append(("dma", "n/a", pulses, None))
        if sys_w:
            extra = self._launch(s, "sysif", "wr", 1)
            await ClockCycles(self.dut_clk, WINDOW)
            now = s.meter.read()
            stall = now["mst"]["sysif"]["aw_stall"] - before["mst"]["sysif"]["aw_stall"]
            rows.append(("sysif", stall, -1, extra))
        done, total, _ = await self._drain(s, chk)
        completed = {}
        for init, stall, pulses, extra in rows:
            if init == "sysif":
                self.logger.info(
                    "OBS-SYSIF-REACH: session=%s reached=0 LINKED-ISSUE SF-009 (observation only)",
                    name,
                )
                acc = "na"
                comp = int(all(t.done for t in extra))
            elif init == "dma":
                if pulses == 0:
                    self._fail(chk, "init=dma held request never accepted after the releases")
                acc = f"{pulses}pulses"
                comp = int(s.job.done)
            else:
                if pulses == 0:
                    self._fail(chk, "init=lsu held request never accepted after the releases")
                acc = f"{pulses}pulses"
                comp = int(all(t.done for t in extra))
            if not comp:
                self._fail(chk, f"init={init} held request never completed")
            completed[init] = comp
            emit = self._emit if init == "lsu" else self._obs_row
            emit(
                chk,
                f"init={init} stall_cycles={stall} earlier_altered={alt_before} "
                f"accepted_after_release={acc} completed={comp} session={name} "
                f"drained={done}/{total}"
                + (
                    " stall_src=not_observable_at_a_pin not_graded=observation_only"
                    if init == "dma"
                    else (
                        " reached=0 not_graded=observation_only LINKED-ISSUE SF-009"
                        if init == "sysif"
                        else ""
                    )
                ),
            )
        if chk == "CHK-CHAIN-HELD":
            self.logger.info(
                "OBS-CHAIN-HELD: port_accepted_writes=%d responder_wr_limit=%d "
                "chain_stop_cause=not_separable_from_xbar LINKED-ISSUE SF-003 (observation only)",
                before["port_aw"],
                self.c.depth,
            )

    async def _s8_held(self) -> None:
        n = max(1, self.mst_n)
        await self._held("CHK-XBAR-HELD", "xbar_held_lsu", lsu_w=n)
        await self._held("CHK-XBAR-HELD", "xbar_held_dma", dma_words=DMA_WORDS)
        await self._held("CHK-XBAR-HELD", "xbar_held_sysif", sys_w=n)
        await self._held("CHK-CHAIN-HELD", "chain_held", lsu_w=n, dma_words=DMA_WORDS, sys_w=n)
        self._fence("LIMIT_HELD")

    # ---- S9, S10 -------------------------------------------------------------------------------
    async def _s9_chain(self) -> None:
        acc = {}
        done = total = 0
        demand = LSU_ISSUE + DMA_WORDS
        for op, kw in (
            ("write", {"lsu_w": LSU_ISSUE, "dma": ("wr", DMA_WORDS), "sys_w": LSU_ISSUE}),
            ("read", {"lsu_r": LSU_ISSUE, "dma": ("rd", DMA_WORDS), "sys_r": LSU_ISSUE}),
        ):
            s = await self._open(f"chain_{op}", **kw)
            snap = await self._window(s, "CHK-CHAIN-LIMIT")
            n = snap["port_aw"] if op == "write" else snap["port_ar"]
            if n >= demand:
                self._fail(
                    "CHK-CHAIN-LIMIT",
                    f"session={s.name} chain_accepted_{op}={n} >= {op} demand {demand} "
                    f"(lsu {LSU_ISSUE} + dma {DMA_WORDS}): no finite stop",
                )
            acc[op] = n
            self.logger.info(
                "OBS-CHAIN-LIMIT: %s_accepted=%d per_init=%s LINKED-ISSUE SF-003",
                op,
                n,
                {i: snap["port"][i] for i in INITS},
            )
            d, t, _ = await self._drain(s, "CHK-CHAIN-LIMIT")
            done += d
            total += t
        self._emit(
            "CHK-CHAIN-LIMIT",
            f"chain_accepted_write={acc['write']} chain_accepted_read={acc['read']} "
            f"demand={demand} drained={done}/{total} deadlock=0 "
            f"responder_wr_limit={self.c.depth} responder_rd_limit={self.c.depth} "
            "responder_limit_reached=0 chain_stop_cause=not_separable_from_xbar "
            "LINKED-ISSUE=SF-003",
        )
        self._fence("CHAIN_LIMIT")

    async def _s10_both(self) -> None:
        s = await self._open(
            "both",
            lsu_w=LSU_ISSUE,
            lsu_r=LSU_ISSUE,
            sys_w=LSU_ISSUE,
            sys_r=LSU_ISSUE,
            dma=("wr", DMA_WORDS),
        )
        snap = await self._window(s, "CHK-BOTH-LIMITS")
        m = snap["mst"]["lsu"]
        xbar = int(m["aw_stall"] > 0 or m["ar_stall"] > 0)
        if not xbar:
            self._fail("CHK-BOTH-LIMITS", "crossbar limit not reached in the hold")
        done, total, to_last = await self._drain(s, "CHK-BOTH-LIMITS")
        self._emit(
            "CHK-BOTH-LIMITS",
            f"xbar_reached={xbar} chain_reached=not_separable_from_xbar port_aw={snap['port_aw']} "
            f"port_ar={snap['port_ar']} responder_wr_limit={self.c.depth} "
            f"responder_rd_limit={self.c.depth} LINKED-ISSUE=SF-003 drained={done}/{total} "
            f"release_to_last_ns={to_last:.1f} deadlock=0",
        )
        self._fence("BOTH_LIMITS")

    # ---- S11 -----------------------------------------------------------------------------------
    async def _s11_post(self) -> None:
        resp = {}
        lats = []
        for init in INITS:
            for op in ("wr", "rd"):
                r = await self._lone(init, op)
                if init != "sysif" and r.resp != RESP_OKAY:
                    self._fail("CHK-XBAR-POSTDRAIN", f"init={init} op={op} resp={r.resp}")
                resp[f"{init}_{'w' if op == 'wr' else 'r'}"] = r.resp
                lats.append(r.lat)
        base = max(self.base.values())
        self._emit(
            "CHK-XBAR-POSTDRAIN",
            " ".join(f"{k}={v}" for k, v in resp.items())
            + f" latency_ns={max(lats):.1f} baseline_ns={base:.1f}",
        )
        self._fence("POST_DRAIN")

    async def _final_accounting(self) -> None:
        self.ctl.clear()
        idle = (self.rsp.mark(), self.pin_s.mark(), self.pin_m.mark())
        await ClockCycles(self.dut_clk, IDLE_CLOCKS)
        self._wait_bound("idle_window", f"clocks={IDLE_CLOCKS}")
        ps, pm = self.pin_s.since(idle[1]), self.pin_m.since(idle[2])
        rsp_idle = self.rsp.beats[idle[0] :]
        extra_b = sum(1 for b in rsp_idle if b.ch == "b") + ps["b"] + pm["b"]
        extra_r = sum(1 for b in rsp_idle if b.ch == "r") + ps["r"] + pm["r"]

        whole = port_view(self.layout, self.out.beats[self.m0[0] :], self.rsp.beats[self.m0[1] :])
        ws, wm = self.pin_s.since(self.m0[2]), self.pin_m.since(self.m0[3])
        iss = {k: len(v) for k, v in self.issued_all.items()}
        if whole.unknown:
            self._fail("CHK-SAT-B-COUNT", f"x_or_z_beats={whole.unknown}")
        lsu_aw, lsu_ar = whole.n_req("lsu", "wr"), whole.n_req("lsu", "rd")
        dma_aw, dma_ar = whole.n_req("dma", "wr"), whole.n_req("dma", "rd")
        sys_aw, sys_ar = whole.n_req("sysif", "wr"), whole.n_req("sysif", "rd")
        if (lsu_aw, lsu_ar) != (iss.get(("lsu", "wr"), 0), iss.get(("lsu", "rd"), 0)):
            self._fail(
                "CHK-SAT-B-COUNT", f"lsu requests at PR-OUT {lsu_aw}/{lsu_ar} != issued {iss}"
            )
        if (dma_aw, dma_ar) != (iss.get(("dma", "wr"), 0), iss.get(("dma", "rd"), 0)):
            self._fail(
                "CHK-SAT-B-COUNT", f"dma requests at PR-OUT {dma_aw}/{dma_ar} != issued {iss}"
            )
        if ws["b"] != lsu_aw or whole.b_by_init["lsu"] != lsu_aw:
            self._fail("CHK-SAT-B-COUNT", f"lsu_aw={lsu_aw} lsu_b={ws['b']}")
        if whole.b_by_init["dma"] != dma_aw:
            self._fail("CHK-SAT-B-COUNT", f"dma_aw={dma_aw} dma_b={whole.b_by_init['dma']}")
        sys_issued_w = iss.get(("sysif", "wr"), 0)
        if wm["b"] != sys_issued_w:
            self._fail("CHK-SAT-B-COUNT", f"sysif_issued={sys_issued_w} sysif_b={wm['b']}")
        if whole.b_total != len([r for r in whole.reqs if r.kind == "wr"]):
            self._fail("CHK-SAT-B-COUNT", f"port_b={whole.b_total}")
        if extra_b:
            self._fail("CHK-SAT-B-COUNT", f"extra_b_after_idle={extra_b}")
        if sys_aw + sys_ar:
            self.logger.info("OBS-SYSIF-REACH: reached=1 aw=%d ar=%d", sys_aw, sys_ar)
        else:
            self.logger.info(
                "OBS-SAT-B-COUNT: sysif_writes_answered_without_port_request=%d "
                "LINKED-ISSUE SF-009 SF-015",
                sys_issued_w,
            )
        self._emit(
            "CHK-SAT-B-COUNT",
            f"lsu_aw={lsu_aw} lsu_b={ws['b']} dma_aw={dma_aw} dma_b={whole.b_by_init['dma']} "
            f"sysif_aw={sys_aw} sysif_b={wm['b']} extra_b_after_idle={extra_b}",
        )
        if ws["r"] != whole.r_beats_by_init["lsu"] or ws["r"] != lsu_ar:
            self._fail("CHK-SAT-R-COUNT", f"lsu_ar={lsu_ar} lsu_r={ws['r']}")
        if whole.r_beats_by_init["dma"] != dma_ar:
            self._fail("CHK-SAT-R-COUNT", f"dma_ar={dma_ar} dma_r={whole.r_beats_by_init['dma']}")
        sys_issued_r = iss.get(("sysif", "rd"), 0)
        if wm["r"] != sys_issued_r:
            self._fail("CHK-SAT-R-COUNT", f"sysif_issued={sys_issued_r} sysif_r={wm['r']}")
        rlast = ws["rlast"] + wm["rlast"]
        if rlast != lsu_ar + sys_issued_r:
            self._fail("CHK-SAT-R-COUNT", f"rlast={rlast} reads={lsu_ar + sys_issued_r}")
        if (
            whole.rlast_ok["lsu"] != lsu_ar
            or whole.rlast_ok["dma"] != dma_ar
            or whole.r_total != lsu_ar + dma_ar
        ):
            self._fail("CHK-SAT-R-COUNT", f"rlast_ok_port={whole.rlast_ok} r_total={whole.r_total}")
        if extra_r:
            self._fail("CHK-SAT-R-COUNT", f"extra_r_after_idle={extra_r}")
        self._emit(
            "CHK-SAT-R-COUNT",
            f"lsu_ar={lsu_ar} lsu_r={ws['r']} dma_ar={dma_ar} dma_r={whole.r_beats_by_init['dma']} "
            f"sysif_ar={sys_ar} sysif_r={wm['r']} extra_r_after_idle={extra_r}",
        )

    # ---- scenario --------------------------------------------------------------------------------
    async def run_scenario(self) -> None:
        seed = self.random_seed()
        self.c = c = _Cfg(seed)
        self.rng = SepSeededRng(seed ^ 0x0C0FFEE)
        self.dut_clk = cocotb.top.clk_i
        self.fence_seen: list[str] = []
        self.waits_logged: set[str] = set()
        self.n_made = self.n_jobs = 0
        self.sys_reached = False
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
        self.out = SepFabricTap("PR-OUT").start()
        self.rsp = SepFabricTap("PR-OUT-RSP").start()
        self.pin_s = PinWatch("s_axi").start()
        self.pin_m = PinWatch("m_axi").start()
        self.layout = Layout(PAGE)
        self.tr = OutboundTraffic(self, self.layout, self._port_state)
        self.ctl = RespCtl()
        await self._program_filters()
        cocotb.top.smn_outbound_rd_addr_data_i.value = 1
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

        cocotb.top.smn_outbound_rd_addr_data_i.value = 0
        self.pin_s.stop()
        self.pin_m.stop()
        await self.out.stop()
        await self.rsp.stop()
        if self.fence_seen != list(FENCE):
            self._fail("CHK-NONVAC", f"fence order {self.fence_seen}")
        self._emit("CHK-NONVAC", "fence=" + "<".join(self.fence_seen) + f" terms={len(FENCE)}")
        waits = "{" + ",".join(sorted(self.waits_logged)) + "}"
        self._emit(
            "CHK-TIMEOUT-PATHS",
            f"waits={waits} txn_bound_ns={self.tr.timeout_ns} window_clocks={WINDOW} "
            f"idle_clocks={IDLE_CLOCKS}",
        )
        self.logger.info("RESULT %s seed=%d PASS", TEST, seed)
