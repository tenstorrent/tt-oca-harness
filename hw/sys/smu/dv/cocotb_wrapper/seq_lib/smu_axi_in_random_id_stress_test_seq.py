# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Seeded random-ID, random-size stream from the SMN port into the SMC SPM, with JTAG2AXI egress.

The stream writes and reads the SMC SPM through inbound filter entry 0 with random AXI IDs over
the whole ID width of the port, random AxSIZE 0..3 and AxLEN 0..3 INCR bursts, several IDs in
flight at once and random RREADY and BREADY hold-backs. Eight JTAG2AXI writes to addresses outside
both SMU apertures leave on ``smu_axi_out`` while the stream runs.

AMBA AXI4 specification, ordering model: a response carries the ID of its request, and responses
with one ID return in the order of their requests. ``hw/sys/smc/doc/fabric.adoc`` "AXI Transaction
ID widths" states that each fabric stage prepends ID bits and the IDs a master sees are its own.

S1: TAP reset, JTAG2AXI gate open, SMC aperture routed to its local alias, entry 0 over the SPM
    window, the external master, the ID width of the bound ``ext_in_awid`` and the seed.
S2: every SPM block is filled with seeded bytes, then the stream: writes of random byte ranges at
    distinct blocks and reads of other blocks, in waves of three to eight transactions, while the
    JTAG2AXI egress writes run.
S3: per-ID scoreboard sampled on the ``ext_in`` pins: BID and RID echo, request order per ID.
S4: read-back of every written block under the ID that wrote it.
S5: the eight egress writes complete, each crosses ``smu_axi_out`` once, and the responder
    memory holds each word.
