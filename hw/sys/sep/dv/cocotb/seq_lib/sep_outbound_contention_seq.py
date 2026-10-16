# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Three initiators toward the outbound port, and the accounting of what leaves it.

The CPU LSU is the TB master on the LSU splice (``s_axi``), the Secure DMA is
programmed over that master, and the SMN inbound port is the TB master on
``m_axi``. Each initiator owns one slot of one 4 KiB page of the outbound
window, so a request seen at the outbound port (tap PR-OUT) is attributed to
its initiator by address. The responder (``tb/sep_outbound_mbx.sv``) answers
write bursts and reads in request order, so a response seen at the port (tap
PR-OUT-RSP) is attributed to the initiator of the request it answers by order.

Contents:

* ``Layout``: the slots, the address allocator, the read-data word of an
  address (the responder returns ``{~a, a}`` when ``smn_outbound_rd_addr_data_i``
  is 1).
* ``Txn``, ``DmaJob``: one TB-master access and one Secure DMA copy.
* ``PinWatch``: every AW/B/AR/R handshake on the pins of one TB master.
* ``ResponderDelay``: the per-cycle drive of the responder READY stall mask and
  of ``smn_outbound_resp_hold_i`` from a seeded stream.
* ``port_view``, ``id_overlap``: the attribution and the outbound-ID sweep over
  the two taps.
* ``OutboundTraffic``: runs transactions and DMA jobs on the three initiators.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from env.sep_seeded_rng import SepSeededRng

from seq_lib.sep_dma_ops import ST_DONE, STATUS, DmaTimeout, SepDmaOps, SepMemWords

INITS = ("lsu", "dma", "sysif")
SLOT_BYTES = 0x400
RESP_OKAY = 0
BURST_INCR = 1
AXSIZE_8B = 3
AXSIZE_4B = 2
# The bus carrying each initiator's own accesses, and the lowest AXI ID the
# outbound traffic of that bus uses. s_axi ID 0 is the CSR traffic of the DMA
# programming, so outbound LSU traffic starts at 1.
BUS_OF = {"lsu": "s_axi", "sysif": "m_axi"}
MIN_ID = {"s_axi": 1, "m_axi": 0}
MAGIC_WORDS = (0xA5A5_5A5A, 0xCAFE_BABE, 0xDEAD_BEEF)


def r_word(addr: int) -> int:
    """The 64-bit read data the responder returns for the beat holding ``addr``."""
    a = addr & ~7 & 0xFFFF_FFFF
    return (((~a) & 0xFFFF_FFFF) << 32) | a


def r_lane32(addr: int) -> int:
    """The 32-bit lane of ``r_word`` that a 4-byte read at ``addr`` returns."""
    return (r_word(addr) >> (32 * ((addr >> 2) & 1))) & 0xFFFF_FFFF


class Layout:
    """Slots of the outbound page and an address allocator per initiator."""

    def __init__(self, page: int) -> None:
        self.page = page
        self._next = {i: 0 for i in INITS}

    def span(self, init: str) -> tuple[int, int]:
        lo = self.page + INITS.index(init) * SLOT_BYTES
        return lo, lo + SLOT_BYTES

    def owner(self, addr: int | None) -> str | None:
        if addr is None:
            return None
        for init in INITS:
            lo, hi = self.span(init)
            if lo <= addr < hi:
                return init
        return None

    def alloc(self, init: str, nbytes: int) -> int:
        """The next 8-byte-aligned address of the slot with ``nbytes`` free; wraps."""
        step = (nbytes + 15) & ~15 if init == "dma" else (nbytes + 7) & ~7
        lo, hi = self.span(init)
        off = self._next[init]
        if off + step > hi - lo:
            off = 0
        self._next[init] = off + step
        return lo + off


@dataclass
class Txn:
    """One single-beat or INCR-burst access of a TB master."""

    init: str
    op: str  # "wr" or "rd"
    addr: int
    beats: int = 1
    axi_id: int = 0
    user: int = 0
    prot: int = 0
    wdata: bytes = b""
    name: str = ""
    resp: int = -2
    words: tuple[int, ...] = ()
    t0_ps: int = 0
    t1_ps: int = 0
    c0: int = 0
    c1: int = 0
    done: bool = False

    @property
    def latency_ns(self) -> float:
        return (self.t1_ps - self.t0_ps) / 1000.0

    def expected_words(self) -> tuple[int, ...]:
        return tuple(r_word(self.addr + 8 * k) for k in range(self.beats))


