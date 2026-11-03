# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Illegal AXI encodings on SEP_IN and SYS_IN: WRAP AxLEN 0, reserved AxBURST, 4 KiB crossing.

Per port, a write and a read of each of three shapes the AXI4 specification
does not allow: AxBURST WRAP with AxLEN 0, the reserved AxBURST 2'b11, and an
INCR burst of full-width beats that starts in the misc_wrap scratch_cold
island and crosses one 4 KiB boundary. The bench master cannot emit the
reserved encoding or an unsplit crossing burst through its backend, so every
illegal request is issued as a raw AW/W or AR on the VIP's own channels with
its response registered in the VIP's tag context, the way
``SmcSysAxiDriver._start_strobed_write`` issues a strobed write.

The run carries +smc_axi_wrap_len1_inject: the SEP_IN and SYS_IN checkers, and
the checkers of the fabric links the requests are forwarded on (SEP ID remap
output, SYS inbound filter output), see each request at an encoding their
WRAP-length, burst-legal and 4 KiB rules accept, while the DUT sees the real
one (docs/SMC_TB_ARCH.adoc). Every other rule of those checkers still grades
the requests. The encoding the DUT forwards on each link is an observation
(OBS-G11-FORWARDED).

Grading, per request, from the port pins the leaf samples on every clk_smc_i
edge: exactly one B for a write and AxLEN+1 R beats with RID=ARID and RLAST on
the last beat only for a read, never EXOKAY, within a counted bound. The
response codes themselves are observations (SF-015, SF-012), the crossing
write's BRESP among them: it is recorded beside the write-split rule of
memmap.adoc:64-67 over the single-beat reference codes and never compared. After
each request the reference set (scratch_cold SCRATCH[0..7] and one
SMC_BASE_CONFIG register) is read back, and only registers inside the
request's footprint may differ (memmap.adoc:63-67, 155-176); a fresh legal
64-bit read of the SMC_BASE_CONFIG register on the same port must answer OKAY
with its seeded value.

Every wait is a bounded count of clk_smc_i edges; an expiry records the
request unanswered with the port's last AW/W/AR/B/R handshake and the reset
sample, classifies it on an INFO-CLASSIFY line and fails the leaf.
"""

from __future__ import annotations

import sys

import cocotb
from cocotb.triggers import Event, ReadOnly, RisingEdge
from cocotb.utils import get_sim_time
from cocotbext.axi.axi_master import AxiWriteRespCmd
from cocotbext.axi.constants import AxiBurstType

from .smc_addr_map import smc_addr, smc_indexed_addr
from .smc_output_fabric_vip_utils import output_fabric_pass_all_cfg_seq

SCRATCH = tuple(
    smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", i) for i in range(8)
)
SCRATCH_SEEDS = tuple(0x6B11_0000 | (i * 0x0101) | 0x8000 for i in range(8))
# HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD: a 20-bit read/write field whose detector is
# disabled at reset (HANG_DET_SEP_AXI_CTRL.enable = 0), so its value moves nothing.
BASE_REF = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD_BASE_ADDR")
BASE_REF_SEED = 0x5_A1B7
REF_COUNT = len(SCRATCH) + 1

BURST_INCR = 1
BURST_WRAP = 2
BURST_RSVD = 3
BURST_NAMES = {0: "FIXED", BURST_INCR: "INCR", BURST_WRAP: "WRAP", BURST_RSVD: "RSVD"}
RESP_NAMES = {0: "OKAY", 1: "EXOKAY", 2: "SLVERR", 3: "DECERR", -1: "TIMEOUT"}
AXI_EXOKAY = 1
AXI_SLVERR = 2
AXI_DECERR = 3

FULL_SIZE = 3
BEAT_BYTES = 8
# An INCR of full-width beats starting at SCRATCH[6] whose last beat starts on the
# next 4 KiB boundary: the footprint crosses exactly one boundary.
CROSS_START = SCRATCH[6]
CROSS_BOUNDARY = (CROSS_START | 0xFFF) + 1
CROSS_BEATS = (CROSS_BOUNDARY - CROSS_START) // BEAT_BYTES + 1
CROSS_BEAT0 = 0x4C4C_0000_0000_0001
# misc_wrap is a generated register block (memmap.adoc, Generated Register Blocks),
# so the crossing write's start address selects a register unit.
CROSS_UNIT_IS_REGISTER = True

# AxPROT and AxCACHE of every request: the pass-all inbound entry leaves allow_ns at 0,
# so it matches AxPROT[1] == 0 only (filter_ctrl.rdl).
AX_PROT = 0
AX_CACHE = 0b0011
AX_ATTRS = {"lock": 0, "cache": AX_CACHE, "qos": 0}

# Bench bounds in clk_smc_i edges; none is a specification value.
TXN_BOUND = 40_000
DRIVER_TIMEOUT_NS = 10_000_000

PORTS = ("SEP_IN", "SYS_IN")
PORT_PREFIX = {"SEP_IN": "s_axi_", "SYS_IN": "sys_axi_"}
PORT_SVA = {"SEP_IN": "u_sep_in_axi_sva", "SYS_IN": "u_sys_in_axi_sva"}
# tb_top probes carrying the view each port's checker instance receives.
PORT_VIEW = {"SEP_IN": "tb_g11_view_sep_in_", "SYS_IN": "tb_g11_view_sys_in_"}
# The fabric link each port's requests reach, its checker instance, the tb_top
# probes carrying the view that instance receives, and the tb_top probe prefix
# carrying the encoding the DUT drives on it.
FWD_LINK = {"SEP_IN": "sep_axi_id_remap_req", "SYS_IN": "filtered_sys_axi_out_req"}
FWD_SVA = {"SEP_IN": "u_sep_remap_axi_sva", "SYS_IN": "u_filtered_sys_axi_sva"}
FWD_VIEW = {"SEP_IN": "tb_g11_view_sep_remap_", "SYS_IN": "tb_g11_view_filtered_sys_"}
FWD_PROBE = {"SEP_IN": "tb_g11_fwd_sep_", "SYS_IN": "tb_g11_fwd_sys_"}
# IDs of the illegal requests (each used once per port), the reference writes,
# the liveness reads and the read-back / re-seed accesses.
REF_ID = 0x10
LIVE_ID = 0x20
HOUSE_ID = 0x30

# (shape, op, burst, beats, start address, AXI ID, payload) per port.
SHAPES = {
    "wrap_len0": {"SEP_IN": SCRATCH[0], "SYS_IN": SCRATCH[2]},
    "reserved_burst": {"SEP_IN": SCRATCH[4], "SYS_IN": SCRATCH[6]},
}
SHAPE_BURST = {"wrap_len0": BURST_WRAP, "reserved_burst": BURST_RSVD, "crossing": BURST_INCR}
SHAPE_IDS = {
    ("wrap_len0", "write"): 1,
    ("wrap_len0", "read"): 2,
    ("reserved_burst", "write"): 3,
    ("reserved_burst", "read"): 4,
    ("crossing", "write"): 5,
    ("crossing", "read"): 6,
}
STAGES = ("setup", "wrap_len0", "reserved_burst", "crossing", "footprint", "liveness")


def _payload(port: int, shape: int, op: int) -> int:
    return 0xA110_0000_0000_0000 | (port << 16) | (shape << 8) | op


def _cross_beat(index: int) -> int:
    return CROSS_BEAT0 if index == 0 else 0


def _sample(sig) -> str:
    value = sig.value
    if isinstance(value, int) or value.is_resolvable:
        return f"{int(value):#x}"
    return str(value)


def _val(sig) -> int | None:
    value = sig.value
    if isinstance(value, int):
        return value
    return int(value) if value.is_resolvable else None


def split_bresp(codes: list[int]) -> int:
    """memmap.adoc:64-67: the last beat's code when it is an error, else SLVERR on an earlier one."""
    if codes[-1] in (AXI_SLVERR, AXI_DECERR):
        return codes[-1]
    if any(code in (AXI_SLVERR, AXI_DECERR) for code in codes[:-1]):
        return AXI_SLVERR
    return 0


