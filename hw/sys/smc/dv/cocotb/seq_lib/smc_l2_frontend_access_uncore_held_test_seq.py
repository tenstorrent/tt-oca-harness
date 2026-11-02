# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""L2-frontend accesses from SYS_IN, SEP_IN and JTAG_IN across a drained software uncore reset.

Spec sources: cpu.adoc (front-port demultiplexer, AXI isolation, Drain Handshake, Timeout
Recovery), cpu_ctrl.adoc (RESET_CTRL, RESET_TIMEOUT, SCRATCH), clk_rst.adoc, and the AXI
rules transcribed in the ocah_axi_sva header (a master in reset drives VALID low).

With RESET_TIMEOUT at its reset value (drain mode, timer disabled) and no L2-frontend
traffic outstanding, a SEP_IN RESET_CTRL write clears uncore_reset_n and reset_applied has
to set. While it is set, scratchpad and boot-ROM requests presented on the three ports get
no response for a counted window and complete after the release; CPU_CTRL stays reachable
because the CPU-control block sits in front of the isolation block. The cluster-driven
VALIDs at the cluster side of the two isolation blocks are sampled on every clk_smc_i edge
of the hold. Every request is graded from a passive per-port handshake sampler; the values
the specification leaves open (SF-016, SF-017, SF-018, SF-019, SF-026) are OBS lines.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import ClockCycles, First, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time

from .smc_addr_map import (
    LOCAL_BASE_RESET,
    SPM_MEMORY_BASE,
    cpu_ctrl_u32,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
)

OKAY, EXOKAY, SLVERR, DECERR = 0, 1, 2, 3
_RESP = {OKAY: "OKAY", EXOKAY: "EXOKAY", SLVERR: "SLVERR", DECERR: "DECERR", None: "X"}

PORTS = ("SYS_IN", "SEP_IN", "JTAG_IN")
PREFIX = {"SEP_IN": "s_axi", "SYS_IN": "sys_axi", "JTAG_IN": "jtag_axi"}
AGENT = {"SEP_IN": "sep_in_axi_agent", "SYS_IN": "sys_in_axi_agent", "JTAG_IN": "jtag_axi_agent"}
# Data-path ID per port; JTAG_IN carries a 2-bit ID, SEP_IN and SYS_IN 6 bits. SEP_IN uses
# two more IDs so its CPU-control accesses never share an ID with a blocked request.
DATA_ID = {"SEP_IN": 0x15, "SYS_IN": 0x2A, "JTAG_IN": 0x2}
SEP_CTRL_ID = 0x16
SEP_RESET_ID = 0x17

LOCAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
RESET_CTRL = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_CTRL_BASE_ADDR")
RESET_TIMEOUT = smc_addr("SMC_TOP_SMC_CPU_CTRL_RESET_TIMEOUT_BASE_ADDR")
SCRATCH0 = smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", 0)
ROM_BASE = smc_addr("SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR")

UNCORE_N = cpu_ctrl_u32("CPU_CTRL__RESET_CTRL__UNCORE_RESET_N_N0_SCAN_bm")
CORE_LEVEL_N = sum(
    cpu_ctrl_u32(f"CPU_CTRL__RESET_CTRL__CORE{i}_RESET_N_N0_SCAN_bm") for i in range(4)
)
APPLIED = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_APPLIED_bm")
TIMED_OUT = cpu_ctrl_u32("CPU_CTRL__RESET_TIMEOUT__RESET_TIMEOUT_bm")
SCRATCH_DATA = cpu_ctrl_u32("CPU_CTRL__SCRATCH__DATA_bm")
# cpu_ctrl.adoc RESET_TIMEOUT: every field resets to 0 (drain mode, timer disabled).
RESET_TIMEOUT_RESET = 0

BEAT = 8
W_ADDR = tuple(SPM_MEMORY_BASE + 0x2_8000 + BEAT * i for i in range(4))
W_REF = (0x5EED_0000_A11C_0000, 0x5EED_0001_A11C_0001, 0x5EED_0002_A11C_0002, 0x5EED_0003_A11C_0003)
# Episode C writes W1', W2', W3' at W1..W3 from SYS_IN, SEP_IN and JTAG_IN.
W_PRIME = {
    "SYS_IN": (W_ADDR[1], 0xC0DE_0001_B10C_0001),
    "SEP_IN": (W_ADDR[2], 0xC0DE_0002_B10C_0002),
    "JTAG_IN": (W_ADDR[3], 0xC0DE_0003_B10C_0003),
}
ROM_A = ROM_BASE + 0x100
ROM_B = ROM_BASE + 0x140
FRESH_BEATS = 8
FRESH_ADDR = {p: SPM_MEMORY_BASE + 0x3_0000 + 0x1000 * i for i, p in enumerate(PORTS)}
SCRATCH_RUNNING = {
    "SYS_IN": 0x0000_0000_5C2A_0001,
    "SEP_IN": 0x0000_0000_5C15_0002,
    "JTAG_IN": 0x0000_0000_5C02_0003,
}
SCRATCH_HELD = {
    "SYS_IN": 0x0000_0000_4E2A_0011,
    "SEP_IN": 0x0000_0000_4E15_0012,
    "JTAG_IN": 0x0000_0000_4E02_0013,
}

FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
BOOT_BOUND = 200_000
ACCESS_BOUND = 20_000
POLL_BOUND = 64
WINDOW_N = 2048
CTRL_ISSUE_EDGE = 512
CTRL_WINDOW = 1024
RELEASE_BOUND = 400_000