@dataclass
class DmaJob:
    """One Secure DMA copy: a write of SRAM words to the outbound slot or a read from it."""

    write: bool
    words: int
    out_addr: int
    mem_addr: int
    data: list[int] = field(default_factory=list)
    name: str = ""
    status_done: int = -1
    status_error: int = -1
    done_after_clear: int = -1
    t0_ps: int = 0
    t1_ps: int = 0
    done: bool = False
    got: list[int] = field(default_factory=list)

    @property
    def op(self) -> str:
        return "wr" if self.write else "rd"

    @property
    def latency_ns(self) -> float:
        return (self.t1_ps - self.t0_ps) / 1000.0

    def expected_words(self) -> list[int]:
        return [r_lane32(self.out_addr + 4 * i) for i in range(self.words)]


def _bit(sig) -> bool:
    try:
        return bool(int(sig.value))
    except ValueError:
        return False


def _int(sig) -> int:
    try:
        return int(sig.value)
    except ValueError:
        return -1


class PinWatch:
    """Every AW, B, AR and R handshake on the pins of one TB master."""

    NAMES = (
        "awvalid",
        "awready",
        "awid",
        "awaddr",
        "bvalid",
        "bready",
        "bid",
        "bresp",
        "arvalid",
        "arready",
        "arid",
        "araddr",
        "rvalid",
        "rready",
        "rid",
        "rresp",
        "rdata",
        "rlast",
    )

    def __init__(self, bus: str) -> None:
        self.bus = bus
        self.cycles = 0
        self.aw: list[tuple[int, int, int]] = []  # (cycle, id, addr)
        self.b: list[tuple[int, int, int]] = []  # (cycle, id, resp)
        self.ar: list[tuple[int, int, int]] = []
        self.r: list[tuple[int, int, int, int, int]] = []  # (cycle, id, resp, data, last)
        self.aw_stall = 0
        self.ar_stall = 0
        self._task = None

    def start(self) -> "PinWatch":
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    async def _run(self) -> None:
        dut = cocotb.top
        s = {n: getattr(dut, f"{self.bus}_{n}") for n in self.NAMES}
        while True:
            await RisingEdge(dut.clk_i)
            self.cycles += 1
            c = self.cycles
            if _bit(s["awvalid"]):
                if _bit(s["awready"]):
                    self.aw.append((c, _int(s["awid"]), _int(s["awaddr"])))
                else:
                    self.aw_stall += 1
            if _bit(s["arvalid"]):
                if _bit(s["arready"]):
                    self.ar.append((c, _int(s["arid"]), _int(s["araddr"])))
                else:
                    self.ar_stall += 1
            if _bit(s["bvalid"]) and _bit(s["bready"]):
                self.b.append((c, _int(s["bid"]), _int(s["bresp"])))
            if _bit(s["rvalid"]) and _bit(s["rready"]):
                self.r.append(
                    (c, _int(s["rid"]), _int(s["rresp"]), _int(s["rdata"]), _int(s["rlast"]))
                )

    def mark(self) -> tuple[int, int, int, int]:
        return len(self.aw), len(self.b), len(self.ar), len(self.r)

    def since(self, mark: tuple[int, int, int, int]) -> dict:
        """The handshakes after ``mark`` on IDs at or above this bus's outbound floor."""
        lo = MIN_ID[self.bus]
        aw = [x for x in self.aw[mark[0] :] if x[1] >= lo]
        b = [x for x in self.b[mark[1] :] if x[1] >= lo]
        ar = [x for x in self.ar[mark[2] :] if x[1] >= lo]
        r = [x for x in self.r[mark[3] :] if x[1] >= lo]
        return {
            "aw": len(aw),
            "b": len(b),
            "b_resp": [x[2] for x in b],
            "ar": len(ar),
            "r": len(r),
            "r_data": [x[3] for x in r],
            "r_resp": [x[2] for x in r],
            "rlast": sum(1 for x in r if x[4] == 1),
            "r_last_flags": [x[4] for x in r],
        }