def rule_trips(addr: int, length: int, size: int, burst: int) -> list[str]:
    """Which WRAP-length, burst-legal or 4 KiB rule of ocah_axi_sva an AW/AR view trips."""
    trips = []
    if burst == BURST_RSVD:
        trips.append("BURST_LEGAL")
    if burst == BURST_WRAP and length not in (1, 3, 7, 15):
        trips.append("LEN_WRAP_LEGAL")
    if burst == BURST_INCR and (((addr & 0xFFF) >> size) << size) + ((length + 1) << size) > 0x1000:
        trips.append("4KB_BOUNDARY")
    return trips


class _PortMon:
    """Every AW/W/AR/B/R handshake of one bench port, sampled on each clk_smc_i edge.

    The AW and AR records also carry the request as the port's checker instance
    sees it, so the leaf measures what the inject hook presented.
    """

    def __init__(self, port: str) -> None:
        self.port = port
        self.prefix = PORT_PREFIX[port]
        self.view = PORT_VIEW[port]
        self.aw: list[dict] = []
        self.ar: list[dict] = []
        self.w: list[dict] = []
        self.b: list[dict] = []
        self.r: list[dict] = []
        self.last: dict[str, str] = {ch: "none" for ch in ("aw", "w", "ar", "b", "r")}

    def _sig(self, name: str):
        return getattr(cocotb.top, f"{self.prefix}{name}")

    def _addr_rec(self, ch: str) -> dict:
        top = cocotb.top
        rec = {
            "t": int(get_sim_time("ns")),
            "id": _val(self._sig(f"{ch}id")),
            "addr": _val(self._sig(f"{ch}addr")),
            "len": _val(self._sig(f"{ch}len")),
            "size": _val(self._sig(f"{ch}size")),
            "burst": _val(self._sig(f"{ch}burst")),
            "sva_addr": _val(getattr(top, f"{self.view}{ch}addr")),
            "sva_burst": _val(getattr(top, f"{self.view}{ch}burst")),
            "sva_len": _val(getattr(top, f"{self.view}{ch}len")),
            "sva_size": _val(getattr(top, f"{self.view}{ch}size")),
        }
        self.last[ch] = (
            f"{ch}id={rec['id']} {ch}addr={rec['addr']:#x} {ch}len={rec['len']} "
            f"{ch}burst={rec['burst']} t={rec['t']}ns"
            if rec["addr"] is not None
            else f"unresolved t={rec['t']}ns"
        )
        return rec

    @staticmethod
    def _hs(valid, ready) -> bool:
        return _val(valid) == 1 and _val(ready) == 1

    async def run(self) -> None:
        dut = cocotb.top
        s = {
            n: self._sig(n)
            for n in (
                "awvalid",
                "awready",
                "wvalid",
                "wready",
                "wlast",
                "arvalid",
                "arready",
                "bvalid",
                "bready",
                "bid",
                "bresp",
                "rvalid",
                "rready",
                "rid",
                "rresp",
                "rlast",
                "rdata",
            )
        }
        while True:
            await RisingEdge(dut.clk_smc_i)
            await ReadOnly()
            t = int(get_sim_time("ns"))
            if self._hs(s["awvalid"], s["awready"]):
                self.aw.append(self._addr_rec("aw"))
            if self._hs(s["wvalid"], s["wready"]):
                self.w.append({"t": t, "last": _val(s["wlast"])})
                self.last["w"] = f"wlast={_sample(s['wlast'])} t={t}ns"
            if self._hs(s["arvalid"], s["arready"]):
                self.ar.append(self._addr_rec("ar"))
            if self._hs(s["bvalid"], s["bready"]):
                rec = {"t": t, "id": _val(s["bid"]), "resp": _val(s["bresp"])}
                self.b.append(rec)
                self.last["b"] = f"bid={rec['id']} bresp={rec['resp']} t={t}ns"
            if self._hs(s["rvalid"], s["rready"]):
                rec = {
                    "t": t,
                    "id": _val(s["rid"]),
                    "resp": _val(s["rresp"]),
                    "last": _val(s["rlast"]),
                    "data": _sample(s["rdata"]),
                }
                self.r.append(rec)
                self.last["r"] = f"rid={rec['id']} rresp={rec['resp']} rlast={rec['last']} t={t}ns"

    def report(self) -> str:
        return " | ".join(f"{ch.upper()}[{self.last[ch]}]" for ch in ("aw", "w", "ar", "b", "r"))