FENCE = (
    "ADMIT",
    "RUNNING_CTRL",
    "HOLD",
    "HELD_CTRL",
    "BLOCKED_A",
    "RELEASE_A",
    "EPISODE_B",
    "EPISODE_C",
    "VALIDS",
    "FRESH",
)
FENCE_STEP = dict(zip(FENCE, ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")))
PLANNED = {
    "ADMIT": 1,
    "RUNNING_CTRL": 9,
    "HOLD": 1,
    "HELD_CTRL": 9,
    "BLOCKED_A": 3,
    "RELEASE_A": 3,
    "EPISODE_B": 3,
    "EPISODE_C": 3,
    "VALIDS": 1,
    "FRESH": 6,
}

# Cluster-side struct ports of the two isolation blocks. The nets are packed structs, so
# each VALID is located by its bit position in the AXI_TYPEDEF_ALL layout; the handle
# width is checked against that layout before any sample is taken.
_CPU = ("u_dut", "u_smc", "u_smc_cpu_wrapper", "u_smc_cpu")
L2_ISO = (*_CPU, "u_l2_frontend_axi_isolate")
MMIO_ISO = (*_CPU, "u_mmio_axi_isolate")
NETS = {
    "l2_req": ((*L2_ISO, "mst_req_o"), (*_CPU, "l2_frontend_axi_isolated_req")),
    "l2_resp": ((*L2_ISO, "mst_resp_i"), (*_CPU, "l2_frontend_axi_isolated_resp")),
    "mmio_req": ((*MMIO_ISO, "slv_req_i"), (*_CPU, "mmio_axi_cpu_req")),
    "mmio_resp": ((*MMIO_ISO, "slv_resp_o"), (*_CPU, "mmio_axi_cpu_resp")),
}
L2_ID_W, L2_ADDR_W = 8, 32
MMIO_ID_W, MMIO_ADDR_W = 3, 56
USER_W, DATA_W = 12, 64


def _req_layout(id_w: int, addr_w: int) -> tuple[int, dict[str, int]]:
    ar = id_w + addr_w + 8 + 3 + 2 + 1 + 4 + 3 + 4 + 4 + USER_W
    aw = ar + 6
    w = DATA_W + DATA_W // 8 + 1 + USER_W
    pos = {"ar_valid": 1, "w_valid": 2 + ar + 1, "aw_valid": 2 + ar + 2 + w}
    return 2 + ar + 2 + w + 1 + aw, pos


def _resp_layout(id_w: int) -> tuple[int, dict[str, int]]:
    r = id_w + DATA_W + 2 + 1 + USER_W
    b = id_w + 2 + USER_W
    return r + 1 + b + 1 + 3, {"r_valid": r, "b_valid": r + 1 + b}


LAYOUT = {
    "l2_req": _req_layout(L2_ID_W, L2_ADDR_W),
    "l2_resp": _resp_layout(L2_ID_W),
    "mmio_req": _req_layout(MMIO_ID_W, MMIO_ADDR_W),
    "mmio_resp": _resp_layout(MMIO_ID_W),
}
CLUSTER_DRIVEN = (
    ("mmio_req", "aw_valid"),
    ("mmio_req", "w_valid"),
    ("mmio_req", "ar_valid"),
    ("l2_resp", "r_valid"),
    ("l2_resp", "b_valid"),
)
ISOLATION_DRIVEN = (
    ("l2_req", "aw_valid"),
    ("l2_req", "w_valid"),
    ("l2_req", "ar_valid"),
    ("mmio_resp", "r_valid"),
    ("mmio_resp", "b_valid"),
)
PROBES = (
    "tb_cpu_isolate_req",
    "tb_cpu_drained",
    "tb_cpu_reset_applied",
    "tb_cpu_reset_timeout",
    "tb_cpu_uncore_reset_n",
    "tb_cpu_l2_isolated",
    "tb_cpu_mmio_isolated",
    "tb_cpu_l2_pending_ar",
    "tb_cpu_l2_pending_aw",
)


def _rname(code: int | None) -> str:
    return _RESP.get(code, str(code))


def _hx(value: int | None) -> str:
    return "X" if value is None else f"0x{value:016x}"


def _resolve(path: tuple[str, ...]):
    handle = cocotb.top
    for name in path:
        handle = getattr(handle, name)
    return handle


@dataclass
class _Hs:
    chan: str
    ident: int | None
    addr: int | None
    length: int | None
    resp: int | None
    data: int | None
    last: int | None
    time_ps: int


class SmcPortHandshakeSampler:
    """Record every AR, AW, W, R and B handshake of the three inbound ports per clk_smc_i edge."""

    _CHANS = ("ar", "aw", "w", "r", "b")

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.events: dict[str, list[_Hs]] = {p: [] for p in PORTS}
        self.last: dict[str, dict[str, _Hs | None]] = {
            p: {c: None for c in self._CHANS} for p in PORTS
        }
        self.unresolved: list[str] = []
        self.handles = {
            p: {
                name: getattr(dut, f"{PREFIX[p]}_{name}")
                for name in (
                    "arvalid",
                    "arready",
                    "araddr",
                    "arid",
                    "arlen",
                    "awvalid",
                    "awready",
                    "awaddr",
                    "awid",
                    "awlen",
                    "wvalid",
                    "wready",
                    "wlast",
                    "rvalid",
                    "rready",
                    "rid",
                    "rresp",
                    "rdata",
                    "rlast",
                    "bvalid",
                    "bready",
                    "bid",
                    "bresp",
                )
            }
            for p in PORTS
        }

    @staticmethod
    def _int(sig) -> int | None:
        value = sig.value
        return int(value) if value.is_resolvable else None

    def _fire(self, port: str, h: dict, chan: str) -> bool:
        valid = self._int(h[f"{chan}valid"])
        ready = self._int(h[f"{chan}ready"]) if valid else 0
        if valid is None or ready is None:
            if len(self.unresolved) < 8:
                self.unresolved.append(f"{port} {chan} X at {get_sim_time('ps')} ps")
            return False
        return bool(valid and ready)

    async def run(self) -> None:
        clk = self.dut.clk_smc_i
        while not self.stop:
            await RisingEdge(clk)
            await ReadOnly()
            now = int(get_sim_time("ps"))
            for port in PORTS:
                h = self.handles[port]
                for chan in self._CHANS:
                    if not self._fire(port, h, chan):
                        continue
                    if chan in ("ar", "aw"):
                        hs = _Hs(
                            chan,
                            self._int(h[f"{chan}id"]),
                            self._int(h[f"{chan}addr"]),
                            self._int(h[f"{chan}len"]),
                            None,
                            None,
                            None,
                            now,
                        )
                    elif chan == "w":
                        hs = _Hs("w", None, None, None, None, None, self._int(h["wlast"]), now)
                    elif chan == "r":
                        hs = _Hs(
                            "r",
                            self._int(h["rid"]),
                            None,
                            None,
                            self._int(h["rresp"]),
                            self._int(h["rdata"]),
                            self._int(h["rlast"]),
                            now,
                        )
                    else:
                        hs = _Hs(
                            "b",
                            self._int(h["bid"]),
                            None,
                            None,
                            self._int(h["bresp"]),
                            None,
                            1,
                            now,
                        )
                    self.events[port].append(hs)
                    self.last[port][chan] = hs

    def since(self, port: str, t0: int, chan: str, ident: int | None = None) -> list[_Hs]:
        return [
            e
            for e in self.events[port]
            if e.time_ps >= t0 and e.chan == chan and (ident is None or e.ident == ident)
        ]

    def describe(self, port: str) -> str:
        parts = []
        for chan in self._CHANS:
            hs = self.last[port][chan]
            if hs is None:
                parts.append(f"{chan}=none")
            elif chan in ("ar", "aw"):
                addr = "X" if hs.addr is None else f"0x{hs.addr:x}"
                parts.append(f"{chan}=addr {addr} id {hs.ident} len {hs.length} t {hs.time_ps}ps")
            elif chan == "w":
                parts.append(f"w=last {hs.last} t {hs.time_ps}ps")
            elif chan == "r":
                parts.append(
                    f"r=id {hs.ident} resp {_rname(hs.resp)} last {hs.last} t {hs.time_ps}ps"
                )
            else:
                parts.append(f"b=id {hs.ident} resp {_rname(hs.resp)} t {hs.time_ps}ps")
        return "; ".join(parts)


class ClusterValidSampler:
    """Passive per-edge sampler of the cluster-side VALIDs while reset_applied is 1."""

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.handles = {}
        self.paths = {}
        for key, candidates in NETS.items():
            for path in candidates:
                try:
                    handle = _resolve(path)
                except AttributeError:
                    continue
                self.handles[key] = handle
                self.paths[key] = ".".join(path)
                break
        self.layout_ok = False
        self.layout_note = ""
        self.fields: dict[tuple[str, str], object] = {}
        self.armed = False
        self.edges = 0
        self.hold_edges: list[int] = []
        self.cluster_high: list[str] = []
        self.cluster_xz: list[str] = []
        self.isolate_high: dict[str, list[int]] = {f"{k}.{f}": [] for k, f in ISOLATION_DRIVEN}
        self.isolate_xz = 0
        self.running_seen: dict[str, int] = {"l2_req.ar_valid": 0, "l2_resp.r_valid": 0}

    def check_layout(self) -> bool:
        problems = []
        for key, (width, _pos) in LAYOUT.items():
            handle = self.handles.get(key)
            if handle is None:
                problems.append(f"{key}: no handle at {['.'.join(p) for p in NETS[key]]}")
                continue
            try:
                got = len(handle)
            except TypeError:
                got = None
            if got is None or got != width:
                try:
                    for field in LAYOUT[key][1]:
                        self.fields[(key, field)] = getattr(handle, field)
                except AttributeError:
                    problems.append(f"{key}: width {got}, layout {width}, no member handles")
        self.layout_ok = not problems
        mode = "member handles" if self.fields else "widths match the packed layout"
        self.layout_note = "; ".join(problems) if problems else mode
        return self.layout_ok

    def _bit(self, key: str, field: str) -> str:
        member = self.fields.get((key, field))
        if member is not None:
            return str(member.value).lower()
        width, pos = LAYOUT[key]
        text = str(self.handles[key].value)
        return text[width - 1 - pos[field]].lower()

    async def run(self) -> None:
        clk = self.dut.clk_smc_i
        applied = self.dut.tb_cpu_reset_applied
        hold = 0
        while not self.stop:
            await RisingEdge(clk)
            await ReadOnly()
            if not self.layout_ok:
                continue
            for name in self.running_seen:
                key, field = name.split(".")
                if self._bit(key, field) == "1":
                    self.running_seen[name] += 1
            level = applied.value
            if not level.is_resolvable or int(level) != 1:
                if hold:
                    self.hold_edges.append(hold)
                    hold = 0
                continue
            if not self.armed:
                continue
            hold += 1
            self.edges += 1
            now = int(get_sim_time("ps"))
            for key, field in CLUSTER_DRIVEN:
                bit = self._bit(key, field)
                if bit == "1" and len(self.cluster_high) < 16:
                    self.cluster_high.append(f"{key}.{field}@{now}ps")
                elif bit not in ("0", "1") and len(self.cluster_xz) < 16:
                    self.cluster_xz.append(f"{key}.{field}={bit}@{now}ps")
            for key, field in ISOLATION_DRIVEN:
                bit = self._bit(key, field)
                if bit == "1":
                    self.isolate_high[f"{key}.{field}"].append(now)
                elif bit != "0":
                    self.isolate_xz += 1
        if hold:
            self.hold_edges.append(hold)


class _Unanswered(Exception):
    """A bounded wait expired; the request is unanswered-transaction evidence."""


@dataclass
class _Req:
    port: str
    label: str
    addr: int
    write: bool
    ident: int
    beats: int
    data: int
    event: object
    t0: int
    done_ps: int | None = None


class smc_l2_frontend_access_uncore_held_test_seq(SmcCsrSeq):
    """Drive the drained uncore reset, the blocked requests, the release and the fresh accesses."""

    def __init__(self, name: str = "smc_l2_frontend_access_uncore_held_test_seq") -> None:
        super().__init__(name)
        self.sampler: SmcPortHandshakeSampler | None = None
        self.valids: ClusterValidSampler | None = None
        self.fence: list[tuple[str, int, int, int]] = []
        self.findings: dict[str, list[str]] = {
            k: [] for k in ("DRAIN", "BLOCK", "RECONNECT", "VALIDS", "CTRL", "OTHER")
        }
        self.counts = {"drain": 0, "blocked": 0, "reconnect": 0, "fresh": 0, "ctrl": 0}
        self.waits = 0
        self.expired = 0
        self.wait_log: list[str] = []
        self.max_wait = {"access": 0, "release": 0, "poll": 0}
        self.ctrl_word: int | None = None
        self.idle_ctrl: int | None = None
        self.rom_ref: dict[str, int | None] = {}
        self.fuse_state = "not waited"
        self.aborted: str | None = None
        self.period_ps = 1

    # ------------------------------------------------------------------ helpers

    def _vip(self, port: str):
        axi = getattr(self.env, AGENT[port]).driver.axi
        assert axi is not None, f"{port}: the AXI VIP is not attached after bring-up"
        return axi

    def _mark(self, term: str, count: int) -> None:
        now = int(get_sim_time("ps"))
        self.fence.append((term, now, count, PLANNED[term]))
        cocotb.log.info(
            "INFO-STEP %s %s done at %d ps: %d against %d planned",
            FENCE_STEP[term],
            term,
            now,
            count,
            PLANNED[term],
        )

    def _probe_state(self) -> str:
        dut = cocotb.top
        parts = []
        for name in (*PROBES, "rst_primary_smc_clk_no"):
            value = getattr(dut, name).value
            parts.append(f"{name}={int(value) if value.is_resolvable else 'X'}")
        return " ".join(parts)

    def _classify(self, kind: str, req: _Req | None, port: str, bound: int, what: str) -> str:
        assert self.sampler is not None
        line = (
            f"INFO-CLASSIFY: {kind} port={port} {what} bound={bound} clk_smc_i edges; "
            f"last {self.sampler.describe(port)}; {self._probe_state()}"
        )
        if req is not None:
            line += f"; request {req.label} 0x{req.addr:x} id={req.ident} beats={req.beats}"
        cocotb.log.info("%s", line)
        return line

    def _start(
        self,
        port: str,
        label: str,
        addr: int,
        *,
        write: bool,
        ident: int,
        data: int = 0,
        beats: int = 1,
    ) -> _Req:
        vip = self._vip(port)
        t0 = int(get_sim_time("ps"))
        if write:
            event = vip.init_write(
                address=addr,
                data=data.to_bytes(BEAT * beats, "little"),
                id=ident,
                size=3,
                burst=1,
                prot=0,
            )
        else:
            event = vip.init_read(
                address=addr, length=BEAT * beats, id=ident, size=3, burst=1, prot=0
            )
        return _Req(port, label, addr, write, ident, beats, data, event, t0)

    async def _wait(self, req: _Req, bound: int, kind: str = "access") -> None:
        self.waits += 1
        start = int(get_sim_time("ps"))
        if not req.event.is_set():
            await First(req.event.wait(), ClockCycles(cocotb.top.clk_smc_i, bound))
        if not req.event.is_set():
            self.expired += 1
            line = self._classify(
                "unanswered-transaction",
                req,
                req.port,
                bound,
                f"{req.label} {'write' if req.write else 'read'} expired",
            )
            self.wait_log.append(f"{req.label}: expired after {bound} edges")
            raise _Unanswered(line)
        await ReadOnly()
        await RisingEdge(cocotb.top.clk_smc_i)
        req.done_ps = int(get_sim_time("ps"))
        period_ps = self.period_ps
        self.max_wait[kind] = max(self.max_wait[kind], (req.done_ps - start) // period_ps)

    def _grade(self, req: _Req, bucket: str) -> list[_Hs]:
        """One AR/AW with the issued ID, the issued beats, one B, RLAST on the last beat, OKAY."""
        assert self.sampler is not None
        ctx = f"{req.port} {req.label} 0x{req.addr:x}"
        out = self.findings[bucket]
        if req.write:
            aw = self.sampler.since(req.port, req.t0, "aw", req.ident)
            if len(aw) != 1 or aw[0].addr != req.addr or aw[0].length != req.beats - 1:
                out.append(f"{ctx}: AW handshakes {[(a.addr, a.length) for a in aw]}")
            b = self.sampler.since(req.port, req.t0, "b", req.ident)
            if len(b) != 1 or b[0].resp != OKAY:
                out.append(f"{ctx}: B {[_rname(x.resp) for x in b]}, want one OKAY")
            return b
        ar = self.sampler.since(req.port, req.t0, "ar", req.ident)
        if len(ar) != 1 or ar[0].addr != req.addr or ar[0].length != req.beats - 1:
            out.append(f"{ctx}: AR handshakes {[(a.addr, a.length) for a in ar]}")
        r = self.sampler.since(req.port, req.t0, "r", req.ident)
        if len(r) != req.beats:
            out.append(f"{ctx}: {len(r)} R beats, want {req.beats}")
        for i, beat in enumerate(r):
            if beat.resp != OKAY:
                out.append(f"{ctx}: beat {i} RRESP {_rname(beat.resp)}")
            if beat.last != (1 if i == len(r) - 1 else 0):
                out.append(f"{ctx}: beat {i} RLAST {beat.last}")
            if beat.data is None:
                out.append(f"{ctx}: beat {i} RDATA X")
        return r

    async def _do(
        self,
        port: str,
        label: str,
        addr: int,
        *,
        write: bool = False,
        data: int = 0,
        ident: int | None = None,
        beats: int = 1,
        bucket: str = "OTHER",
    ) -> int | None:
        req = self._start(
            port,
            label,
            addr,
            write=write,
            data=data,
            beats=beats,
            ident=DATA_ID[port] if ident is None else ident,
        )
        await self._wait(req, ACCESS_BOUND)
        hs = self._grade(req, bucket)
        if write or not hs or hs[0].data is None:
            return None
        return hs[0].data

    async def _sep_csr(
        self, label: str, addr: int, *, write: bool = False, data: int = 0, bucket: str = "OTHER"
    ) -> int | None:
        return await self._do(
            "SEP_IN", label, addr, write=write, data=data, ident=SEP_RESET_ID, bucket=bucket
        )

    async def _poll_applied(self, tag: str, want: int) -> int | None:
        word = None
        for i in range(POLL_BOUND):
            word = await self._sep_csr(f"{tag}_POLL{i}", RESET_TIMEOUT, bucket="DRAIN")
            if word is not None and bool(word & APPLIED) == bool(want):
                self.max_wait["poll"] = max(self.max_wait["poll"], i + 1)
                return word
        self.expired += 1
        self.wait_log.append(f"{tag}: reset_applied not {want} after {POLL_BOUND} reads")
        line = self._classify(
            "unanswered-transaction",
            None,
            "SEP_IN",
            POLL_BOUND,
            f"{tag} RESET_TIMEOUT 0x{word or 0:x} reset_applied never {want}",
        )
        raise _Unanswered(line)

    # ------------------------------------------------------------- the steps

    async def _ctrl_round(self, values: dict[str, int], tag: str) -> int:
        n = 0
        for port in PORTS:
            ident = SEP_RESET_ID if port == "SEP_IN" else DATA_ID[port]
            await self._do(
                port,
                f"{tag}_SCRATCH0_WR",
                SCRATCH0,
                write=True,
                data=values[port],
                ident=ident,
                bucket="CTRL",
            )
            got = await self._do(port, f"{tag}_SCRATCH0_RD", SCRATCH0, ident=ident, bucket="CTRL")
            want = values[port] & SCRATCH_DATA
            if got != want:
                self.findings["CTRL"].append(
                    f"{port} {tag} SCRATCH[0] read {_hx(got)}, want {_hx(want)} (bits 63:32 zero)"
                )
            timeout = await self._do(
                port, f"{tag}_RESET_TIMEOUT_RD", RESET_TIMEOUT, ident=ident, bucket="CTRL"
            )
            cocotb.log.info(
                "INFO-CTRL: %s %s SCRATCH[0] wrote %s read %s; RESET_TIMEOUT %s",
                tag,
                port,
                _hx(values[port]),
                _hx(got),
                _hx(timeout),
            )
            n += 3
        self.counts["ctrl"] += n
        self.ctrl_word = values[PORTS[-1]] & SCRATCH_DATA
        return n

    async def _hold(self, tag: str) -> None:
        assert self.idle_ctrl is not None
        held = self.idle_ctrl & ~UNCORE_N
        await self._sep_csr(
            f"{tag}_RESET_CTRL_HOLD", RESET_CTRL, write=True, data=held, bucket="DRAIN"
        )
        word = await self._poll_applied(f"{tag}_APPLIED", 1)
        if word is None or word & TIMED_OUT:
            self.findings["DRAIN"].append(f"{tag}: RESET_TIMEOUT {_hx(word)} reset_timeout set")
        rb = await self._sep_csr(f"{tag}_RESET_CTRL_RB", RESET_CTRL, bucket="DRAIN")
        if rb != held or (rb is not None and rb & UNCORE_N):
            self.findings["DRAIN"].append(f"{tag}: RESET_CTRL read {_hx(rb)}, want {_hx(held)}")
        cocotb.log.info(
            "INFO-HOLD: %s RESET_CTRL wrote %s read %s; RESET_TIMEOUT %s after the drain",
            tag,
            _hx(held),
            _hx(rb),
            _hx(word),
        )
        if self.valids is not None:
            self.valids.armed = True

    async def _release(self, tag: str) -> int:
        assert self.idle_ctrl is not None
        req = self._start(
            "SEP_IN",
            f"{tag}_RESET_CTRL_RELEASE",
            RESET_CTRL,
            write=True,
            data=self.idle_ctrl,
            ident=SEP_RESET_ID,
        )
        await self._wait(req, ACCESS_BOUND)
        b = self._grade(req, "RECONNECT")
        return b[0].time_ps if b else int(get_sim_time("ps"))

    async def _released(self, tag: str) -> None:
        word = await self._poll_applied(f"{tag}_CLEARED", 0)
        if word is None or word & TIMED_OUT:
            self.findings["DRAIN"].append(f"{tag}: RESET_TIMEOUT {_hx(word)} after the release")
        self.counts["drain"] += 1
        if self.valids is not None:
            self.valids.armed = False

    async def _window(self, reqs: list[_Req], tag: str, ctrl_read: bool = False) -> _Req | None:
        """Count N edges with every request outstanding; R or B for a blocked ID is a finding."""
        assert self.sampler is not None
        dut = cocotb.top
        ctrl = None
        applied_low = 0
        t_start = int(get_sim_time("ps"))
        for edge in range(1, WINDOW_N + 1):
            await RisingEdge(dut.clk_smc_i)
            level = dut.tb_cpu_reset_applied.value
            if not level.is_resolvable or int(level) != 1:
                applied_low += 1
            if ctrl_read and edge == CTRL_ISSUE_EDGE:
                ctrl = self._start(
                    "SEP_IN", f"{tag}_SCRATCH0_IN_WINDOW", SCRATCH0, write=False, ident=SEP_CTRL_ID
                )
            if ctrl is not None and ctrl.done_ps is None and ctrl.event.is_set():
                ctrl.done_ps = int(get_sim_time("ps"))
                cocotb.log.info(
                    "INFO-WINDOW: %s CPU-control read completed at window edge %d", tag, edge
                )
        if applied_low:
            self.findings["BLOCK"].append(f"{tag}: reset_applied low on {applied_low} window edges")
        for req in reqs:
            chan = "b" if req.write else "r"
            early = self.sampler.since(req.port, req.t0, chan, req.ident)
            if early or req.event.is_set():
                self.findings["BLOCK"].append(
                    f"{tag} {req.port} {req.label}: {len(early)} {chan.upper()} inside the "
                    f"{WINDOW_N}-edge window ({[_rname(e.resp) for e in early]})"
                )
            addr_chan = "aw" if req.write else "ar"
            acc = self.sampler.since(req.port, req.t0, addr_chan, req.ident)
            w = self.sampler.since(req.port, req.t0, "w") if req.write else []
            period_ps = self.period_ps

            def edge_of(hs: list[_Hs]) -> str:
                return "none" if not hs else str((hs[0].time_ps - t_start) // period_ps)

            cocotb.log.info(
                "OBS-ISO-BLOCK-READY: port=%s kind=%s %sready=%s%s sf=SF-016",
                req.port,
                "wr" if req.write else "rd",
                addr_chan,
                edge_of(acc),
                f" wready={edge_of(w)}" if req.write else "",
            )
            self.counts["blocked"] += 1
        if ctrl_read:
            assert ctrl is not None
            done = (
                ctrl.done_ps is not None and ctrl.done_ps - ctrl.t0 <= CTRL_WINDOW * self.period_ps
            )
            edge = (
                "none" if ctrl.done_ps is None else str((ctrl.done_ps - t_start) // self.period_ps)
            )
            cocotb.log.info(
                "OBS-FRONTPORT-WHILE-BLOCKED: completed=%s edge=%s issued_edge=%d window=%d "
                "sf=SF-026",
                "y" if done else "n",
                edge,
                CTRL_ISSUE_EDGE,
                CTRL_WINDOW,
            )
        return ctrl

    async def _complete_blocked(self, reqs: list[_Req], tag: str, release_ps: int) -> None:
        period_ps = self.period_ps
        for req in reqs:
            await self._wait(req, RELEASE_BOUND, "release")
            hs = self._grade(req, "RECONNECT")
            latency = "none" if not hs else str((hs[0].time_ps - release_ps) // period_ps)
            data = None if req.write or not hs else hs[0].data
            cocotb.log.info(
                "OBS-ISO-RECONNECT: port=%s latency=%s rdata=%s request=%s sf=SF-017,SF-018",
                req.port,
                latency,
                _hx(data) if not req.write else "n/a",
                req.label,
            )
            self.counts["reconnect"] += 1

    async def _admit(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.waits += 3
        await RisingEdge(dut.clk_smc_i)
        t1 = int(get_sim_time("ps"))
        await RisingEdge(dut.clk_smc_i)
        self.period_ps = max(1, int(get_sim_time("ps")) - t1)
        for cycle in range(BOOT_BOUND + 1):
            value = dut.tb_cpu_cluster_isolate.value
            if value.is_resolvable and int(value) == 0:
                break
            await RisingEdge(dut.clk_smc_i)
        else:
            self.expired += 1
            raise _Unanswered(f"tb_cpu_cluster_isolate still not 0 after {BOOT_BOUND} edges")
        self.waits += 1
        self.wait_log.append(f"cluster boundary de-isolated after {cycle} edges")

        self.sampler = SmcPortHandshakeSampler(dut)
        cocotb.start_soon(self.sampler.run())
        self.valids = ClusterValidSampler(dut)
        layout = self.valids.check_layout()
        cocotb.log.info(
            "INFO-VALID-NETS: %s; %s",
            ", ".join(f"{k}={v}" for k, v in self.valids.paths.items()),
            self.valids.layout_note,
        )
        if not layout:
            self.findings["VALIDS"].append(f"cluster-side nets unusable: {self.valids.layout_note}")
        cocotb.start_soon(self.valids.run())

        for name, addr, value in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("START", INBOUND0_START, 0),
            ("END", INBOUND0_END, 0x00FF_FFFF_FFFF_FFFF),
        ):
            await self._sep_csr(f"INBOUND0_{name}", addr, write=True, data=value)
            rb = await self._sep_csr(f"INBOUND0_{name}_RB", addr)
            if rb != value:
                self.findings["OTHER"].append(f"inbound entry 0 {name} read {_hx(rb)}")
        got = await self._do("SYS_IN", "ADMIT_LOCAL_BASE", LOCAL_BASE_REG)
        assert got == LOCAL_BASE_RESET and not self.findings["OTHER"], (
            f"SYS_IN LOCAL_BASE through pass-all entry 0 read {_hx(got)}: {self.findings['OTHER']}"
        )
        cocotb.log.info(
            "CTRL-M1-ADMIT: SYS_IN 64-bit read of LOCAL_BASE @ 0x%x through pass-all inbound entry 0 "
            "answered OKAY %s",
            LOCAL_BASE_REG,
            _hx(got),
        )
        timeout = await self._sep_csr("RESET_TIMEOUT_IDLE", RESET_TIMEOUT, bucket="DRAIN")
        if timeout != RESET_TIMEOUT_RESET:
            self.findings["DRAIN"].append(f"RESET_TIMEOUT idle {_hx(timeout)}, want reset value 0")
        ctrl = await self._sep_csr("RESET_CTRL_IDLE", RESET_CTRL, bucket="DRAIN")
        if ctrl is None or not ctrl & UNCORE_N or ctrl & CORE_LEVEL_N != CORE_LEVEL_N:
            raise _Unanswered(f"RESET_CTRL idle {_hx(ctrl)}: uncore and cores not all released")
        self.idle_ctrl = ctrl
        for i, (addr, value) in enumerate(zip(W_ADDR, W_REF)):
            await self._do("SEP_IN", f"W{i}_SEED", addr, write=True, data=value)
            rb = await self._do("SEP_IN", f"W{i}_SEED_RB", addr)
            if rb != value:
                self.findings["OTHER"].append(f"W{i} seed read back {_hx(rb)}, want {_hx(value)}")
        for port, addr in (("SEP_IN", ROM_A), ("SYS_IN", ROM_B), ("JTAG_IN", ROM_B)):
            self.rom_ref[port] = await self._do(port, "ROM_REF", addr)
        seen = dict(self.valids.running_seen)
        cocotb.log.info(
            "CTRL-M1-VALID-MAP: running uncore, decoded L2 ar_valid high on %d edges and r_valid "
            "high on %d edges of the S1 scratchpad and ROM traffic; RESET_CTRL %s RESET_TIMEOUT %s; "
            "ROM %s",
            seen["l2_req.ar_valid"],
            seen["l2_resp.r_valid"],
            _hx(ctrl),
            _hx(timeout),
            {p: _hx(v) for p, v in self.rom_ref.items()},
        )
        if not (seen["l2_req.ar_valid"] and seen["l2_resp.r_valid"]):
            self.findings["VALIDS"].append(
                f"decoded L2 VALID bits never rose under running traffic: {seen}"
            )
        self._mark("ADMIT", 1)

    async def _episode_reads(self, tag: str, plan: tuple[tuple[str, int], ...], ctrl_read: bool):
        reqs = [
            self._start(
                port,
                f"{tag}_{'ROM' if addr != W_ADDR[0] else 'W0'}_BLOCKED",
                addr,
                write=False,
                ident=DATA_ID[port],
            )
            for port, addr in plan
        ]
        ctrl = await self._window(reqs, tag, ctrl_read)
        return reqs, ctrl

    async def body(self) -> None:
        try:
            await self._admit()
            self._mark("RUNNING_CTRL", await self._ctrl_round(SCRATCH_RUNNING, "RUNNING"))
            await self._hold("A")
            self._mark("HOLD", 1)
            self._mark("HELD_CTRL", await self._ctrl_round(SCRATCH_HELD, "HELD"))

            reqs, ctrl = await self._episode_reads(
                "A", (("SYS_IN", W_ADDR[0]), ("JTAG_IN", W_ADDR[0]), ("SEP_IN", ROM_A)), True
            )
            self._mark("BLOCKED_A", len(reqs))
            release = await self._release("A")
            await self._complete_blocked(reqs, "A", release)
            assert ctrl is not None
            await self._wait(ctrl, RELEASE_BOUND, "release")
            hs = self._grade(ctrl, "RECONNECT")
            cocotb.log.info(
                "INFO-WINDOW: A SEP_IN CPU-control read answered %s %s (last SCRATCH[0] write %s)",
                _rname(hs[0].resp) if hs else "none",
                _hx(hs[0].data) if hs else "X",
                _hx(self.ctrl_word),
            )
            await self._released("A")
            self._mark("RELEASE_A", len(reqs))

            await self._hold("B")
            reqs, _ = await self._episode_reads(
                "B", (("SEP_IN", W_ADDR[0]), ("SYS_IN", ROM_B), ("JTAG_IN", ROM_B)), False
            )
            release = await self._release("B")
            await self._complete_blocked(reqs, "B", release)
            await self._released("B")
            self._mark("EPISODE_B", len(reqs))

            await self._hold("C")
            reqs = [
                self._start(port, "C_W_BLOCKED", addr, write=True, data=data, ident=DATA_ID[port])
                for port, (addr, data) in W_PRIME.items()
            ]
            await self._window(reqs, "C")
            release = await self._release("C")
            await self._complete_blocked(reqs, "C", release)
            await self._released("C")
            for port, (addr, data) in W_PRIME.items():
                got = await self._do(port, "C_W_READBACK", addr, bucket="RECONNECT")
                if got != data:
                    self.findings["RECONNECT"].append(
                        f"{port} blocked write 0x{addr:x} read back {_hx(got)}, want {_hx(data)}"
                    )
            self._mark("EPISODE_C", len(reqs))

            assert self.valids is not None
            self.valids.stop = True
            self._report_valids()
            self._mark("VALIDS", self.valids.edges)

            await self._fresh()
        except _Unanswered as exc:
            self.aborted = str(exc)
        finally:
            if self.sampler is not None:
                self.sampler.stop = True
            if self.valids is not None:
                self.valids.stop = True
        for port in PORTS:
            assert self.sampler is not None
            cocotb.log.info(
                "INFO-CLASSIFY: port=%s unanswered=%d; checker fires are simulator records in "
                "this log; last %s; %s",
                port,
                1 if self.aborted else 0,
                self.sampler.describe(port),
                self._probe_state(),
            )
        self._report()

    async def _fresh(self) -> None:
        n = 0
        for i, port in enumerate(PORTS):
            payload = 0
            for beat in range(FRESH_BEATS):
                payload |= (0xF2E5_0000_0000_0000 | (i << 16) | beat) << (64 * beat)
            addr = FRESH_ADDR[port]
            wreq = self._start(
                port,
                "FRESH_WR",
                addr,
                write=True,
                data=payload,
                beats=FRESH_BEATS,
                ident=DATA_ID[port],
            )
            await self._wait(wreq, ACCESS_BOUND)
            self._grade(wreq, "RECONNECT")
            w = self.sampler.since(port, wreq.t0, "w") if self.sampler else []
            if len(w) != FRESH_BEATS or [x.last for x in w] != [0] * (FRESH_BEATS - 1) + [1]:
                self.findings["RECONNECT"].append(
                    f"{port} fresh write: W beats {len(w)} WLAST {[x.last for x in w]}"
                )
            rreq = self._start(
                port, "FRESH_RD", addr, write=False, beats=FRESH_BEATS, ident=DATA_ID[port]
            )
            await self._wait(rreq, ACCESS_BOUND)
            r = self._grade(rreq, "RECONNECT")
            got = 0
            for beat, hs in enumerate(r):
                got |= (hs.data or 0) << (64 * beat)
            if got != payload or any(hs.data is None for hs in r):
                self.findings["RECONNECT"].append(f"{port} fresh burst read data differs")
            n += 2
            self.counts["fresh"] += 2
        words = [await self._do("SEP_IN", f"W{i}_AFTER", a) for i, a in enumerate(W_ADDR)]
        cocotb.log.info(
            "OBS-ISO-RECONNECT: port=SEP_IN latency=n/a rdata=n/a w0..w3=%s seeded=%s sf=SF-018",
            ",".join(_hx(w) for w in words),
            ",".join(_hx(w) for w in W_REF),
        )
        self._mark("FRESH", n)

    def _report_valids(self) -> None:
        v = self.valids
        assert v is not None
        if v.edges == 0:
            self.findings["VALIDS"].append("no edge sampled with reset_applied=1")
        if v.cluster_high:
            self.findings["VALIDS"].append(f"cluster-driven VALID high: {v.cluster_high}")
        if v.cluster_xz:
            self.findings["VALIDS"].append(f"cluster-driven VALID X/Z: {v.cluster_xz}")
        highs = {k: (f"{len(t)}@{t[0]}ps" if t else "none") for k, t in v.isolate_high.items()}
        cocotb.log.info(
            "OBS-ISO-VALIDS-ISOLATE: edges=%d holds=%s high_edges=%s xz=%d sf=SF-019",
            v.edges,
            v.hold_edges,
            highs,
            v.isolate_xz,
        )

    # ---------------------------------------------------------------- report

    def _report(self) -> None:
        f = self.findings
        if self.sampler is not None and self.sampler.unresolved:
            f["OTHER"].append(f"X on inbound handshake lines: {self.sampler.unresolved}")
        for key, items in f.items():
            for item in items:
                cocotb.log.info("INFO-FINDING: %s %s", key, item)
        if self.aborted:
            return
        if not f["DRAIN"]:
            cocotb.log.info(
                "CHK-ISO-DRAIN-APPLIED: %d episodes, set after drain, timeout 0, readback bit8=0, "
                "cleared after release (RESET_CTRL OKAY, reset_applied 1 within %d reads, "
                "reset_timeout 0, reset_applied 0 after each release)",
                self.counts["drain"],
                POLL_BOUND,
            )
        if not f["BLOCK"] and not f["RECONNECT"]:
            cocotb.log.info(
                "CHK-ISO-BLOCK-NO-RESPONSE: %d requests, 0 responses during %d-edge windows, all "
                "answered after release",
                self.counts["blocked"],
                WINDOW_N,
            )
        if not f["RECONNECT"]:
            cocotb.log.info(
                "CHK-ISO-RECONNECT: %d blocked requests completed OKAY, fresh bursts OKAY with "
                "data (%d AxLEN=%d accesses), blocked writes read back, reset_applied 0",
                self.counts["reconnect"],
                self.counts["fresh"],
                FRESH_BEATS - 1,
            )
        if not f["VALIDS"] and self.valids is not None:
            cocotb.log.info(
                "CHK-ISO-VALIDS-CLUSTER: %d sampled edges over %d holds, 0 VALID high "
                "(MMIO aw/w/ar_valid, L2 r/b_valid, no X or Z)",
                self.valids.edges,
                len(self.valids.hold_edges),
            )
        if not f["CTRL"]:
            cocotb.log.info(
                "CHK-FRONTPORT-CTRL: running and held, %d CPU-control accesses OKAY, SCRATCH "
                "readback exact",
                self.counts["ctrl"],
            )

    def log_timeout_paths(self) -> None:
        text = (
            f"{self.waits} bounded waits, bound and last state per wait, {self.expired} expired: "
            f"fuse sense sub-waits bounded {FUSE_WAIT_BOUND_SMC_CYCLES} clk_smc_i rises, last "
            f"{self.fuse_state}; cluster de-isolate bounded {BOOT_BOUND} edges; every access "
            f"bounded {ACCESS_BOUND} clk_smc_i edges by First(event, ClockCycles), longest "
            f"{self.max_wait['access']}; RESET_TIMEOUT polls bounded {POLL_BOUND} reads, longest "
            f"{self.max_wait['poll']}; blocked-request completion after release bounded "
            f"{RELEASE_BOUND} edges, longest {self.max_wait['release']}; counted windows "
            f"{WINDOW_N} edges (silence is the stated behaviour); in-window CPU-control read "
            f"window {CTRL_WINDOW} edges; expiry prints INFO-CLASSIFY (last AR/AW/W/R/B, "
            f"rst_primary_smc_clk_no, isolate and drain probes) and fails the leaf; "
            f"{'; '.join(self.wait_log) or 'no expiry'}"
        )
        if self.expired:
            cocotb.log.info("INFO-TIMEOUT-PATHS: %s", text)
        else:
            cocotb.log.info("CHK-TIMEOUT-PATHS: %s", text)

    def nonvac_fence(self) -> None:
        terms = tuple(t for t, _time, _n, _p in self.fence)
        times = [time for _t, time, _n, _p in self.fence]
        problems = []
        if terms != FENCE:
            problems.append(f"terms {terms}, want {FENCE}")
        if not all(b > a for a, b in zip(times, times[1:])):
            problems.append(f"times not increasing {times}")
        problems += [f"{t}: {n} against {p}" for t, _x, n, p in self.fence if n <= 0 or n < p]
        detail = ", ".join(f"{t}@{time}ps={n}/{p}" for t, time, n, p in self.fence)
        if problems:
            cocotb.log.info("INFO-NONVAC-BROKEN: %s (%s)", "; ".join(problems), detail)
            return
        cocotb.log.info("CHK-NONVAC: %s (time and count per term: %s)", " < ".join(FENCE), detail)

    def raise_findings(self) -> None:
        failed = [f"{k}: {v[0]} (+{len(v) - 1})" for k, v in self.findings.items() if v]
        if self.aborted:
            failed.insert(0, f"aborted: {self.aborted}")
        terms = tuple(t for t, _time, _n, _p in self.fence)
        if terms != FENCE:
            failed.append(f"fence {terms}")
        if self.expired:
            failed.append(f"{self.expired} bounded waits expired")
        assert not failed, "uncore-held L2-frontend findings: " + " | ".join(failed)