S6: every bounded wait reports its bound and last state.
"""

from __future__ import annotations

import random
from collections import Counter, deque
from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, Event, RisingEdge, with_timeout
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_OKAY, AxiTimingProfile, resp_name, worst_resp
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_axi_helpers import AXI_TIMEOUT_NS, make_smu_axi_master
from seq_lib.smu_filter_helpers import (
    page_align_window,
    program_inbound0_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_8B,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_tb_pins import smc_primary_reset, smu_axi_in_prefix

# hw/sys/smc/regs/gen/c/smc_addr.h: the SPM window the entry is programmed over.
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SPM_SIZE = smc_addr("SMC_TOP_SPM_MEMORY_SIZE")

# hw/sys/smc/doc/fabric.adoc "AXI Common Signal Widths": DATA_WIDTH 64, so one beat is at most 8
# bytes (AxSIZE 3) and an AxLEN 3 INCR burst spans at most 32 bytes.
BUS_BYTES = 8
SIZE_COUNT = 4
MAX_BEATS = 4
BLOCK_BYTES = MAX_BEATS * BUS_BYTES
LANE_MASK = BUS_BYTES - 1

# Blocks of the SPM the stream owns, at a 4 KB offset inside the window so no burst crosses a 4 KB
# boundary. Each written block is touched by one write only.
AREA_OFFSET = 0x1000
AREA_BASE = SPM_BASE + AREA_OFFSET
WRITE_BLOCKS = 48
READ_BLOCKS = 24
TAIL_READS = 6
BLOCK_COUNT = WRITE_BLOCKS + READ_BLOCKS + TAIL_READS
AREA_BYTES = BLOCK_COUNT * BLOCK_BYTES
BYTE_VALUES = 256

# Stream shape stated in the Objective and Test Coverage of this leaf's card in
# hw/sys/smu/dv/docs/SMU_VPLAN.adoc.
MIN_STREAM_LENGTH = 64
MIN_DISTINCT_IDS = 3
MIN_DISTINCT_SIZES = 2
MIN_DISCRIMINATING_PAIRS = 3
MIN_WAVE = 3
MAX_WAVE = 8
ID_POOL_SIZE = 8
ID_POOL_DRAWS = 64
MAX_READY_HOLD_CYCLES = 24
IDLE_CYCLES = 4

# The width of ext_in_awid on the bench top bounds the IDs the port accepts;
# hw/sys/smu/doc/port_table.adoc names the port type without a width and the integrator chapter
# gives none.
ID_SIGNALS = ("awid", "arid", "bid", "rid")

# hw/sys/smu/doc/index.adoc "AXI Crossbar": an SMC address outside both apertures leaves on
# smu_axi_out. Eight doublewords at a 256-byte stride above the 0xAA.. pattern.
ADDR_MASK = (1 << 56) - 1
EGRESS_BASE = 0xAA_AAAA_AAAA_A000 & ADDR_MASK
EGRESS_STRIDE = 0x100
EGRESS_COUNT = 8
EGRESS_STROBE_ALL = 0xFF
J2A_POLL_LIMIT = 128
EGRESS_POLL_CYCLES = 4000
LAUNCH_BOUND_NS = 4 * AXI_TIMEOUT_NS
JOIN_BOUND_NS = 4 * LAUNCH_BOUND_NS
J2A_ACCESS_COUNT = 2 + 3 + EGRESS_COUNT
J2A_ACCESS_BUDGET = 20

STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
EXPECTED_SITES = (
    "j2a_aperture_alias",
    "j2a_window",
    "j2a_egress_write",
    "ext_response_wait",
    "egress_launch_gate",
    "responder_observation",
    "egress_join",
)


@dataclass
class _Req:
    write: bool
    addr: int
    nbytes: int
    size: int
    tid: int
    data: bytes = b""


def _high(pin) -> bool:
    return str(pin.value) == "1"


def _int(pin, name: str) -> int:
    val = pin.value
    if not val.is_resolvable:
        raise AssertionError(f"X/Z on {name}: {val}")
    return int(val)


class _InPortTrace:
    """Every handshake on the ext_in port, sampled on the DUT pins at each clk_smu_i edge.

    A response is matched to the oldest outstanding request of its ID, so a response carrying an
    ID with no outstanding request is recorded as unmatched and a read whose beats differ from the
    oldest same-ID request is recorded as out of order.
    """

    def __init__(self, dut, clk, expect_read) -> None:
        prefix = smu_axi_in_prefix(dut)
        self._pins = {}
        for name in (
            *ID_SIGNALS,
            "awvalid",
            "awready",
            "awaddr",
            "awlen",
            "awsize",
            "arvalid",
            "arready",
            "araddr",
            "arlen",
            "arsize",
            "wvalid",
            "wready",
            "wstrb",
            "bvalid",
            "bready",
            "rvalid",
            "rready",
            "rdata",
            "rlast",
        ):
            pin = getattr(dut, f"{prefix}_{name}", None)
            if pin is None:
                raise AssertionError(f"{prefix}_{name} unobservable on this tb_top")
            self._pins[name] = pin
        self._clk = clk
        self._expect_read = expect_read
        self.out_w: dict[int, deque] = {}
        self.out_r: dict[int, deque] = {}
        self.aw_count: Counter = Counter()
        self.ar_count: Counter = Counter()
        self.b_count: Counter = Counter()
        self.r_count: Counter = Counter()
        self.sizes: set[int] = set()
        self.lens: set[int] = set()
        self.wstrbs: Counter = Counter()
        self.unmatched: list = []
        self.misordered: list = []
        self.discriminating = 0
        self.max_ids_in_flight = 0
        self.max_in_flight = 0
        self.stamps: list[float] = []
        self._beats: dict[int, list[int]] = {}
        self._task = cocotb.start_soon(self._watch())

    def _p(self, name: str) -> int:
        return _int(self._pins[name], name)

    def _in_flight(self) -> None:
        ids = {i for q in (self.out_w, self.out_r) for i, d in q.items() if d}
        total = sum(len(d) for q in (self.out_w, self.out_r) for d in q.values())
        self.max_ids_in_flight = max(self.max_ids_in_flight, len(ids))
        self.max_in_flight = max(self.max_in_flight, total)

    def _read_done(self, rid: int, beats: list[int]) -> None:
        queue = self.out_r.get(rid)
        if not queue:
            self.unmatched.append(("R", rid))
            return
        addr, length, size = queue.popleft()
        want = self._expect_read(addr, length, size)
        got = [(b ^ e) & m for b, (e, m) in zip(beats, want)]
        if len(beats) != length + 1 or any(got):
            self.misordered.append((rid, hex(addr), length + 1, len(beats)))
        for other in queue:
            if self._expect_read(*other) != want:
                self.discriminating += 1
                break

    async def _watch(self) -> None:
        pins = self._pins
        while True:
            await RisingEdge(self._clk)
            now = get_sim_time("ns")
            if _high(pins["awvalid"]) and _high(pins["awready"]):
                tid = self._p("awid")
                self.out_w.setdefault(tid, deque()).append(self._p("awaddr"))
                self.aw_count[tid] += 1
                self.sizes.add(self._p("awsize"))
                self.lens.add(self._p("awlen"))
                self.stamps.append(now)
            if _high(pins["arvalid"]) and _high(pins["arready"]):
                tid = self._p("arid")
                req = (self._p("araddr"), self._p("arlen"), self._p("arsize"))
                self.out_r.setdefault(tid, deque()).append(req)
                self.ar_count[tid] += 1
                self.sizes.add(req[2])
                self.lens.add(req[1])
                self.stamps.append(now)
            self._in_flight()
            if _high(pins["wvalid"]) and _high(pins["wready"]):
                self.wstrbs[self._p("wstrb")] += 1
            if _high(pins["bvalid"]) and _high(pins["bready"]):
                tid = self._p("bid")
                queue = self.out_w.get(tid)
                if queue:
                    queue.popleft()
                else:
                    self.unmatched.append(("B", tid))
                self.b_count[tid] += 1
                self.stamps.append(now)
            if _high(pins["rvalid"]) and _high(pins["rready"]):
                tid = self._p("rid")
                self._beats.setdefault(tid, []).append(self._p("rdata"))
                if _high(pins["rlast"]):
                    self.r_count[tid] += 1
                    self._read_done(tid, self._beats.pop(tid))
                    self.stamps.append(now)

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class _OutboundTap:
    """Every AW handshake and B response on the smu_axi_out boundary interface."""

    def __init__(self, dut) -> None:
        self._if = dut.u_axi_out_if
        self._clk = dut.clk_smu_i
        self.aw_addrs: list[int] = []
        self.b_resps: list[int] = []
        self._task = cocotb.start_soon(self._watch())

    def _int(self, name: str) -> int:
        return _int(getattr(self._if, name), f"u_axi_out_if.{name}")

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._clk)
            if self._int("awvalid") and self._int("awready"):
                self.aw_addrs.append(self._int("awaddr"))
            if self._int("bvalid") and self._int("bready"):
                self.b_resps.append(self._int("bresp"))

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class smu_axi_in_random_id_stress_test_seq:
    """Seeded random-ID stream into the SPM with concurrent JTAG2AXI egress writes."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.clk = cocotb.top.clk_smu_i
        self.seed = test.random_seed()
        self.rng = random.Random(self.seed)
        self.jtag = None
        self.master = None
        self.trace: _InPortTrace | None = None
        self.tap: _OutboundTap | None = None
        self.step_ts: dict[str, float] = {}
        self.sites: dict[str, dict] = {}
        self.seed_logged = False
        self.id_width = 0
        self.pool: list[int] = []
        self.fill = bytes(self.rng.randrange(BYTE_VALUES) for _ in range(AREA_BYTES))
        self.mem = bytearray(self.fill)
        self.issued: Counter = Counter()
        self.issued_ids: list[int] = []
        self.written: dict[int, int] = {}
        self.bad_resp: list = []
        self.stream_sizes: set[int] = set()
        self.stream_lens: set[int] = set()
        self.partial_strobe_writes = 0
        self.ready_holds: list[tuple[int, int]] = []
        self.egress = [
            (EGRESS_BASE + EGRESS_STRIDE * k, self.rng.getrandbits(64) | 1)
            for k in range(EGRESS_COUNT)
        ]
        self.egress_started = [Event() for _ in range(EGRESS_COUNT)]
        self.egress_windows: list[tuple[float, float]] = []
        self.egress_status: list[int] = []
        self.egress_task = None
        self.j2a_accesses = 0
        self.stream_waves = 0
        self.stream_len = 0

    def _log(self, msg: str) -> None:
        cocotb.log.info(msg)

    async def _mark(self, step: str, text: str) -> None:
        await RisingEdge(self.clk)
        self.step_ts[step] = get_sim_time("ns")
        self._log(f"STEP {step}: {text}")

    def _site(self, name: str, bound: int, used: int | None, last: str, unit: str) -> None:
        """Record one bounded wait; ``used`` None means the count is not measurable."""
        site = self.sites.setdefault(
            name,
            {"bound": bound, "used": 0, "last": last, "unit": unit, "count": 0, "measured": True},
        )
        site["count"] += 1
        if used is None:
            site["measured"] = False
        else:
            site["used"] = max(site["used"], used)
        site["last"] = last

    def _chk(self, sb, chk: str, name: str, observed, expected, text: str) -> None:
        self._log(f"{chk}: {text} observed={observed} expected={expected}")
        sb.expect_eq(f"{chk} {name}", observed, expected, evidence=chk)

    # ------------------------------------------------------------------
    # Model of the SPM area.
    # ------------------------------------------------------------------

    def _beat_expect(self, addr: int, length: int, size: int) -> list[tuple[int, int]]:
        """(expected data, lane mask) of each beat of a read, from the model bytes."""
        step = 1 << size
        beats = []
        for beat in range(length + 1):
            lo = addr + beat * step
            off = lo - AREA_BASE
            lane = (lo & LANE_MASK) * 8
            word = int.from_bytes(self.mem[off : off + step], "little") << lane
            beats.append((word, ((1 << (8 * step)) - 1) << lane))
        return beats

    def _draw_pool(self) -> list[int]:
        count = min(ID_POOL_SIZE, 1 << self.id_width)
        for _ in range(ID_POOL_DRAWS):
            pool = self.rng.sample(range(1 << self.id_width), count)
            if self._bits_span(pool):
                return pool
        raise AssertionError(f"no ID pool spanning {self.id_width} bits in {ID_POOL_DRAWS} draws")

    def _bits_span(self, ids) -> bool:
        return all(
            any((i >> bit) & 1 for i in ids) and any(not (i >> bit) & 1 for i in ids)
            for bit in range(self.id_width)
        )

    def _plan_write(self, block: int, tid: int) -> _Req:
        size = self.rng.randrange(SIZE_COUNT)
        step = 1 << size
        beats = self.rng.randint(1, MAX_BEATS)
        off = self.rng.randrange(step)
        lo = max(1, (beats - 1) * step - off + 1)
        count = self.rng.randint(lo, beats * step - off)
        base = block * BLOCK_BYTES + off
        data = bytes(self.fill[base + i] ^ self.rng.randrange(1, BYTE_VALUES) for i in range(count))
        self.mem[base : base + count] = data
        self.written[block] = tid
        if size < SIZE_COUNT - 1 or count != beats * BUS_BYTES:
            self.partial_strobe_writes += 1
        return _Req(True, AREA_BASE + base, count, size, tid, data)

    def _plan_read(self, block: int, tid: int, full: bool = False) -> _Req:
        size = SIZE_COUNT - 1 if full else self.rng.randrange(SIZE_COUNT)
        step = 1 << size
        beats = MAX_BEATS if full else self.rng.randint(1, MAX_BEATS)
        off = step * self.rng.randrange((BLOCK_BYTES - beats * step) // step + 1)
        return _Req(False, AREA_BASE + block * BLOCK_BYTES + off, beats * step, size, tid)

    # ------------------------------------------------------------------
    # External master waves.
    # ------------------------------------------------------------------

    async def _wave(self, reqs: list[_Req], stream: bool) -> list:
        holds = (
            self.rng.randrange(MAX_READY_HOLD_CYCLES + 1),
            self.rng.randrange(MAX_READY_HOLD_CYCLES + 1),
        )
        self.ready_holds.append(holds)
        self.master.driver.set_timing(
            AxiTimingProfile(b_ready_delay=holds[0], r_ready_delay=holds[1])
        )
        events = []
        for req in reqs:
            if req.write:
                events.append(self.master.init_write(req.addr, req.data, size=req.size, id=req.tid))
            else:
                events.append(
                    self.master.init_read(req.addr, req.nbytes, size=req.size, id=req.tid)
                )
            self.issued[(req.write, req.tid)] += 1
            self.issued_ids.append(req.tid)
            if stream:
                self.stream_sizes.add(req.size)
                step = 1 << req.size
                self.stream_lens.add((req.addr % step + req.nbytes + step - 1) // step - 1)
        t0 = get_sim_time("ns")
        for req, event in zip(reqs, events):
            try:
                await with_timeout(event.wait(), AXI_TIMEOUT_NS, "ns")
            except Exception as exc:
                self._site(
                    "ext_response_wait",
                    AXI_TIMEOUT_NS,
                    AXI_TIMEOUT_NS + 1,
                    f"EXPIRED addr=0x{req.addr:x} id={req.tid}",
                    "ns",
                )
                raise AssertionError(
                    f"TIMEOUT ext response addr=0x{req.addr:x} id={req.tid} "
                    f"bound={AXI_TIMEOUT_NS}ns: {exc}"
                ) from exc
        used = int(get_sim_time("ns") - t0)
        self._site(
            "ext_response_wait",
            AXI_TIMEOUT_NS,
            used,
            f"{len(reqs)} responses, hold bready={holds[0]} rready={holds[1]}",
            "ns",
        )
        self.master.driver.set_timing(AxiTimingProfile())
        await ClockCycles(self.clk, IDLE_CYCLES)
        results = []
        for req, event in zip(reqs, events):
            raw = event.data
            resp = worst_resp(getattr(raw, "resp", None))
            if resp != RESP_OKAY:
                self.bad_resp.append((req.write, hex(req.addr), req.tid, resp_name(resp)))
            results.append(bytes(getattr(raw, "data", b"")))
        return results

    async def _gate(self, index: int) -> None:
        event = self.egress_started[min(index, EGRESS_COUNT - 1)]
        t0 = get_sim_time("ns")
        try:
            await with_timeout(event.wait(), LAUNCH_BOUND_NS, "ns")
        except Exception as exc:
            self._site(
                "egress_launch_gate",
                LAUNCH_BOUND_NS,
                LAUNCH_BOUND_NS + 1,
                f"EXPIRED waiting for egress write {index}",
                "ns",
            )
            if self.egress_task is not None and self.egress_task.done():
                raise AssertionError(f"egress task ended before launch {index}") from exc
            raise AssertionError(f"TIMEOUT egress launch {index}: {exc}") from exc
        self._site(
            "egress_launch_gate",
            LAUNCH_BOUND_NS,
            int(get_sim_time("ns") - t0),
            f"egress write {min(index, EGRESS_COUNT - 1)} launched",
            "ns",
        )

    def _chunks(self, items: list) -> list[list]:
        out, pos = [], 0
        while pos < len(items):
            size = self.rng.randint(MIN_WAVE, MAX_WAVE)
            out.append(items[pos : pos + size])
            pos += size
        return out

    # ------------------------------------------------------------------
    # JTAG2AXI egress.
    # ------------------------------------------------------------------

    async def _j2a_write(self, tag: str, addr: int, data: int, **kw) -> int:
        t0 = get_sim_time("ns")
        try:
            status, _ = await jtag2axi_single_write(
                self.jtag, addr, data, poll_limit=J2A_POLL_LIMIT, require_complete=True, **kw
            )
        except TimeoutError as exc:
            self._site(f"j2a_{tag}", J2A_POLL_LIMIT, J2A_POLL_LIMIT + 1, f"EXPIRED {exc}", "polls")
            raise
        require_jtag_tdo_resolved(f"J2A {tag} @0x{addr:x}")
        elapsed = int((get_sim_time("ns") - t0) / self.cfg.smu_clk_period_ns)
        self._site(
            f"j2a_{tag}",
            J2A_POLL_LIMIT,
            None,
            f"status={status} addr=0x{addr:x} elapsed_clk={elapsed} (measured); "
            "used polls: not measured",
            "polls",
        )
        self.j2a_accesses += 1
        return status

    async def _j2a_helper(self, tag: str, accesses: int, call, note: str = ""):
        t0 = get_sim_time("ns")
        try:
            result = await call
        except TimeoutError as exc:
            self._site(f"j2a_{tag}", J2A_POLL_LIMIT, J2A_POLL_LIMIT + 1, f"EXPIRED {exc}", "polls")
            raise
        elapsed = int((get_sim_time("ns") - t0) / self.cfg.smu_clk_period_ns)
        self._site(
            f"j2a_{tag}",
            J2A_POLL_LIMIT,
            None,
            f"{accesses} accesses SUCCESS {note} elapsed_clk={elapsed} (measured); "
            "used polls: not measured",
            "polls",
        )
        self.j2a_accesses += accesses
        return result

    async def _egress_writes(self) -> None:
        for k, (addr, value) in enumerate(self.egress):
            before = len(self.tap.aw_addrs)
            t0 = get_sim_time("ns")
            self.egress_started[k].set()
            status = await self._j2a_write(
                "egress_write", addr, value, wstrb=EGRESS_STROBE_ALL, size=SMC_DBG_AXSIZE_8B
            )
            self.egress_windows.append((t0, get_sim_time("ns")))
            self.egress_status.append(status)
            last = before
            for cycle in range(1, EGRESS_POLL_CYCLES + 1):
                last = len(self.tap.aw_addrs)
                if last > before:
                    self._site(
                        "responder_observation",
                        EGRESS_POLL_CYCLES,
                        cycle,
                        f"write {k} addr=0x{addr:014x} seen, aw_count={last}",
                        "clk",
                    )
                    break
                await RisingEdge(self.clk)
            else:
                self._site(
                    "responder_observation",
                    EGRESS_POLL_CYCLES,
                    EGRESS_POLL_CYCLES + 1,
                    f"EXPIRED write {k} aw_count={last}",
                    "clk",
                )
                raise AssertionError(f"TIMEOUT responder observation of egress write {k}")

    # ------------------------------------------------------------------
    # Steps.
    # ------------------------------------------------------------------

    async def _s1(self, sb) -> None:
        dut = self.dut
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        gate_pin = dut.tb_smc_jtag2axi_security_disable
        if not gate_pin.value.is_resolvable or (int(gate_pin.value) & 1) != 0:
            raise AssertionError(f"SMC J2A gated after TCK sync: {gate_pin.value}")
        readback = await self._j2a_helper(
            "aperture_alias", 2, program_smc_aperture_local_alias(self.jtag, scoreboard=sb)
        )
        lo, hi = page_align_window(SPM_BASE, SPM_BASE + SPM_SIZE - 1)
        await self._j2a_helper(
            "window",
            3,
            program_inbound0_window(self.jtag, lo, hi, scoreboard=sb, tag="SPM"),
            f"readback GLOBAL_BASE=0x{readback:08x}",
        )
        prefix = smu_axi_in_prefix(dut)
        widths = {len(getattr(dut, f"{prefix}_{name}")) for name in ID_SIGNALS}
        if len(widths) != 1:
            raise AssertionError(f"ext_in ID widths differ: {sorted(widths)}")
        self.id_width = widths.pop()
        self.pool = self._draw_pool()
        self.master = await make_smu_axi_master(dut, self.clk, smc_primary_reset(dut))
        self.trace = _InPortTrace(dut, self.clk, self._beat_expect)
        self.tap = _OutboundTap(dut)
        self._log(
            f"SEED: RANDOM_SEED={self.seed} id_width={self.id_width} "
            f"pool={[hex(i) for i in self.pool]} window=[0x{lo:x},0x{hi:x}] "
            f"area=0x{AREA_BASE:x}+0x{AREA_BYTES:x}"
        )
        self.seed_logged = True

    async def _s2(self, sb) -> None:
        fill = [
            _Req(True, AREA_BASE + b * BLOCK_BYTES, BLOCK_BYTES, 3, self.rng.choice(self.pool))
            for b in range(BLOCK_COUNT)
        ]
        for req in fill:
            base = req.addr - AREA_BASE
            req.data = self.fill[base : base + BLOCK_BYTES]
        for wave in self._chunks(fill):
            await self._wave(wave, stream=False)
        self._log(f"FILL: {len(fill)} blocks of {BLOCK_BYTES} bytes written under pool IDs")

        blocks = list(range(WRITE_BLOCKS))
        reads = list(range(WRITE_BLOCKS, WRITE_BLOCKS + READ_BLOCKS))
        tail_blocks = range(WRITE_BLOCKS + READ_BLOCKS, BLOCK_COUNT)
        stream = [self._plan_write(b, self.rng.choice(self.pool)) for b in blocks]
        stream += [self._plan_read(b, self.rng.choice(self.pool)) for b in reads]
        self.rng.shuffle(stream)
        self.egress_task = cocotb.start_soon(self._egress_writes())
        tail_id = self.rng.choice(self.pool)
        tail = [self._plan_read(b, tail_id, full=True) for b in tail_blocks]
        waves = [*self._chunks(stream), tail]
        stream = [*stream, *tail]
        self.stream_waves = len(waves)
        for index, wave in enumerate(waves):
            await self._gate(index)
            await self._wave(wave, stream=True)
        self._log(
            f"STREAM: transactions={len(stream)} waves={len(waves)} "
            f"writes={WRITE_BLOCKS} reads={READ_BLOCKS + TAIL_READS} "
            f"sizes={sorted(self.stream_sizes)} "
            f"lens={sorted(self.stream_lens)} partial_strobe_writes={self.partial_strobe_writes}"
        )
        holds = Counter(b > 0 or r > 0 for b, r in self.ready_holds)
        self._log(
            f"OBSERVATION ready hold-backs: waves with a hold={holds[True]} "
            f"without={holds[False]} max={MAX_READY_HOLD_CYCLES} (measured and logged only)"
        )
        self.stream_len = len(stream)

    async def _s3(self, sb) -> None:
        tr = self.trace
        ids = sorted(set(self.issued_ids))
        per_id = {
            i: (
                self.issued[(True, i)],
                tr.aw_count[i],
                tr.b_count[i],
                self.issued[(False, i)],
                tr.ar_count[i],
                tr.r_count[i],
            )
            for i in ids
        }
        want = {i: (n, n, n, m, m, m) for i, (n, _, _, m, _, _) in per_id.items()}
        spans = self._bits_span(ids)
        sizes = sorted(tr.sizes)
        self._chk(
            sb,
            "CHK-RANDID-ECHO",
            "BID equals AWID, RID equals ARID and every response matches one request",
            (per_id, tr.unmatched, spans),
            (want, [], True),
            f"distinct_ids={len(ids)} (floor {MIN_DISTINCT_IDS}) sizes_on_pins={sizes} "
            f"lens_on_pins={sorted(tr.lens)} id_width={self.id_width} "
            f"per_id(issued_aw,aw,b,issued_ar,ar,r)={per_id}",
        )
        sb.expect_true(
            f"CHK-RANDID-ECHO at least {MIN_DISTINCT_IDS} distinct IDs and {MIN_DISTINCT_SIZES} "
            "AxSIZE values",
            len(ids) >= MIN_DISTINCT_IDS and len(sizes) >= MIN_DISTINCT_SIZES,
            evidence="CHK-RANDID-ECHO",
        )
        self._chk(
            sb,
            "CHK-RANDID-ORDER",
            "responses of one ID return in request order",
            (
                tr.misordered,
                tr.max_ids_in_flight >= MIN_DISTINCT_IDS,
                tr.discriminating >= MIN_DISCRIMINATING_PAIRS,
            ),
            ([], True, True),
            f"max_ids_in_flight={tr.max_ids_in_flight} max_in_flight={tr.max_in_flight} "
            f"same_id_read_pairs_with_distinct_data={tr.discriminating} "
            f"(floor {MIN_DISCRIMINATING_PAIRS})",
        )

    async def _s4(self, sb) -> None:
        order = sorted(self.written, key=lambda b: (self.written[b], b))
        reqs = [
            _Req(False, AREA_BASE + b * BLOCK_BYTES, BLOCK_BYTES, 3, self.written[b]) for b in order
        ]
        bad = []
        written_bytes = 0
        for wave in self._chunks(reqs):
            await self._gate(EGRESS_COUNT)
            for req, data in zip(wave, await self._wave(wave, stream=False)):
                off = req.addr - AREA_BASE
                want = bytes(self.mem[off : off + BLOCK_BYTES])
                written_bytes += sum(1 for i in range(BLOCK_BYTES) if want[i] != self.fill[off + i])
                if data != want:
                    bad.append((hex(req.addr), req.tid, data.hex(), want.hex()))
        witness = written_bytes > 0
        self._chk(
            sb,
            "CHK-RANDID-DATA",
            "read-back per ID equals the bytes that ID wrote under its strobes",
            (
                bad,
                self.bad_resp,
                witness,
                self.partial_strobe_writes > 0,
                self.trace.misordered,
                self.trace.unmatched,
            ),
            ([], [], True, True, [], []),
            f"blocks={len(reqs)} bytes_differing_from_fill={written_bytes} "
            f"partial_strobe_writes={self.partial_strobe_writes} "
            f"wstrb_patterns_on_pins={sorted(self.trace.wstrbs)}",
        )

    async def _s5(self, sb) -> None:
        tr = self.trace
        t0 = get_sim_time("ns")
        try:
            await with_timeout(self.egress_task, JOIN_BOUND_NS, "ns")
        except Exception as exc:
            self._site(
                "egress_join",
                JOIN_BOUND_NS,
                JOIN_BOUND_NS + 1,
                f"EXPIRED after {len(self.egress_windows)} of {EGRESS_COUNT} egress writes: {exc}",
                "ns",
            )
            self._log(
                f"TIMEOUT-PATH egress_join: bound={JOIN_BOUND_NS} ns EXPIRED "
                f"completed_writes={len(self.egress_windows)}"
            )
            raise
        self._site(
            "egress_join",
            JOIN_BOUND_NS,
            int(get_sim_time("ns") - t0),
            f"egress task done, {len(self.egress_windows)} of {EGRESS_COUNT} writes complete",
            "ns",
        )
        await ClockCycles(self.clk, IDLE_CYCLES)
        addrs = [a for a, _ in self.egress]
        held = [self.cfg.axi_out_mem.read_int(a, 8) for a in addrs]
        overlap = [sum(1 for t in tr.stamps if t0 <= t < t1) > 0 for t0, t1 in self.egress_windows]
        writes_issued = sum(n for (w, _), n in self.issued.items() if w)
        reads_issued = sum(n for (w, _), n in self.issued.items() if not w)
        observed = (
            sorted(self.tap.aw_addrs),
            self.tap.b_resps,
            held,
            self.egress_status,
            overlap,
            (sum(tr.b_count.values()), sum(tr.r_count.values())),
            (tr.unmatched, any(tr.out_w.values()) or any(tr.out_r.values())),
        )
        want = (
            sorted(addrs),
            [RESP_OKAY] * EGRESS_COUNT,
            [v for _, v in self.egress],
            [J2A_STATUS_SUCCESS] * EGRESS_COUNT,
            [True] * EGRESS_COUNT,
            (writes_issued, reads_issued),
            ([], False),
        )
        self._chk(
            sb,
            "CHK-RANDID-CONCURRENT",
            "stream and egress writes complete once each",
            observed,
            want,
            f"egress_windows_ns={[(int(a), int(b)) for a, b in self.egress_windows]} "
            f"ext_in writes={writes_issued} reads={reads_issued} "
            f"smu_axi_out aw={len(self.tap.aw_addrs)} b={len(self.tap.b_resps)}",
        )

    def _s6(self, sb) -> None:
        expired = [n for n, s in self.sites.items() if s["used"] > s["bound"]]
        for name, site in self.sites.items():
            state = "EXPIRED" if name in expired else "ok"
            used = site["used"] if site["measured"] else "not measured"
            self._log(
                f"TIMEOUT-PATH {name}: bound={site['bound']} {site['unit']} "
                f"max_used={used} count={site['count']} {state} last={site['last']}"
            )
        finite = all(0 < s["bound"] < 10**9 for s in self.sites.values())
        has_last = all(s["last"] for s in self.sites.values())
        self._chk(
            sb,
            "CHK-TIMEOUT-PATHS",
            "bounded waits",
            (expired, sorted(self.sites), finite, has_last, self.j2a_accesses),
            ([], sorted(EXPECTED_SITES), True, True, J2A_ACCESS_COUNT),
            f"sites={len(self.sites)} expired={len(expired)} ext_bound={AXI_TIMEOUT_NS} ns "
            f"j2a_poll_limit={J2A_POLL_LIMIT}; j2a_accesses against the budget "
            f"{J2A_ACCESS_BUDGET}",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        await self.cfg.reset_done.wait()
        await ClockCycles(self.clk, 16)
        plan = (
            ("S1", "SETUP: TAP, aperture, entry 0 over the SPM, master, ID width, seed", self._s1),
            ("S2", "stream: fill, then random IDs and sizes with concurrent egress", self._s2),
            ("S3", "per-ID scoreboard: echo and order", self._s3),
            ("S4", "read-back per ID", self._s4),
            ("S5", "concurrent egress: responder memory and response counts", self._s5),
        )
        try:
            for step, text, body in plan:
                await self._mark(step, text)
                await body(sb)
            await self._mark("S6", "TIMEOUT: bounded waits and last state")
            self._s6(sb)
            await ClockCycles(self.clk, 2)
            self.step_ts["PASS"] = get_sim_time("ns")
        finally:
            self.trace.stop()
            self.tap.stop()
        order = [*STEPS, "PASS"]
        stamps = " ".join(f"{k}={self.step_ts[k]:.0f}ns" for k in order)
        increasing = all(self.step_ts[b] > self.step_ts[a] for a, b in zip(order, order[1:]))
        self._log(
            f"CHK-NONVAC: ordered fence {'<'.join(order)} {stamps}; stream_length="
            f"{self.stream_len} seed={self.seed}"
        )
        self._chk(
            sb,
            "CHK-NONVAC",
            "ordered fence, stream length and seed",
            (increasing, self.stream_len >= MIN_STREAM_LENGTH, self.seed_logged),
            (True, True, True),
            f"step stamps strictly increase to the pass point, stream_length={self.stream_len} "
            f"against the floor {MIN_STREAM_LENGTH}, seed {self.seed} logged",
        )