class _FwdMon:
    """AW and AR handshakes on the fabric link one port's requests reach.

    Each record carries the encoding the DUT drives on the link (tb_g11_fwd_*
    probes) and the view the link's checker instance receives.
    """

    def __init__(self, port: str) -> None:
        self.port = port
        self.link = FWD_LINK[port]
        self.view = FWD_VIEW[port]
        self.probe = FWD_PROBE[port]
        self.aw: list[dict] = []
        self.ar: list[dict] = []

    def _rec(self, ch: str, t: int) -> dict:
        top = cocotb.top
        return {
            "t": t,
            "burst": _val(getattr(top, f"{self.probe}{ch}burst")),
            "len": _val(getattr(top, f"{self.probe}{ch}len")),
            "addr": _val(getattr(top, f"{self.probe}{ch}addr")),
            "sva_burst": _val(getattr(top, f"{self.view}{ch}burst")),
            "sva_len": _val(getattr(top, f"{self.view}{ch}len")),
            "sva_size": _val(getattr(top, f"{self.view}{ch}size")),
            "sva_addr": _val(getattr(top, f"{self.view}{ch}addr")),
        }

    async def run(self) -> None:
        top = cocotb.top
        hs = {ch: getattr(top, f"{self.probe}{ch}_hs") for ch in ("aw", "ar")}
        while True:
            await RisingEdge(top.clk_smc_i)
            await ReadOnly()
            t = int(get_sim_time("ns"))
            for ch in ("aw", "ar"):
                if _val(hs[ch]) == 1:
                    getattr(self, ch).append(self._rec(ch, t))


class _Req:
    """One illegal request: what was presented, where its handshakes start, and the outcome."""

    def __init__(self, port: str, shape: str, op: str, addr: int, beats: int, axi_id: int):
        self.port = port
        self.shape = shape
        self.op = op
        self.addr = addr
        self.beats = beats
        self.axi_id = axi_id
        self.burst = SHAPE_BURST[shape]
        self.marks: dict[str, int] = {}
        self.fwd_mark = 0
        self.addr_rec: dict | None = None
        self.fwd_recs: list[dict] = []
        self.resps: list[dict] = []
        self.answered = False

    @property
    def label(self) -> str:
        return f"{self.port} {self.shape} {self.op} addr=0x{self.addr:x} id={self.axi_id}"

    @property
    def footprint(self) -> tuple[int, int]:
        return self.addr, self.addr + self.beats * BEAT_BYTES