class PortStall:
    """Clocks of VALID without READY on AW, W and AR at the outbound port (tap PR-OUT)."""

    def __init__(self) -> None:
        self.n = {"aw": 0, "w": 0, "ar": 0}
        self._task = None

    def start(self) -> "PortStall":
        self._task = cocotb.start_soon(self._run())
        return self

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None

    def snap(self) -> dict:
        return dict(self.n)

    async def _run(self) -> None:
        dut = cocotb.top
        sig = {
            ch: (getattr(dut, f"pr_out_{ch}valid_o"), getattr(dut, f"pr_out_{ch}ready_o"))
            for ch in self.n
        }
        while True:
            await RisingEdge(dut.clk_i)
            for ch, (v, r) in sig.items():
                if _bit(v) and not _bit(r):
                    self.n[ch] += 1


class ResponderDelay:
    """Drives the responder READY stall mask and the B/R hold, one draw per clock.

    ``p_stall`` is the percent chance per clock that AW, W and AR READY of the
    responder are low. The hold starts with ``p_hold`` percent chance per clock
    and lasts 1 to ``hold_max`` clocks; B and R VALID stay low while it is up.
    """

    def __init__(
        self, rng: SepSeededRng, p_stall: tuple[int, int, int], p_hold: int, hold_max: int
    ):
        self.rng = rng
        self.p_stall = p_stall
        self.p_hold = p_hold
        self.hold_max = hold_max
        self.hold_clocks = 0
        self.stall_clocks = [0, 0, 0]
        self._task = None

    def describe(self) -> str:
        return (
            f"p_stall_aw={self.p_stall[0]} p_stall_w={self.p_stall[1]} "
            f"p_stall_ar={self.p_stall[2]} p_hold={self.p_hold} hold_max={self.hold_max}"
        )

    def start(self) -> None:
        self._task = cocotb.start_soon(self._run())

    def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            self._task = None
        dut = cocotb.top
        dut.smn_outbound_ready_stall_i.value = 0
        dut.smn_outbound_resp_hold_i.value = 0

    async def _run(self) -> None:
        dut = cocotb.top
        left = 0
        while True:
            await RisingEdge(dut.clk_i)
            mask = 0
            for bit, p in enumerate(self.p_stall):
                if p and self.rng.randrange(100) < p:
                    mask |= 1 << bit
                    self.stall_clocks[bit] += 1
            if left:
                left -= 1
                hold = 1
            elif self.p_hold and self.rng.randrange(100) < self.p_hold:
                left = self.rng.randrange(1, self.hold_max + 1) - 1
                hold = 1
            else:
                hold = 0
            self.hold_clocks += hold
            dut.smn_outbound_ready_stall_i.value = mask
            dut.smn_outbound_resp_hold_i.value = hold


@dataclass
class Req:
    """One request accepted at the outbound port."""

    init: str | None
    kind: str  # "wr" or "rd"
    id: int | None
    addr: int | None
    length: int | None
    user: int | None
    prot: int | None
    t_ps: int
    unknown: bool
    t_done_ps: float = float("inf")


@dataclass
class PortView:
    """The beats of one window at the outbound port, attributed by initiator."""

    reqs: list[Req]
    w_total: int
    w_by_init: dict[str, int]
    b_by_init: dict[str, int]
    r_beats_by_init: dict[str, int]
    r_data_by_init: dict[str, list[int]]
    r_reads_by_init: dict[str, list[list[int]]]
    rlast_ok: dict[str, int]
    b_total: int
    r_total: int
    b_unmatched: int
    r_unmatched: int
    unknown: int
    unattributed: int

    def n_req(self, init: str, kind: str) -> int:
        return sum(1 for r in self.reqs if r.init == init and r.kind == kind)

    def req_beats(self, init: str, kind: str) -> int:
        return sum((r.length or 0) + 1 for r in self.reqs if r.init == init and r.kind == kind)

    def addrs(self, init: str, kind: str) -> list[int]:
        return sorted(r.addr for r in self.reqs if r.init == init and r.kind == kind)

    def lens(self, init: str, kind: str) -> list[int]:
        return [r.length for r in self.reqs if r.init == init and r.kind == kind]


def port_view(layout: Layout, out_beats, rsp_beats) -> PortView:
    """Attribute the beats of PR-OUT and PR-OUT-RSP to the initiators."""
    aws, ars, ws = [], [], []
    unknown = 0
    for b in out_beats:
        if b.has_unknown():
            unknown += 1
        if b.ch == "w":
            ws.append(b)
            continue
        kind = "wr" if b.ch == "aw" else "rd"
        req = Req(
            layout.owner(b.fields.get("addr")),
            kind,
            b.fields.get("id"),
            b.fields.get("addr"),
            b.fields.get("len"),
            b.fields.get("user"),
            b.fields.get("prot"),
            b.t_ps,
            b.has_unknown(),
        )
        (aws if kind == "wr" else ars).append(req)
    reqs = aws + ars
    w_by = {i: 0 for i in INITS}
    pos = 0
    for r in aws:
        n = (r.length or 0) + 1
        if r.init is not None:
            w_by[r.init] += len(ws[pos : pos + n])
        pos += n
    b_by = {i: 0 for i in INITS}
    rb_by = {i: 0 for i in INITS}
    rd_by: dict[str, list[int]] = {i: [] for i in INITS}
    rreads: dict[str, list[list[int]]] = {i: [] for i in INITS}
    rlast_ok = {i: 0 for i in INITS}
    bs = [b for b in rsp_beats if b.ch == "b"]
    rs = [b for b in rsp_beats if b.ch == "r"]
    for b in bs:
        if b.has_unknown():
            unknown += 1
    for r in rs:
        if r.has_unknown():
            unknown += 1
    for k, req in enumerate(aws):
        if k < len(bs):
            req.t_done_ps = bs[k].t_ps
            if req.init is not None:
                b_by[req.init] += 1
    pos = 0
    for req in ars:
        n = (req.length or 0) + 1
        grp = rs[pos : pos + n]
        pos += n
        if len(grp) == n:
            req.t_done_ps = grp[-1].t_ps
        if req.init is None:
            continue
        rb_by[req.init] += len(grp)
        rd_by[req.init].extend(g.fields.get("data") for g in grp)
        rreads[req.init].append([g.fields.get("data") for g in grp])
        flags = [g.fields.get("last") for g in grp]
        if len(grp) == n and flags == [0] * (n - 1) + [1]:
            rlast_ok[req.init] += 1
    return PortView(
        reqs=reqs,
        w_total=len(ws),
        w_by_init=w_by,
        b_by_init=b_by,
        r_beats_by_init=rb_by,
        r_data_by_init=rd_by,
        r_reads_by_init=rreads,
        rlast_ok=rlast_ok,
        b_total=len(bs),
        r_total=len(rs),
        b_unmatched=max(0, len(bs) - len(aws)),
        r_unmatched=max(0, len(rs) - pos),
        unknown=unknown,
        unattributed=sum(1 for r in reqs if r.init is None),
    )


def id_overlap(view: PortView) -> tuple[int, int, dict[str, set[int]]]:
    """(overlapping pairs from different initiators, those with one ID, ID sets)."""
    reqs = [r for r in view.reqs if r.init is not None]
    pairs = collisions = 0
    for i, a in enumerate(reqs):
        for b in reqs[i + 1 :]:
            if a.init == b.init:
                continue
            if a.t_ps < b.t_done_ps and b.t_ps < a.t_done_ps:
                pairs += 1
                if a.id == b.id:
                    collisions += 1
    ids: dict[str, set[int]] = {i: set() for i in INITS}
    for r in reqs:
        ids[r.init].add(r.id)
    return pairs, collisions, ids