class smc_axi_illegal_encoding_inject_test_seq(output_fabric_pass_all_cfg_seq):
    """WRAP AxLEN 0, reserved burst and 4 KiB-crossing requests on SEP_IN and SYS_IN."""

    def __init__(self, name: str = "smc_axi_illegal_encoding_inject_test_seq") -> None:
        super().__init__(name)
        self.stamps: list[tuple[str, int, str]] = []
        self.waits = 0
        self.expired = 0
        self.mon: dict[str, _PortMon] = {}
        self.fwd: dict[str, _FwdMon] = {}
        self.reqs: list[_Req] = []
        self.ref_codes: dict[str, list[int]] = {}
        self.footprint_checks = 0
        self.footprint_refs = 0
        self.changed_outside: list[str] = []
        self.live_reads = 0
        self.live_ok = 0
        self.ctrl_lines = 0
        self.dut_burst_real = 0
        self.masked_fires = 0
        self.fwd_unresolved = 0

    # ------------------------------------------------------------------
    # Bookkeeping
    # ------------------------------------------------------------------
    def _stage(self, stage: str, counts: str) -> None:
        self.stamps.append((stage, int(get_sim_time("ns")), counts))
        cocotb.log.info("INFO-STAGE: %s %s at %d ns", stage, counts, self.stamps[-1][1])

    def _evidence(self, port: str) -> str:
        rst = _sample(cocotb.top.rst_primary_smc_clk_no)
        return f"{port} last {self.mon[port].report()}; rst_primary_smc_clk_no={rst}"

    def _expire(self, what: str, port: str) -> AssertionError:
        self.expired += 1
        cocotb.log.info(
            "INFO-CLASSIFY: %s unanswered within %d clk_smc_i edges, classification=design-side; %s",
            what,
            TXN_BOUND,
            self._evidence(port),
        )
        return AssertionError(
            f"{what} was not answered within its bound (design-side); {self._evidence(port)}"
        )

    def _axi(self, port: str):
        agent = {"SEP_IN": self.env.sep_in_axi_agent, "SYS_IN": self.env.sys_in_axi_agent}[port]
        axi = agent.driver.axi
        assert axi is not None, f"{port}: the AXI master is not attached"
        return axi

    async def _bounded(self, done, what: str, port: str) -> None:
        self.waits += 1
        for _ in range(TXN_BOUND + 1):
            if done():
                return
            await RisingEdge(cocotb.top.clk_smc_i)
        raise self._expire(what, port)

    # ------------------------------------------------------------------
    # Legal accesses with an explicit ID (reference writes, read-back, liveness)
    # ------------------------------------------------------------------
    async def _legal(self, port: str, op: str, addr: int, axi_id: int, data: int = 0):
        axi = self._axi(port)
        if op == "write":
            coro = axi.write_bytes_result(
                addr,
                data.to_bytes(BEAT_BYTES, "little"),
                size=FULL_SIZE,
                id=axi_id,
                prot=AX_PROT,
                attrs=AX_ATTRS,
                check_response=False,
                timeout_ns=DRIVER_TIMEOUT_NS,
                allow_timeout=True,
            )
        else:
            coro = axi.read_bytes_result(
                addr,
                BEAT_BYTES,
                size=FULL_SIZE,
                id=axi_id,
                prot=AX_PROT,
                attrs=AX_ATTRS,
                check_response=False,
                timeout_ns=DRIVER_TIMEOUT_NS,
                allow_timeout=True,
            )
        task = cocotb.start_soon(coro)
        self.accesses += 1
        await self._bounded(task.done, f"{port} legal {op} 0x{addr:x} id={axi_id}", port)
        result = await task
        if result.timed_out:
            raise self._expire(f"{port} legal {op} 0x{addr:x} id={axi_id}", port)
        return result

    async def _read_refs(self) -> dict[int, int]:
        """Reference set over SEP_IN: SCRATCH pairs as 64-bit reads, then the base register."""
        values: dict[int, int] = {}
        for pair in range(0, len(SCRATCH), 2):
            res = await self._legal("SEP_IN", "read", SCRATCH[pair], HOUSE_ID)
            assert res.resp == 0, (
                f"reference read-back SCRATCH[{pair}:{pair + 1}] answered "
                f"{RESP_NAMES.get(res.resp, res.resp)}; {self._evidence('SEP_IN')}"
            )
            values[SCRATCH[pair]] = res.data & 0xFFFF_FFFF
            values[SCRATCH[pair + 1]] = res.data >> 32
        res = await self._legal("SEP_IN", "read", BASE_REF, HOUSE_ID)
        assert res.resp == 0, f"reference read-back of the base register answered {res.resp}"
        values[BASE_REF] = res.data
        return values

    def _seed_of(self, addr: int) -> int:
        return BASE_REF_SEED if addr == BASE_REF else SCRATCH_SEEDS[SCRATCH.index(addr)]

    async def _reseed(self) -> None:
        """Write every SCRATCH pair back to its seeds over SEP_IN and prove the reference set."""
        for pair in range(0, len(SCRATCH), 2):
            word = (SCRATCH_SEEDS[pair + 1] << 32) | SCRATCH_SEEDS[pair]
            res = await self._legal("SEP_IN", "write", SCRATCH[pair], HOUSE_ID, word)
            assert res.resp == 0, f"re-seed of SCRATCH[{pair}:{pair + 1}] answered {res.resp}"
        values = await self._read_refs()
        bad = {hex(a): hex(v) for a, v in values.items() if v != self._seed_of(a)}
        assert not bad, f"reference set not at its seeds after the re-seed: {bad}"

    # ------------------------------------------------------------------
    # Raw illegal requests on the VIP's own channels
    # ------------------------------------------------------------------
    def _issue(self, req: _Req, data_beats: list[int]) -> None:
        vip = self._axi(req.port)
        mon = self.mon[req.port]
        req.marks = {ch: len(getattr(mon, ch)) for ch in ("aw", "w", "ar", "b", "r")}
        req.fwd_mark = len(getattr(self.fwd[req.port], "aw" if req.op == "write" else "ar"))
        event = Event()
        if req.op == "write":
            wif = vip.backend.write_if
            aw = wif.aw_channel._transaction_obj()
            aw.awid = req.axi_id
            aw.awaddr = req.addr
            aw.awlen = req.beats - 1
            aw.awsize = FULL_SIZE
            aw.awburst = req.burst
            aw.awlock = 0
            aw.awcache = AX_CACHE
            aw.awprot = AX_PROT
            aw.awqos = 0
            aw.awregion = 0
            aw.awuser = 0
            beats = []
            for k, data in enumerate(data_beats):
                w = wif.w_channel._transaction_obj()
                w.wdata = data
                w.wstrb = (1 << BEAT_BYTES) - 1
                w.wlast = int(k == len(data_beats) - 1)
                w.wuser = 0
                beats.append(w)
            wif.in_flight_operations += 1
            wif._idle.clear()
            wif.active_id[req.axi_id] += 1

            async def issue_write() -> None:
                await wif.aw_channel.send(aw)
                for w in beats:
                    await wif.w_channel.send(w)
                wif.tag_context_manager.start_cmd(
                    req.axi_id,
                    AxiWriteRespCmd(
                        req.addr,
                        req.beats * BEAT_BYTES,
                        FULL_SIZE,
                        req.beats,
                        AX_PROT,
                        [1],
                        event,
                    ),
                )

            cocotb.start_soon(issue_write())
        else:
            rif = vip.backend.read_if
            ar = rif.ar_channel._transaction_obj()
            ar.arid = req.axi_id
            ar.araddr = req.addr
            ar.arlen = req.beats - 1
            ar.arsize = FULL_SIZE
            ar.arburst = req.burst
            ar.arlock = 0
            ar.arcache = AX_CACHE
            ar.arprot = AX_PROT
            ar.arqos = 0
            ar.arregion = 0
            ar.aruser = 0
            rif.in_flight_operations += 1
            rif._idle.clear()
            rif.active_id[req.axi_id] += 1
            unpack = AxiBurstType.WRAP if req.burst == BURST_WRAP else AxiBurstType.INCR
            # The read-response command the VIP's own read side defines beside it.
            read_cmd = sys.modules[type(rif).__module__].OcahAxiReadRespCmd

            async def issue_read() -> None:
                await rif.ar_channel.send(ar)
                rif.tag_context_manager.start_cmd(
                    req.axi_id,
                    read_cmd(
                        req.addr,
                        req.beats * BEAT_BYTES,
                        FULL_SIZE,
                        req.beats,
                        AX_PROT,
                        [req.beats],
                        event,
                        unpack,
                    ),
                )

            cocotb.start_soon(issue_read())
        self.accesses += 1
        self.reqs.append(req)

    def _answered(self, req: _Req) -> bool:
        mon = self.mon[req.port]
        if req.op == "write":
            return any(b["id"] == req.axi_id for b in mon.b[req.marks["b"] :])
        return any(r["id"] == req.axi_id and r["last"] == 1 for r in mon.r[req.marks["r"] :])

    async def _drive(self, req: _Req, data_beats: list[int]) -> None:
        self._issue(req, data_beats)
        await self._bounded(lambda: self._answered(req), req.label, req.port)
        mon = self.mon[req.port]
        ch = "aw" if req.op == "write" else "ar"
        recs = getattr(mon, ch)[req.marks[ch] :]
        mine = [rec for rec in recs if rec["id"] == req.axi_id]
        assert len(mine) == 1, f"{req.label}: {len(mine)} address handshakes, want 1"
        req.addr_rec = mine[0]
        if req.op == "write":
            req.resps = [b for b in mon.b[req.marks["b"] :]]
        else:
            req.resps = [r for r in mon.r[req.marks["r"] :]]
        req.answered = True
        rec = req.addr_rec
        dut_burst = rec["burst"]
        self.ctrl_lines += 1
        if dut_burst == req.burst and rec["addr"] == req.addr and rec["len"] == req.beats - 1:
            self.dut_burst_real += 1
        trips = rule_trips(rec["sva_addr"], rec["sva_len"], rec["sva_size"], rec["sva_burst"])
        self.masked_fires += len(trips)
        req.fwd_recs = getattr(self.fwd[req.port], ch)[req.fwd_mark :]
        fwd = req.fwd_recs[0] if req.fwd_recs else None
        fwd_probe_ok = fwd is not None and None not in (
            fwd["sva_addr"],
            fwd["sva_len"],
            fwd["sva_burst"],
        )
        fwd_trips = (
            rule_trips(fwd["sva_addr"], fwd["sva_len"], fwd["sva_size"], fwd["sva_burst"])
            if fwd_probe_ok
            else []
        )
        if fwd is not None and not fwd_probe_ok:
            self.fwd_unresolved += 1
        self.masked_fires += len(fwd_trips)
        if fwd is None:
            cocotb.log.info(
                "OBS-G11-FORWARDED: port=%s shape=%s op=%s link=%s fwd_burst=none fwd_len=none "
                "fwd_addr=none (no %s handshake on the link while the request was open; "
                "observation, SF-015; never compared)",
                req.port,
                req.shape,
                req.op,
                FWD_LINK[req.port],
                ch.upper(),
            )
        else:
            cocotb.log.info(
                "OBS-G11-FORWARDED: port=%s shape=%s op=%s link=%s fwd_burst=%s fwd_len=%s "
                "fwd_addr=%s checker_burst=%s checker_addr=%s link_handshakes=%d t=%d ns "
                "(observation, SF-015; never compared)",
                req.port,
                req.shape,
                req.op,
                FWD_LINK[req.port],
                BURST_NAMES.get(fwd["burst"], fwd["burst"]),
                fwd["len"],
                "unresolved" if fwd["addr"] is None else f"0x{fwd['addr']:x}",
                BURST_NAMES.get(fwd["sva_burst"], fwd["sva_burst"]),
                "unresolved" if fwd["sva_addr"] is None else f"0x{fwd['sva_addr']:x}",
                len(req.fwd_recs),
                fwd["t"],
            )
        for inst, tripped, view in (
            (PORT_SVA[req.port], trips, rec),
            (FWD_SVA[req.port], fwd_trips, fwd),
        ):
            if tripped:
                cocotb.log.info(
                    "INFO-CLASSIFY: %s %s rule(s) %s on the checker view burst=%s len=%s addr=%s; "
                    "classification=checker-side (the inject view does not cover the request); "
                    "%s",
                    inst,
                    req.label,
                    ",".join(tripped),
                    view["sva_burst"],
                    view["sva_len"],
                    view["sva_addr"],
                    self._evidence(req.port),
                )
        cocotb.log.info(
            "CTRL-INJECT-%s: op=%s shape=%s real_burst=%s real_len=%d real_addr=0x%x "
            "dut_burst=%s dut_len=%s dut_addr=0x%x checker_burst=%s checker_addr=0x%x "
            "checker_trips=%s t=%d ns",
            req.port.replace("_", "-"),
            req.op,
            req.shape,
            BURST_NAMES[req.burst],
            req.beats - 1,
            req.addr,
            BURST_NAMES.get(dut_burst, dut_burst),
            rec["len"],
            rec["addr"],
            BURST_NAMES.get(rec["sva_burst"], rec["sva_burst"]),
            rec["sva_addr"],
            ",".join(trips) or "none",
            rec["t"],
        )

    def _grade(self, req: _Req) -> str:
        """Exactly one B / AxLEN+1 R beats with RID=ARID and RLAST last, never EXOKAY."""
        mon = self.mon[req.port]
        if req.op == "write":
            mine = [b for b in mon.b[req.marks["b"] :] if b["id"] == req.axi_id]
            assert len(mine) == 1, (
                f"{req.label}: {len(mine)} B responses with BID={req.axi_id}, want exactly 1; "
                f"{self._evidence(req.port)}"
            )
            assert mine[0]["resp"] != AXI_EXOKAY, f"{req.label}: BRESP EXOKAY"
            return RESP_NAMES.get(mine[0]["resp"], str(mine[0]["resp"]))
        window = req.resps
        last_idx = next(i for i, r in enumerate(window) if r["id"] == req.axi_id and r["last"] == 1)
        beats = window[: last_idx + 1]
        foreign = [r for r in beats if r["id"] != req.axi_id]
        assert not foreign, f"{req.label}: R beats with another RID inside the burst: {foreign}"
        assert len(beats) == req.beats, (
            f"{req.label}: {len(beats)} R beats, want AxLEN+1 = {req.beats}; "
            f"{self._evidence(req.port)}"
        )
        early = [i for i, r in enumerate(beats[:-1]) if r["last"] != 0]
        assert not early, f"{req.label}: RLAST on beat(s) {early} before the last"
        exok = [i for i, r in enumerate(beats) if r["resp"] == AXI_EXOKAY]
        assert not exok, f"{req.label}: EXOKAY on beat(s) {exok}"
        later = [r for r in mon.r[req.marks["r"] :] if r["id"] == req.axi_id]
        assert len(later) == req.beats, (
            f"{req.label}: {len(later)} R beats with RID={req.axi_id} by the end of the shape, "
            f"want {req.beats}"
        )
        return ",".join(RESP_NAMES.get(r["resp"], str(r["resp"])) for r in beats)

    async def _after_shape(self, req: _Req) -> dict[int, int]:
        """Footprint read-back of the reference set, then the liveness read on the port."""
        values = await self._read_refs()
        lo, hi = req.footprint
        changed_in = []
        for addr, value in values.items():
            if value == self._seed_of(addr):
                continue
            if lo <= addr < hi:
                changed_in.append(f"0x{addr:x}=0x{value:x}")
            else:
                self.changed_outside.append(f"{req.label}: 0x{addr:x}=0x{value:x}")
        self.footprint_checks += 1
        self.footprint_refs += len(values)
        assert not self.changed_outside, (
            f"reference register outside the footprint changed: {self.changed_outside}"
        )
        cocotb.log.info(
            "INFO-FOOTPRINT: %s footprint=[0x%x,0x%x) refs=%d changed_inside=%s",
            req.label,
            lo,
            hi,
            len(values),
            changed_in or "none",
        )
        live = await self._legal(req.port, "read", BASE_REF, LIVE_ID)
        self.live_reads += 1
        assert live.resp == 0 and live.data == BASE_REF_SEED, (
            f"{req.port} liveness read after {req.shape} {req.op} answered "
            f"{RESP_NAMES.get(live.resp, live.resp)} data=0x{live.data:x}, want OKAY "
            f"0x{BASE_REF_SEED:x}; {self._evidence(req.port)}"
        )
        self.live_ok += 1
        if changed_in:
            await self._reseed()
        return values

    # ------------------------------------------------------------------
    # Body
    # ------------------------------------------------------------------
    async def body(self) -> None:
        await self.wait_fuse_sense_done()
        for port in PORTS:
            self.mon[port] = _PortMon(port)
            cocotb.start_soon(self.mon[port].run())
            self.fwd[port] = _FwdMon(port)
            cocotb.start_soon(self.fwd[port].run())
        monitor = getattr(self.env, "axi_monitor", None)
        cross_addrs = [CROSS_START + k * BEAT_BYTES for k in range(CROSS_BEATS)]

        # S2 SETUP
        await self.program_inbound_pass_all()
        cocotb.log.info(
            "INFO-FILTER: inbound entry 0 pass-all, allow_ns=0 (matches AxPROT[1]=0 only); every "
            "request drives AxPROT=%d AxCACHE=0x%x",
            AX_PROT,
            AX_CACHE,
        )
        for i, addr in enumerate(SCRATCH):
            await self.csr_write(f"SCRATCH_COLD_{i}_SEED", addr, SCRATCH_SEEDS[i])
            await self.csr_read(f"SCRATCH_COLD_{i}_SEED_RB", addr, expected=SCRATCH_SEEDS[i])
        await self.csr_write("BASE_REF_SEED", BASE_REF, BASE_REF_SEED, length=8)
        await self.csr_read("BASE_REF_SEED_RB", BASE_REF, expected=BASE_REF_SEED, length=8)
        values = await self._read_refs()
        bad = {hex(a): hex(v) for a, v in values.items() if v != self._seed_of(a)}
        assert not bad, f"reference set does not read back its seeds: {bad}"
        if monitor is not None:
            # SF-015: the response to each illegal request is open; a DECERR on one is an
            # observation, so its start address and the reference beat addresses are excused.
            for shape in SHAPES.values():
                monitor.expected_decerr_addrs.update(shape.values())
            monitor.expected_decerr_addrs.update(cross_addrs)
        cocotb.log.info(
            "INFO-PLAN: ports=%s wrap_len0 (WRAP AxLEN 0 AxSIZE 3) at %s; reserved_burst "
            "(AxBURST 2'b11 AxLEN 0 AxSIZE 3) at %s; crossing (INCR AxLEN %d AxSIZE 3) at 0x%x "
            "crossing 0x%x after %d single-beat reference writes per port; reference set "
            "SCRATCH[0..7] at 0x%x.. + SMC_BASE_CONFIG HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD 0x%x",
            ",".join(PORTS),
            {p: hex(a) for p, a in SHAPES["wrap_len0"].items()},
            {p: hex(a) for p, a in SHAPES["reserved_burst"].items()},
            CROSS_BEATS - 1,
            CROSS_START,
            CROSS_BOUNDARY,
            CROSS_BEATS,
            SCRATCH[0],
            BASE_REF,
        )
        self._stage("setup", f"refs={len(values)}")

        # S3 WRAP AxLEN 0 and S4 RESERVED BURST, each followed by S6 and S7.
        obs: dict[str, list[str]] = {"wrap_len0": [], "reserved_burst": []}
        for shape_i, shape in enumerate(("wrap_len0", "reserved_burst")):
            for port_i, port in enumerate(PORTS):
                addr = SHAPES[shape][port]
                for op_i, op in enumerate(("write", "read")):
                    req = _Req(port, shape, op, addr, 1, SHAPE_IDS[(shape, op)])
                    data = _payload(port_i, shape_i, op_i)
                    await self._drive(req, [data])
                    after = await self._after_shape(req)
                    code = self._grade(req)
                    if op == "write":
                        stored = [f"0x{a:x}=0x{after[a]:x}" for a in (addr, addr + 4)]
                        obs[shape].append(f"{port}:BRESP={code} footprint_after={stored}")
                    else:
                        data_words = [r["data"] for r in req.resps if r["id"] == req.axi_id]
                        obs[shape].append(f"{port}:RRESP={code} RDATA={data_words}")
            self._stage(shape, f"reqs={2 * len(PORTS)}")
            if shape == "wrap_len0":
                cocotb.log.info(
                    "OBS-G11-WRAP-LEN0: %s (observation, SF-015; never compared)",
                    "; ".join(obs[shape]),
                )
                answered = {p: sum(r.answered for r in self.reqs if r.port == p) for p in PORTS}
                cocotb.log.info(
                    "CHK-G11-WRAP-LEN0-ANSWERED: sep_in=%d/2 sys_in=%d/2 (one B per write, "
                    "AxLEN+1 R beats with RID=ARID and RLAST last per read, no EXOKAY)",
                    answered["SEP_IN"],
                    answered["SYS_IN"],
                )
                assert answered == {"SEP_IN": 2, "SYS_IN": 2}
            else:
                cocotb.log.info(
                    "OBS-G11-RSVD-BURST: %s (observation, SF-015; never compared)",
                    "; ".join(obs[shape]),
                )
                answered = {
                    p: sum(r.answered for r in self.reqs if r.port == p and r.shape == shape)
                    for p in PORTS
                }
                cocotb.log.info(
                    "CHK-G11-RSVD-BURST-ANSWERED: sep_in=%d/2 sys_in=%d/2 (one B per write, "
                    "AxLEN+1 R beats with RID=ARID and RLAST last per read, no EXOKAY)",
                    answered["SEP_IN"],
                    answered["SYS_IN"],
                )
                assert answered == {"SEP_IN": 2, "SYS_IN": 2}

        # S5 4 KiB CROSSING: the reference codes first, then the burst write and read.
        split: dict[str, tuple[str, str]] = {}
        obs_4kb: list[str] = []
        for port in PORTS:
            codes = []
            for k, beat_addr in enumerate(cross_addrs):
                res = await self._legal(port, "write", beat_addr, REF_ID, _cross_beat(k))
                codes.append(res.resp)
            self.ref_codes[port] = codes
            await self._reseed()
            write = _Req(port, "crossing", "write", CROSS_START, CROSS_BEATS, 5)
            await self._drive(write, [_cross_beat(k) for k in range(CROSS_BEATS)])
            await self._after_shape(write)
            bresp_name = self._grade(write)
            read = _Req(port, "crossing", "read", CROSS_START, CROSS_BEATS, 6)
            await self._drive(read, [])
            await self._after_shape(read)
            rresp = self._grade(read).split(",")
            bresp = next(b["resp"] for b in write.resps if b["id"] == write.axi_id)
            expected = split_bresp(codes)
            assert CROSS_UNIT_IS_REGISTER
            split[port] = (RESP_NAMES[bresp], RESP_NAMES[expected])
            hist = {RESP_NAMES[c]: codes.count(c) for c in sorted(set(codes))}
            rhist = {c: rresp.count(c) for c in sorted(set(rresp))}
            obs_4kb.append(
                f"{port}: reference codes {hist} first={RESP_NAMES[codes[0]]} "
                f"last={RESP_NAMES[codes[-1]]} per-beat={''.join(str(c) for c in codes)}; "
                f"BRESP={bresp_name}; RRESP {rhist} per-beat={''.join(str(c)[0] for c in rresp)}"
            )
        cocotb.log.info(
            "OBS-G11-4KB: %s (observation, SF-015 and SF-012; never compared)",
            " || ".join(obs_4kb),
        )
        answered = {
            p: sum(r.answered for r in self.reqs if r.port == p and r.shape == "crossing")
            for p in PORTS
        }
        assert answered == {"SEP_IN": 2, "SYS_IN": 2}
        cocotb.log.info(
            "CHK-G11-4KB-ANSWERED: sep_in=%d/2 sys_in=%d/2 (AxLEN %d INCR from 0x%x across 0x%x; "
            "one B per write, AxLEN+1 R beats with RID=ARID and RLAST last per read, no EXOKAY)",
            answered["SEP_IN"],
            answered["SYS_IN"],
            CROSS_BEATS - 1,
            CROSS_START,
            CROSS_BOUNDARY,
        )
        for port in PORTS:
            got, want = split[port]
            cocotb.log.info(
                "OBS-G11-SPLIT-BRESP: port=%s bresp=%s split_rule_over_single_beat_codes=%s "
                "(observation, SF-012: the single-beat codes come from the design's own answers "
                "to beats routed by their own address, so the burst's past-extent beats have no "
                "stated code to compare against; start 0x%x selects misc_wrap, %d beats)",
                port,
                got,
                want,
                CROSS_START,
                CROSS_BEATS,
            )
        self._stage("crossing", f"reqs={2 * len(PORTS)} ref_writes={len(PORTS) * CROSS_BEATS}")

        # S6 FOOTPRINT and S7 LIVENESS verdicts over every shape.
        shapes = len(self.reqs)
        assert shapes == 12 and self.footprint_checks == shapes
        assert self.footprint_refs == shapes * REF_COUNT and not self.changed_outside
        cocotb.log.info(
            "CHK-G11-FOOTPRINT: shapes=%d refs=%d changed_outside=%d",
            shapes,
            REF_COUNT,
            len(self.changed_outside),
        )
        self._stage("footprint", f"shapes={shapes}")
        assert self.live_reads == shapes and self.live_ok == shapes
        cocotb.log.info("CHK-G11-LIVENESS: reads=%d ok=%d", self.live_reads, self.live_ok)
        self._stage("liveness", f"reads={self.live_reads}")

        assert self.ctrl_lines == shapes and self.dut_burst_real == shapes, (
            f"CTRL-INJECT lines {self.ctrl_lines}, DUT-side encoding real on {self.dut_burst_real}"
        )
        assert self.masked_fires == 0, f"{self.masked_fires} masked rule(s) tripped on the view"
        assert self.fwd_unresolved == 0, (
            f"{self.fwd_unresolved} forwarded request(s) with an unresolved fabric-link probe"
        )
        cocotb.log.info(
            "CHK-G11-INJECT-MASK: ctrl_lines=%d dut_burst_real=%d masked_fires=%d "
            "fwd_unresolved=%d (the views of u_sep_in_axi_sva, u_sys_in_axi_sva, "
            "u_sep_remap_axi_sva and u_filtered_sys_axi_sva of every illegal request evaluated "
            "against the WRAP-length, burst-legal and 4 KiB rules; a forwarded request whose "
            "fabric-link probe reads X counts as unresolved; every other rule fire is an $error "
            "line the log scan grades)",
            self.ctrl_lines,
            self.dut_burst_real,
            self.masked_fires,
            self.fwd_unresolved,
        )

        # S9
        cocotb.log.info("CHK-TIMEOUT-PATHS: waits=%d expired=%d", self.waits, self.expired)
        assert self.expired == 0 and self.waits > 0
        order = [s for s, _, _ in self.stamps]
        assert order == list(STAGES), f"stage order {order}, want {list(STAGES)}"
        times = [t for _, t, _ in self.stamps]
        assert all(b > a for a, b in zip(times[:4], times[1:4])), f"stage times {times}"
        assert all(b >= a for a, b in zip(times, times[1:])), f"stage times {times}"
        cocotb.log.info(
            "CHK-NONVAC: %s",
            " -> ".join(f"{s}[{c}]@{t}ns" for s, t, c in self.stamps),
        )