class OutboundTraffic:
    """Runs transactions and DMA jobs on the three initiators of one leaf."""

    def __init__(self, test, layout: Layout, state_fn) -> None:
        self.test = test
        self.layout = layout
        self.state_fn = state_fn
        self.log = test.logger
        self.timeout_ns = int(test.cfg.axi_timeout_ns)
        self.dma = SepDmaOps(test)
        self.mem = SepMemWords(test)
        self.dma_polls_max = 0

    def master(self, bus: str):
        agent = self.test.env.axi_agent if bus == "s_axi" else self.test.env.ext_axi_agent
        seq = getattr(getattr(agent, "driver", None), "axi", None)
        if seq is None or not hasattr(seq, "read_bytes_result"):
            raise RuntimeError(f"no VIP master sequence behind the {bus} agent")
        return seq

    @staticmethod
    def _now_ps() -> int:
        return int(get_sim_time("ps"))

    async def run_txn(self, t: Txn, *, delay: int = 0, watch: PinWatch | None = None) -> Txn:
        """One access on the bus of ``t.init``; fails with the last port state on expiry."""
        if delay:
            await ClockCycles(cocotb.top.clk_i, delay)
        master = self.master(BUS_OF[t.init])
        t.t0_ps = self._now_ps()
        t.c0 = watch.cycles if watch is not None else 0
        burst = BURST_INCR if t.beats > 1 else None
        try:
            if t.op == "wr":
                res = await master.write_bytes_result(
                    t.addr,
                    t.wdata,
                    size=AXSIZE_8B,
                    burst=burst,
                    id=t.axi_id,
                    prot=t.prot,
                    user=t.user,
                    check_response=False,
                    timeout_ns=self.timeout_ns,
                )
            else:
                res = await master.read_bytes_result(
                    t.addr,
                    8 * t.beats,
                    size=AXSIZE_8B,
                    burst=burst,
                    id=t.axi_id,
                    prot=t.prot,
                    user=t.user,
                    check_response=False,
                    timeout_ns=self.timeout_ns,
                )
        except AssertionError as exc:
            raise AssertionError(
                f"TIMEOUT initiator={t.init} txn={t.name} {t.op} addr=0x{t.addr:x} "
                f"beats={t.beats} id={t.axi_id} bound_ns={self.timeout_ns} "
                f"last_port_state={self.state_fn()} detail={exc}"
            ) from exc
        t.t1_ps = self._now_ps()
        t.c1 = watch.cycles if watch is not None else 0
        t.resp = int(res.resp)
        if t.op == "rd":
            t.words = tuple(res.data_words)
        t.done = True
        return t

    async def dma_prepare(self, job: DmaJob) -> None:
        """Clean state, stage the source words, program the transfer registers."""
        await self.dma.clean_state()
        if job.write:
            await self.mem.fill(job.mem_addr, job.data)
            src, dst = job.mem_addr, job.out_addr
        else:
            src, dst = job.out_addr, job.mem_addr
        total = 4 * job.words
        await self.dma.program_transfer(src=src, dst=dst, total=total, chunk=total)

    async def dma_run(self, job: DmaJob, *, delay: int = 0) -> DmaJob:
        """GO after ``delay`` clocks, wait for DONE, then (reads) take the copied words."""
        if delay:
            await ClockCycles(cocotb.top.clk_i, delay)
        total = 4 * job.words
        job.t0_ps = self._now_ps()
        await self.dma.go()
        try:
            res = await self.dma.run_to_done(total, tag=f" {job.name}")
        except DmaTimeout as exc:
            raise AssertionError(
                f"TIMEOUT initiator=dma txn={job.name} {job.op} addr=0x{job.out_addr:x} "
                f"words={job.words} bound_polls={self.dma.done_bound(total)} "
                f"last_port_state={self.state_fn()} detail={exc}"
            ) from exc
        job.t1_ps = self._now_ps()
        job.status_done = res.status.done
        job.status_error = res.status.error
        self.dma_polls_max = max(self.dma_polls_max, res.polls)
        job.done = True
        return job

    async def dma_finish(self, job: DmaJob) -> None:
        """Clear DONE with the RW1C write and read it back; (reads) read the copied words."""
        await self.dma.wr(STATUS, ST_DONE)
        job.done_after_clear = (await self.dma.read_status()).done
        if not job.write:
            job.got = await self.mem.read(job.mem_addr, job.words)


async def run_all(coros) -> None:
    """Run the coroutines together; raise the first failure once every one has finished."""
    failures: list[BaseException] = []

    async def _one(coro):
        try:
            await coro
        except BaseException as exc:  # noqa: BLE001 - re-raised below
            failures.append(exc)

    tasks = [cocotb.start_soon(_one(c)) for c in coros]
    for t in tasks:
        await t
    if failures:
        raise failures[0]
