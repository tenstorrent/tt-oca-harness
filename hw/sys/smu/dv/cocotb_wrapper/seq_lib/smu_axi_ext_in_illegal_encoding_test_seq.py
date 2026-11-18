# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Illegal encodings and legal burst shapes on the SMU external inbound port. No Force.

The SEP aperture is opened over the SEP debug module's system bus exactly as
``smu_axi_in_sep_aperture_test`` does (TEST_DEV posture, window
[0x0400_0000, 0x1500_0000) covering SEP-local 0x0 .. 0x10FF_FFFF). The SMC
aperture local alias and SMC inbound filter entry 0 are opened over the DTP
JTAG2AXI bridge first, as ``smu_axi_in_burst_outstanding_test`` does, so ext_in
reaches the SEP
SRAM through ``sep_in`` and the SMC scratchpad (SPM) through ``smc_in``
(``hw/sys/smu/doc/index.adoc``, routing table).

Stimulus path: a raw-channel driver on the ``ext_in_*`` pins of the bench top.
The shared cocotbext-axi master cannot present the requests this contract
needs: it refuses AxBURST = 2'b11 (its burst enum has no value 3) and it
splits every burst at a 4 KiB boundary, and it asserts on a response whose ID
it did not issue. The driver here holds each VALID until its READY, keeps
the payload stable while VALID is high, keeps BREADY and RREADY high, and
issues one transaction at a time except where a step names concurrency. Apart
from the WRAP AxLEN = 0, AxBURST = 2'b11 and 4 KiB-crossing INCR requests of
S5-S7, every request is legal AXI4 (IHI 0022 A3.4.1): FIXED and WRAP beats are
full width, WRAP lengths are 2, 4, 8 or 16 beats from an aligned start, and
every other burst stays inside one 4 KiB page. A passive tap on the same pins
records every AW, W, AR, B and R handshake; a second tap decodes the AW and AR
handshakes at the crossbar SEP and SMC target ports and at both ID-width
converter outputs.

S1 SETUP: SMC alias and inbound filter, debug module, SEP aperture; CTRL-G11-OKAY round trip
   to one SEP SRAM word and one SPM word.
S2 LEGAL INCR: INCR AxLEN 0, 1, 15, 255 to both targets; single-beat FIXED and
   INCR; W after, with and before its AW; four reads under distinct IDs in
   flight together.
S3 NARROW AND STROBES: AxSIZE 0..2 with an unaligned first beat and partial
   strobes, and one write whose unstrobed lanes carry X.
S4 FIXED AND WRAP to SEP SRAM: FIXED AxLEN 1, 3, 15 and WRAP AxLEN 1, 3, 7, 15.
S5 WRAP AxLEN=0, S6 AxBURST=2'b11, S7 4 KiB crossing: a read and a write toward
   the SEP aperture, the SMC aperture and neither aperture, one at a time,
   with +smu_axi_illegal_inject armed on the bench; the SEP SRAM and SPM words
   they address are written first.
S8 FRESH ACCESS after each illegal request.
S9 DECODE AND RULE FAMILIES.
S10 TIMEOUT: every wait is a bounded count of clk_smu_i edges.
"""

from __future__ import annotations

from collections import defaultdict

import cocotb
from cocotb.triggers import RisingEdge
from cocotb.types import LogicArray
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_OKAY, RESP_SLVERR, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import smc_addr
from seq_lib.smu_axi_in_sep_aperture_test_seq import (
    SRAM_LOCAL,
    WIN_BASE,
    WIN_SIZE,
    smu_axi_in_sep_aperture_test_seq,
)
from seq_lib.smu_compose_helpers import hier, sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import smu_dtp_sep_dm_dmi_test_seq
from seq_lib.smu_filter_helpers import (
    PASS_ALL_END,
    PASS_RW_CONFIG,
    program_inbound0_window,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import DTP_DEFAULT_IDCODE, make_smu_jtag_tap

# --- addresses: generated headers and the routing table ---
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
SPM_SIZE = smc_addr("SMC_TOP_SPM_MEMORY_SIZE")
SEP_SRAM = WIN_BASE + SRAM_LOCAL
# SEP SRAM cells (global): S1 word, INCR region, narrow region, FIXED/WRAP
# region, illegal-request word, 4 KiB-crossing start.
SEP_S1 = SEP_SRAM
SEP_INCR = SEP_SRAM + 0x1000
SEP_NARROW = SEP_SRAM + 0x100
SEP_FIXWRAP = SEP_SRAM + 0x400
SEP_ILL = SEP_SRAM + 0x800
SEP_CROSS = SEP_SRAM + 0x4000 - 0x10
# SPM cells, local; the ext_in address adds the SMC aperture offset.
SPM_INCR_LOCAL = SPM_BASE + 0x1000
SPM_S1_LOCAL = SPM_BASE + 0xF00
SPM_ILL_LOCAL = SPM_BASE + 0x800
SPM_CROSS_LOCAL = SPM_BASE + 0x3000 - 0x10
# An address inside neither aperture; checked against both at run time.
NEITHER = 0x3000_0000

BURST_FIXED, BURST_INCR, BURST_WRAP, BURST_RSVD = 0, 1, 2, 3
# AxPROT of every request: unprivileged non-secure data, the shared master's
# default; SMC inbound filter entry 0 is opened with ALLOW_NS only.
AXPROT_NONSECURE = 0b010
INCR_LENS = (0, 1, 15, 255)
FIXED_LENS = (1, 3, 15)
WRAP_LENS = (1, 3, 7, 15)

# --- bounds, counted in clk_smu_i edges ---
HS_BOUND = 4096
RESP_BOUND = 20_000
ILL_WINDOW = 1024
W_LEAD = 4
# ID ranges: the illegal requests use their own IDs so a late response is
# attributable; every other access draws from the low range.
ILL_ID_BASE = 0xE0
LEGAL_ID_MAX = 0xDF
RULE_FAMILIES = (
    ("valid_ready_x", "OCAH_INC_ASSERT"),
    ("payload_known", "OCAH_INC_ASSERT"),
    ("reset", "SIMULATION"),
    ("handshake", "SIMULATION"),
    ("burst_legality", "SIMULATION"),
    ("wlast_rlast", "SIMULATION"),
    ("strobe", "SIMULATION"),
    ("response_order", "SIMULATION"),
    ("outstanding", "SIMULATION"),
)
SVA_INSTANCES = (
    "u_smu_in_axi_sva",
    "u_incut_axi_sva",
    "u_xbar_ext_in_axi_sva",
    "u_xbar_sep_in_axi_sva",
    "u_iwc_sep_axi_sva",
    "u_xbar_smc_in_axi_sva",
    "u_iwc_smc_axi_sva",
)
HOOK_INSTANCES = ("u_smu_in_axi_sva", "u_incut_axi_sva", "u_xbar_ext_in_axi_sva")
XBAR = "u_dut.u_smu.gen_sep.u_smu_axi_xbar"
DOWN_LINKS = (
    ("xbar_sep_in", f"{XBAR}.sep_in_req_o", f"{XBAR}.sep_in_resp_i"),
    ("iwc_sep", "u_dut.u_smu.sep_smn_inbound_axi_req", "u_dut.u_smu.sep_smn_inbound_axi_resp"),
    ("xbar_smc_in", f"{XBAR}.smc_in_req_o", f"{XBAR}.smc_in_resp_i"),
    ("iwc_smc", "u_dut.u_smu.smc_sys_axi_in_req", "u_dut.u_smu.smc_sys_axi_in_resp"),
)
LINK_ADDR_BITS = 56
LINK_DATA_BITS = 64


def _now() -> int:
    return int(get_sim_time(unit="ns"))


def _lanes(addr: int, size: int, beat: int, burst: int) -> int:
    """Active byte lanes of one beat on the 8-byte bus (IHI 0022 A3.4.3)."""
    nbytes = 1 << size
    aligned = addr & ~(nbytes - 1)
    if burst == BURST_FIXED or beat == 0:
        lo = addr
        hi = aligned + nbytes
    else:
        lo = aligned + beat * nbytes
        hi = lo + nbytes
    mask = 0
    for a in range(lo, hi):
        mask |= 1 << (a % 8)
    return mask


def _beat_addr(addr: int, size: int, beat: int) -> int:
    nbytes = 1 << size
    return addr if beat == 0 else (addr & ~(nbytes - 1)) + beat * nbytes


def _crosses_4k(addr: int, length: int, size: int) -> bool:
    return ((((addr & 0xFFF) >> size) << size) + ((length + 1) << size)) > 0x1000


class _Down:
    """AW/AR field positions in one pulp AXI4 request/response struct pair."""

    def __init__(self, dut, name: str, req_path: str, resp_path: str) -> None:
        self.name = name
        self.req = hier(dut, req_path)
        self.resp = hier(dut, resp_path)
        rq, rp = len(self.req), len(self.resp)
        a, d = LINK_ADDR_BITS, LINK_DATA_BITS
        x = rq - (2 * a + 9 * d // 8 + 70)
        y = rp - (d + 10)
        u = x - y
        i2 = y - 2 * u
        if u < 0 or i2 <= 0 or i2 % 2:
            raise AssertionError(f"{name}: {rq}/{rp}-bit structs do not decode as AXI4")
        idw = i2 // 2
        self.idw, self.uw, self.rq, self.rp = idw, u, rq, rp
        ar = idw + a + 29 + u
        w = d + d // 8 + 1 + u
        base_ar = 2
        base_w = 4 + ar
        base_aw = 5 + ar + w
        self.q = {
            "ar_valid": 1,
            "ar_burst": (base_ar + u + 16, 2),
            "ar_size": (base_ar + u + 18, 3),
            "ar_len": (base_ar + u + 21, 8),
            "ar_addr": (base_ar + u + 29, a),
            "ar_id": (base_ar + u + 29 + a, idw),
            "w_valid": 3 + ar,
            "w_strb": (base_w + u + 1, d // 8),
            "w_data": (base_w + u + 1 + d // 8, d),
            "aw_valid": 4 + ar + w,
            "aw_atop": (base_aw + u, 6),
            "aw_burst": (base_aw + u + 22, 2),
            "aw_size": (base_aw + u + 24, 3),
            "aw_len": (base_aw + u + 27, 8),
            "aw_addr": (base_aw + u + 35, a),
            "aw_id": (base_aw + u + 35 + a, idw),
        }
        r = idw + d + 3 + u
        b = idw + 2 + u
        self.p = {"w_ready": r + 2 + b, "ar_ready": r + 3 + b, "aw_ready": r + 4 + b}

    @staticmethod
    def text(bits: str, lsb_width: tuple[int, int]) -> str:
        lsb, width = lsb_width
        return bits[len(bits) - lsb - width : len(bits) - lsb]

    def field(self, bits: str, key: str) -> int:
        t = self.text(bits, self.q[key])
        if set(t) - {"0", "1"}:
            raise AssertionError(f"X/Z on {self.name}.{key}: {t}")
        return int(t, 2)

    @staticmethod
    def bit(bits: str, lsb: int) -> str:
        return bits[len(bits) - 1 - lsb]


class smu_axi_ext_in_illegal_encoding_test_seq(smu_axi_in_sep_aperture_test_seq):
    """ext_in illegal encodings under the bench hook, and legal bursts into SEP SRAM and SPM."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.sb = test.env.scoreboard
        self.log = test.logger
        self.waits: list[tuple[str, int, int, str]] = []
        self.fence: list[tuple[str, int, int, int]] = []
        self.ev: list[tuple] = []
        self.ill_presented: list[tuple] = []
        self.down: list[tuple] = []
        self.wknown: list[tuple] = []
        self.hook: list[tuple] = []
        self.atop: set[str] = set()
        self.x_samples: list[tuple] = []
        self.legal_ids: set[int] = set()
        self.ill_ids: dict[int, dict] = {}
        self._id = 0
        self._ill_id = ILL_ID_BASE
        self.xlane_watch = False
        self.hook_watch = False
        self.done = False

    # ---------------- logging / bounds ----------------
    def _info(self, msg: str) -> None:
        self.log.info(msg)

    def _last_state(self) -> str:
        last = {}
        for e in self.ev:
            last[e[0]] = e
        rst = str(self.dut.rst_primary_smc_clk_n_o.value)
        return (
            " ".join(f"{c}={last.get(c, 'none')}" for c in ("aw", "ar", "w", "r", "b"))
            + f" rst_primary_smc_clk_n_o={rst}"
        )

    def _expire(self, name: str, bound: int, what: str) -> None:
        state = self._last_state()
        self._info(
            f"INFO-CLASSIFY: kind=unanswered-transaction class=design-side wait={name} "
            f"bound={bound} clk_smu_i expired; {what}; last={state}"
        )
        raise AssertionError(f"TIMEOUT {name}: {what} not seen within {bound} clk_smu_i; {state}")

    def _bounded(self, name: str, bound: int, used: int, last: str) -> None:
        self.waits.append((name, bound, used, last))

    def _mark(self, term: str, count: int, planned: int) -> None:
        self.fence.append((term, _now(), count, planned))
        self._info(f"INFO-G11-STEP: {term} t={_now()}ns count={count} planned={planned}")

    def _next_id(self) -> int:
        if self._id >= LEGAL_ID_MAX:
            raise AssertionError("legal ID range exhausted; per-ID pairing needs unique IDs")
        self._id += 1
        self.legal_ids.add(self._id)
        return self._id

    # ---------------- pins ----------------
    def _pin(self, name: str):
        return getattr(self.dut, f"ext_in_{name}")

    def _init_pins(self) -> None:
        for ch in ("aw", "ar"):
            for f, v in (
                ("valid", 0),
                ("id", 0),
                ("addr", 0),
                ("len", 0),
                ("size", 3),
                ("burst", BURST_INCR),
                ("lock", 0),
                ("cache", 0),
                ("prot", AXPROT_NONSECURE),
                ("qos", 0),
                ("region", 0),
                ("user", 0),
            ):
                self._pin(f"{ch}{f}").value = v
        for f, v in (("valid", 0), ("data", 0), ("strb", 0), ("last", 0), ("user", 0)):
            self._pin(f"w{f}").value = v
        self._pin("bready").value = 1
        self._pin("rready").value = 1

    def _hs(self, valid: str, ready: str) -> bool:
        v = str(self._pin(valid).value)
        r = str(self._pin(ready).value)
        if v not in ("0", "1") or r not in ("0", "1"):
            self.x_samples.append((_now(), valid, v, ready, r))
            return False
        return v == "1" and r == "1"

    async def _send(self, ch: str, fields: dict, label: str) -> None:
        for f, v in fields.items():
            self._pin(f"{ch}{f}").value = v
        self._pin(f"{ch}valid").value = 1
        for n in range(HS_BOUND):
            await RisingEdge(self.dut.clk_smu_i)
            if str(self._pin(f"{ch}ready").value) == "1":
                self._pin(f"{ch}valid").value = 0
                self._bounded(f"{ch}_handshake", HS_BOUND, n, f"{label} {ch.upper()} accepted")
                return
        self._expire(f"{ch}_handshake", HS_BOUND, f"{label} {ch.upper()}READY")

    async def _send_w(self, beats: list[tuple[object, int]], label: str) -> None:
        for i, (data, strb) in enumerate(beats):
            self._pin("wdata").value = data
            self._pin("wstrb").value = strb
            self._pin("wlast").value = int(i == len(beats) - 1)
            self._pin("wvalid").value = 1
            for n in range(HS_BOUND):
                await RisingEdge(self.dut.clk_smu_i)
                if str(self._pin("wready").value) == "1":
                    self._bounded("w_handshake", HS_BOUND, n, f"{label} W beat {i}")
                    break
            else:
                self._expire("w_handshake", HS_BOUND, f"{label} WREADY beat {i}")
        self._pin("wvalid").value = 0

    # ---------------- taps ----------------
    async def _watch(self) -> None:
        dut = self.dut
        links = self.links
        while True:
            await RisingEdge(dut.clk_smu_i)
            t = _now()
            if self._hs("awvalid", "awready"):
                self.ev.append(
                    (
                        "aw",
                        t,
                        int(self._pin("awid").value),
                        int(self._pin("awaddr").value),
                        int(self._pin("awlen").value),
                        int(self._pin("awsize").value),
                        int(self._pin("awburst").value),
                    )
                )
                self.atop.add(_Down.text(str(self.smu_in_req.value), self.smu_in.q["aw_atop"]))
            if self._hs("wvalid", "wready"):
                data = str(self._pin("wdata").value)
                strb = int(self._pin("wstrb").value)
                self.ev.append(("w", t, data, strb, int(self._pin("wlast").value)))
                if self.xlane_watch:
                    self.wknown.append(("smu_in", t, data, strb))
            if self._hs("arvalid", "arready"):
                self.ev.append(
                    (
                        "ar",
                        t,
                        int(self._pin("arid").value),
                        int(self._pin("araddr").value),
                        int(self._pin("arlen").value),
                        int(self._pin("arsize").value),
                        int(self._pin("arburst").value),
                    )
                )
            if self._hs("bvalid", "bready"):
                self.ev.append(
                    ("b", t, sample(self._pin("bid"), "bid"), sample(self._pin("bresp"), "bresp"))
                )
            if self._hs("rvalid", "rready"):
                self.ev.append(
                    (
                        "r",
                        t,
                        sample(self._pin("rid"), "rid"),
                        sample(self._pin("rresp"), "rresp"),
                        sample(self._pin("rlast"), "rlast"),
                        str(self._pin("rdata").value),
                    )
                )
            for link in links:
                qs = str(link.req.value)
                if (
                    _Down.bit(qs, link.q["aw_valid"]) != "1"
                    and _Down.bit(qs, link.q["ar_valid"]) != "1"
                ):
                    if not (self.xlane_watch and _Down.bit(qs, link.q["w_valid"]) == "1"):
                        continue
                ps = str(link.resp.value)
                for ch in ("aw", "ar"):
                    if (
                        _Down.bit(qs, link.q[f"{ch}_valid"]) == "1"
                        and _Down.bit(ps, link.p[f"{ch}_ready"]) == "1"
                    ):
                        self.down.append(
                            (
                                link.name,
                                ch,
                                t,
                                link.field(qs, f"{ch}_id"),
                                link.field(qs, f"{ch}_addr"),
                                link.field(qs, f"{ch}_len"),
                                link.field(qs, f"{ch}_size"),
                                link.field(qs, f"{ch}_burst"),
                            )
                        )
                if (
                    self.xlane_watch
                    and _Down.bit(qs, link.q["w_valid"]) == "1"
                    and _Down.bit(ps, link.p["w_ready"]) == "1"
                ):
                    self.wknown.append(
                        (
                            link.name,
                            t,
                            _Down.text(qs, link.q["w_data"]),
                            int(_Down.text(qs, link.q["w_strb"]), 2),
                        )
                    )
            if self.hook_watch:
                for inst in HOOK_INSTANCES:
                    h = self.hook_h[inst]
                    for ch in ("aw", "ar"):
                        if str(h[f"{ch}valid"].value) == "1" and str(h[f"{ch}ready"].value) == "1":
                            self.hook.append(
                                (
                                    inst,
                                    ch,
                                    t,
                                    int(h[f"{ch}id"].value),
                                    int(h[f"{ch}burst"].value),
                                    int(h[f"{ch}addr"].value),
                                    int(h[f"{ch}len"].value),
                                )
                            )

    def _events(self, kind: str, start: int, ident: int | None = None) -> list[tuple]:
        return [e for e in self.ev[start:] if e[0] == kind and (ident is None or e[2] == ident)]

    async def _wait_for(self, pred, bound: int, name: str, what: str) -> int:
        for n in range(bound):
            if pred():
                self._bounded(name, bound, n, what)
                return n
            await RisingEdge(self.dut.clk_smu_i)
        self._expire(name, bound, what)
        return bound

    # ---------------- transactions ----------------
    async def _wr(
        self,
        addr: int,
        beats: list[tuple[object, int]],
        *,
        size: int = 3,
        burst: int = BURST_INCR,
        awid: int | None = None,
        order: str = "with",
        label: str,
    ) -> dict:
        awid = self._next_id() if awid is None else awid
        start = len(self.ev)
        aw = {
            "id": awid,
            "addr": addr,
            "len": len(beats) - 1,
            "size": size,
            "burst": burst,
        }
        if order == "after":
            await self._send("aw", aw, label)
            await self._send_w(beats, label)
        elif order == "before":
            w_task = cocotb.start_soon(self._send_w(beats, label))
            for _ in range(W_LEAD):
                await RisingEdge(self.dut.clk_smu_i)
            await self._send("aw", aw, label)
            await w_task
        else:
            w_task = cocotb.start_soon(self._send_w(beats, label))
            await self._send("aw", aw, label)
            await w_task
        await self._wait_for(
            lambda: self._events("b", start, awid),
            RESP_BOUND,
            "b_response",
            f"{label} B id=0x{awid:x}",
        )
        b = self._events("b", start, awid)
        return {"id": awid, "bid": b[0][2], "bresp": b[0][3], "nb": len(b)}

    async def _rd_issue(
        self, addr: int, length: int, *, size=3, burst=BURST_INCR, arid=None, label
    ):
        arid = self._next_id() if arid is None else arid
        await self._send(
            "ar", {"id": arid, "addr": addr, "len": length, "size": size, "burst": burst}, label
        )
        return arid

    async def _rd_collect(self, arid: int, start: int, label: str) -> list[tuple]:
        await self._wait_for(
            lambda: any(e[4] == 1 for e in self._events("r", start, arid)),
            RESP_BOUND,
            "r_response",
            f"{label} RLAST id=0x{arid:x}",
        )
        return self._events("r", start, arid)

    async def _rd(self, addr: int, length: int, *, size=3, burst=BURST_INCR, label: str):
        start = len(self.ev)
        arid = await self._rd_issue(addr, length, size=size, burst=burst, label=label)
        beats = await self._rd_collect(arid, start, label)
        return arid, beats

    @staticmethod
    def _beat_bytes(beat: tuple, lanes: int = 0xFF) -> bytes | None:
        text = beat[5]
        out = bytearray()
        for lane in range(8):
            if not lanes >> lane & 1:
                continue
            chunk = text[len(text) - 8 * (lane + 1) : len(text) - 8 * lane]
            if set(chunk) - {"0", "1"}:
                return None
            out.append(int(chunk, 2))
        return bytes(out)

    async def _read_bytes(
        self, addr: int, nbytes: int, label: str
    ) -> tuple[bytes | None, list[int]]:
        """Legal 8-byte INCR reads of [addr, addr + nbytes), split at 4 KiB pages."""
        out = bytearray()
        resps = []
        a = addr
        while a < addr + nbytes:
            page_end = (a | 0xFFF) + 1
            n = min(addr + nbytes, page_end) - a
            beats_n = n // 8
            _, beats = await self._rd(a, beats_n - 1, label=label)
            for beat in beats:
                resps.append(beat[3])
                bb = self._beat_bytes(beat)
                if bb is None:
                    return None, resps
                out += bb
            a += n
        return bytes(out), resps

    async def _write_bytes(self, addr: int, data: bytes, label: str) -> list[int]:
        """Legal 8-byte INCR writes of ``data`` at ``addr``, split at 4 KiB pages."""
        resps = []
        a = addr
        while a < addr + len(data):
            page_end = (a | 0xFFF) + 1
            n = min(addr + len(data), page_end) - a
            chunk = data[a - addr : a - addr + n]
            beats = [(int.from_bytes(chunk[i : i + 8], "little"), 0xFF) for i in range(0, n, 8)]
            res = await self._wr(a, beats, label=label)
            resps.append(res["bresp"])
            a += n
        return resps

    @staticmethod
    def _pattern(seed: int, n: int) -> bytes:
        return bytes((seed + 7 * i) & 0xFF for i in range(n))

    # ---------------- steps ----------------
    async def _open_smc(self) -> None:
        """SMC aperture local alias and inbound filter entry 0 over JTAG2AXI."""
        jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if sample(self.dut.tb_smc_jtag2axi_security_disable, "security_disable") & 1:
            raise AssertionError("SMC JTAG2AXI gated; the leaf cannot open the SMC inbound path")
        await program_smc_aperture_local_alias(jtag, scoreboard=self.sb)
        await program_inbound0_window(jtag, 0, PASS_ALL_END, scoreboard=self.sb, tag="G11")

    async def _setup(self) -> None:
        jtag = self.jtag
        await self._window(jtag, WIN_BASE, WIN_SIZE)
        smc_base = sample(self.dut.smc_global_base_o, "smc_global_base_o")
        smc_size = sample(self.dut.smc_region_size_o, "smc_region_size_o")
        sep_base = sample(self.dut.sep_global_base_o, "sep_global_base_o")
        sep_size = sample(self.dut.sep_region_size_o, "sep_region_size_o")
        self.spm = self._smc_view(SPM_BASE)
        self.smc_s1 = self._smc_view(SPM_S1_LOCAL)
        self.smc_incr = self._smc_view(SPM_INCR_LOCAL)
        self.smc_ill = self._smc_view(SPM_ILL_LOCAL)
        self.smc_cross = self._smc_view(SPM_CROSS_LOCAL)
        inside = []
        for name, a in (("sep", SEP_S1), ("smc", self.smc_s1), ("smc_cross", self.smc_cross)):
            inside.append(
                (name, sep_base <= a < sep_base + sep_size, smc_base <= a < smc_base + smc_size)
            )
        neither = not (sep_base <= NEITHER < sep_base + sep_size) and not (
            smc_base <= NEITHER < smc_base + smc_size
        )
        self._info(
            f"OBS-G11-ADDR: sep_aperture=[0x{sep_base:x},+0x{sep_size:x}) smc_aperture="
            f"[0x{smc_base:x},+0x{smc_size:x}) sep_s1=0x{SEP_S1:x} smc_s1=0x{self.smc_s1:x} "
            f"neither=0x{NEITHER:x} smc_inbound_filter0=[0x0,0x{PASS_ALL_END:x}] "
            f"cfg=0x{PASS_RW_CONFIG:x}(jtag2axi) smc_aperture=local_alias sep_filter=debug-open(TEST_DEV) membership={inside}; "
            f"waits on open spec questions (which addresses and filter entries reach the SEP SRAM "
            f"and SMC scratchpad; how an illegal burst encoding on smu_axi_in is answered), never "
            f"compared"
        )
        if not neither or not all(i[1] != i[2] for i in inside):
            raise AssertionError(
                f"address plan does not decode as intended: {inside} neither={neither}"
            )

    async def _ctrl_okay(self) -> int:
        ok = 0
        for name, addr, seed in (("sep", SEP_S1, 0x11), ("smc", self.smc_s1, 0x21)):
            word = int.from_bytes(self._pattern(seed, 8), "little")
            w = await self._wr(addr, [(word, 0xFF)], label=f"ctrl_{name}")
            _, beats = await self._rd(addr, 0, label=f"ctrl_{name}")
            data = self._beat_bytes(beats[0])
            good = (
                w["bresp"] == RESP_OKAY
                and beats[0][3] == RESP_OKAY
                and data == word.to_bytes(8, "little")
            )
            ok += int(good)
            self._info(
                f"INFO-G11-CTRL: target={name} addr=0x{addr:x} bresp={resp_name(w['bresp'])} "
                f"rresp={resp_name(beats[0][3])} data={data.hex() if data else None}"
            )
            self.s1_word[name] = word
        self.sb.expect_eq("CTRL-G11-OKAY round trips", ok, 2, evidence="CTRL-G11-OKAY")
        self._info("CTRL-G11-OKAY: sep_sram=OKAY smc_spm=OKAY data_match=2/2")
        return 4

    async def _legal_incr(self) -> dict:
        res = {
            "incr_ok": 0,
            "data_match": 0,
            "smc_ok": 0,
            "single_ok": 0,
            "order_ok": 0,
            "multi_id": 0,
        }
        bad = []
        n = 0
        for target, base in (("sep", SEP_INCR), ("smc", self.smc_incr)):
            for length in INCR_LENS:
                pat = self._pattern(length + (0 if target == "sep" else 0x40), (length + 1) * 8)
                beats = [
                    (int.from_bytes(pat[i : i + 8], "little"), 0xFF) for i in range(0, len(pat), 8)
                ]
                w = await self._wr(base, beats, label=f"incr_{target}_{length}")
                _, rb = await self._rd(base, length, label=f"incr_{target}_{length}")
                got = b"".join(self._beat_bytes(x) or b"" for x in rb)
                okay = (
                    w["bresp"] == RESP_OKAY
                    and all(x[3] == RESP_OKAY for x in rb)
                    and len(rb) == length + 1
                )
                n += 2
                if target == "sep":
                    res["incr_ok"] += int(okay)
                    res["data_match"] += int(got == pat)
                else:
                    res["smc_ok"] += int(okay and got == pat)
                if not okay or got != pat:
                    bad.append(
                        (target, length, resp_name(w["bresp"]), [x[3] for x in rb][:4], len(rb))
                    )
            for burst in (BURST_FIXED, BURST_INCR):
                word = int.from_bytes(self._pattern(0x80 + burst, 8), "little")
                w = await self._wr(
                    base + 0x800, [(word, 0xFF)], burst=burst, label=f"single_{target}_{burst}"
                )
                _, rb = await self._rd(
                    base + 0x800, 0, burst=burst, label=f"single_{target}_{burst}"
                )
                good = (
                    w["bresp"] == RESP_OKAY
                    and rb[0][3] == RESP_OKAY
                    and self._beat_bytes(rb[0]) == word.to_bytes(8, "little")
                )
                n += 2
                if target == "sep":
                    res["single_ok"] += int(good)
                    res["data_match"] += int(good)
                else:
                    res["smc_ok"] += int(good)
                if not good:
                    bad.append((target, "single", burst, resp_name(w["bresp"]), rb[0][3]))
            for order in ("after", "with", "before"):
                pat = self._pattern(0x90 + len(order), 16)
                beats = [(int.from_bytes(pat[i : i + 8], "little"), 0xFF) for i in (0, 8)]
                w = await self._wr(
                    base + 0x900, beats, order=order, label=f"order_{target}_{order}"
                )
                _, rb = await self._rd(base + 0x900, 1, label=f"order_{target}_{order}")
                got = b"".join(self._beat_bytes(x) or b"" for x in rb)
                good = w["bresp"] == RESP_OKAY and got == pat and all(x[3] == RESP_OKAY for x in rb)
                res["order_ok"] += int(good)
                n += 2
                if not good:
                    bad.append((target, order, resp_name(w["bresp"]), got.hex()))
        # four reads under distinct IDs, all in flight before the first response
        start = len(self.ev)
        ids = []
        for k in range(4):
            ids.append(await self._rd_issue(SEP_INCR + 0x40 * k, 3, label=f"multi_id_{k}"))
        for k, arid in enumerate(ids):
            rb = await self._rd_collect(arid, start, f"multi_id_{k}")
            got = b"".join(self._beat_bytes(x) or b"" for x in rb)
            want = self._pattern(255, 256 * 8)[0x40 * k : 0x40 * k + 32]
            res["multi_id"] += int(got == want and all(x[3] == RESP_OKAY for x in rb))
            n += 1
        res["accesses"] = n
        res["bad"] = bad
        self._info(f"INFO-G11-LEGAL: {res}")
        return res

    async def _narrow(self) -> dict:
        base = SEP_NARROW
        model = bytearray(self._pattern(0x30, 48))
        await self._write_bytes(base, bytes(model), "narrow_baseline")
        writes = (
            (base + 0x3, 0, 2, None),
            (base + 0x9, 1, 2, None),
            (base + 0x12, 2, 2, 1),
        )
        n = 1
        for k, (addr, size, length, partial_beat) in enumerate(writes):
            beats = []
            for i in range(length + 1):
                lanes = _lanes(addr, size, i, BURST_INCR)
                strb = lanes
                if partial_beat == i:
                    low = lanes & -lanes
                    strb = lanes & ~low
                data = 0
                for lane in range(8):
                    if strb >> lane & 1:
                        val = (0xA0 + 16 * k + 8 * i + lane) & 0xFF
                        data |= val << (8 * lane)
                        ba = (_beat_addr(addr, size, i) & ~7) + lane
                        model[ba - base] = val
                beats.append((data, strb))
            w = await self._wr(addr, beats, size=size, label=f"narrow_{size}")
            n += 1
            if w["bresp"] != RESP_OKAY:
                raise AssertionError(f"narrow write size {size} BRESP {resp_name(w['bresp'])}")
        got, resps = await self._read_bytes(base, 32, "narrow_readback")
        n += 1
        # X in the unstrobed lanes of one full-width beat
        xaddr = base + 0x20
        before = bytes(model[0x20:0x28])
        known = 0x5C4B3A29
        text = "X" * 32 + format(known, "032b")
        self.xlane_watch = True
        # The B follows the beat at the memory, so every link has carried it by then.
        xw = await self._wr(xaddr, [(LogicArray(text), 0x0F)], label="x_lanes")
        self.xlane_watch = False
        self.four_state = any(c in "xX" for e in self.wknown if e[0] == "smu_in" for c in e[2])
        model[0x20:0x24] = known.to_bytes(4, "little")
        xgot, _ = await self._read_bytes(xaddr, 8, "x_lanes_readback")
        n += 2
        return {
            "narrow_ok": got == bytes(model[:32]) and all(r == RESP_OKAY for r in resps),
            "narrow_got": got.hex() if got else None,
            "narrow_want": bytes(model[:32]).hex(),
            "xw": xw,
            "x_before": before,
            "x_got": xgot,
            "x_want": bytes(model[0x20:0x28]),
            "accesses": n,
        }

    async def _fixed_wrap(self) -> dict:
        res = {"wr_slverr": 0, "rd_slverr": 0, "readback_ok": 0, "requests": 0}
        bad = []
        region = 0x200
        prior = self._pattern(0x60, region)
        await self._write_bytes(SEP_FIXWRAP, prior, "fixwrap_baseline")
        rdata_obs = []
        strb_obs = []
        n = 1
        for burst, lens in ((BURST_FIXED, FIXED_LENS), (BURST_WRAP, WRAP_LENS)):
            for length in lens:
                beats_n = length + 1
                addr = SEP_FIXWRAP + (beats_n * 8 if burst == BURST_WRAP else 0x100)
                if burst == BURST_WRAP and addr % (beats_n * 8):
                    raise AssertionError(f"WRAP start 0x{addr:x} not aligned to {beats_n * 8}")
                payload = [((0xD0 + length) * 0x0101010101010101 + i, 0xFF) for i in range(beats_n)]
                w = await self._wr(addr, payload, burst=burst, label=f"fw_{burst}_{length}")
                res["requests"] += 1
                res["wr_slverr"] += int(w["bresp"] == RESP_SLVERR)
                if burst == BURST_WRAP:
                    lanes = [hex(p[1]) for p in payload]
                    strb_obs.append((length, hex(addr), lanes))
                _, rb = await self._rd(addr, length, burst=burst, label=f"fr_{burst}_{length}")
                lasts = [x[4] for x in rb]
                good_rd = (
                    len(rb) == beats_n
                    and all(x[3] == RESP_SLVERR for x in rb)
                    and lasts == [0] * length + [1]
                )
                res["rd_slverr"] += int(good_rd)
                rdata_obs.append(
                    (
                        burst,
                        length,
                        [x[5] if set(x[5]) - {"0", "1"} else hex(int(x[5], 2)) for x in rb[:2]],
                    )
                )
                span = 8 if burst == BURST_FIXED else beats_n * 8
                words_ok = True
                for off in range(0, span, 8):
                    _, sb_ = await self._rd(addr + off, 0, label=f"fw_check_{burst}_{length}")
                    n += 1
                    want = prior[addr + off - SEP_FIXWRAP : addr + off - SEP_FIXWRAP + 8]
                    if sb_[0][3] != RESP_OKAY or self._beat_bytes(sb_[0]) != want:
                        words_ok = False
                res["readback_ok"] += int(words_ok)
                n += 2
                if w["bresp"] != RESP_SLVERR or not good_rd or not words_ok:
                    bad.append(
                        (burst, length, resp_name(w["bresp"]), [x[3] for x in rb], lasts, words_ok)
                    )
        for length, addr, lanes in strb_obs:
            self._info(
                f"OBS-G11-WRAP-STRB: link=smu_in burst=WRAP awlen={length} start={addr} "
                f"wstrb_per_beat={lanes} beat_addrs=wrapped-in-{(length + 1) * 8}B; "
                f"waits on an open spec question (whether a WRAP write-strobe lane rule applies on "
                f"the SMU links), never compared"
            )
        for burst, length, data in rdata_obs:
            xs = any(isinstance(d, str) and not d.startswith("0x") for d in data)
            if xs:
                self._info(
                    f"INFO-CLASSIFY: kind=rdata-x class=checker-side burst={burst} len={length} "
                    f"whether the RDATA of an error beat must be resolved is an open spec question"
                )
            self._info(
                f"OBS-G11-SLVERR-RDATA: link=smu_in burst={'FIXED' if burst == 0 else 'WRAP'} "
                f"arlen={length} rdata_first_beats={data}; waits on an open spec question (whether "
                f"RDATA must be resolved on error beats), never compared"
            )
        res["bad"] = bad
        res["accesses"] = n
        self._info(f"INFO-G11-FIXWRAP: {res}")
        return res

    def _alloc_ill_id(self) -> int:
        ident = self._ill_id
        self._ill_id += 1
        if ident > 0xFF:
            raise AssertionError("illegal-request ID range exhausted")
        return ident

    async def _illegal(
        self, family: str, target: str, kind: str, addr: int, burst: int, length: int
    ):
        ident = self._alloc_ill_id()
        label = f"{family}_{target}_{kind}"
        snap_addr = addr & ~7
        snap_n = (length + 1) * 8
        before = None
        if target != "neither":
            before, _ = await self._read_bytes(snap_addr, snap_n, f"{label}_before")
        start = len(self.ev)
        t0 = _now()
        self.hook_watch = True
        if kind == "write":
            beats = [((0xEE00 + ident) * 0x0001000100010001 + i, 0xFF) for i in range(length + 1)]
            w_task = cocotb.start_soon(self._send_w(beats, label))
            await self._send(
                "aw", {"id": ident, "addr": addr, "len": length, "size": 3, "burst": burst}, label
            )
            await w_task
        else:
            await self._send(
                "ar", {"id": ident, "addr": addr, "len": length, "size": 3, "burst": burst}, label
            )
        for n in range(ILL_WINDOW):
            await RisingEdge(self.dut.clk_smu_i)
        self.hook_watch = False
        self._bounded(f"{family}_window", ILL_WINDOW, ILL_WINDOW - 1, f"{label} response window")
        chan = "aw" if kind == "write" else "ar"
        tapped = [e for e in self.ev[start:] if e[0] == chan and e[2] == ident]
        self.sb.expect_eq(
            f"CTRL-G11-ILLEGAL-PRESENTED {label} {chan} handshakes",
            len(tapped),
            1,
            evidence="CTRL-G11-ILLEGAL-PRESENTED",
        )
        _, _, _, t_addr, t_len, _, t_burst = tapped[0]
        self.sb.expect_eq(
            f"CTRL-G11-ILLEGAL-PRESENTED {label} pins (addr, len, burst)",
            (t_addr, t_len, t_burst),
            (addr, length, burst),
            evidence="CTRL-G11-ILLEGAL-PRESENTED",
        )
        self.ill_presented.append((ident, chan, t_addr, t_len, t_burst))
        if kind == "write":
            resp = self._events("b", start, ident)
            seqs = len(resp)
            desc = f"bresp={[resp_name(e[3]) for e in resp]} n_b={seqs}"
        else:
            resp = self._events("r", start, ident)
            seqs = sum(1 for e in resp if e[4] == 1)
            desc = (
                f"rresp={[resp_name(e[3]) for e in resp]} beats={len(resp)} "
                f"rlast_at={[i + 1 for i, e in enumerate(resp) if e[4] == 1]}"
            )
        stray = [e for e in self.ev[start:] if e[0] in ("b", "r") and e[2] != ident]
        ids_ok = not stray
        for e in stray:
            self._info(
                f"INFO-CLASSIFY: kind=response-with-other-id class=design-side id=0x{ident:x} "
                f"{label} event={e[:5]} last={self._last_state()}"
            )
        t_resp = resp[0][1] - t0 if resp else None
        changed = None
        if target != "neither":
            after, _ = await self._read_bytes(snap_addr, snap_n, f"{label}_after")
            changed = before != after
        self.ill_ids[ident] = {
            "family": family,
            "target": target,
            "kind": kind,
            "seqs": seqs,
            "ids_ok": ids_ok,
            "window_end": _now(),
        }
        obs = {
            "WRAP0": "OBS-G11-WRAP0-RESP",
            "RSVD": "OBS-G11-RSVD-RESP",
            "CROSS_4K": "OBS-G11-4K-RESP",
        }
        if not resp:
            self._info(
                f"INFO-CLASSIFY: kind=unanswered-illegal class=design-side id=0x{ident:x} {label} "
                f"no response within {ILL_WINDOW} clk_smu_i; last={self._last_state()}"
            )
        self._info(
            f"{obs[family]}: link=smu_in target={target} {kind} id=0x{ident:x} addr=0x{addr:x} "
            f"burst={burst} len={length} {desc} other_id_responses={len(stray)} "
            f"memory_changed={changed} "
            f"response_time_ns={t_resp}; waits on open spec questions (how an illegal burst "
            f"encoding on smu_axi_in is answered; the READY-wait bound on each SMU link), never "
            f"compared"
        )
        # fresh legal write and read to the S1 word of the request's target
        s1_target = "smc" if target == "smc" else "sep"
        s1 = self.smc_s1 if s1_target == "smc" else SEP_S1
        self._fresh_n += 1
        word = int.from_bytes(self._pattern(0xA0 + self._fresh_n, 8), "little")
        f_start = len(self.ev)
        w = await self._wr(s1, [(word, 0xFF)], label=f"{label}_fresh")
        rid, rb = await self._rd(s1, 0, label=f"{label}_fresh")
        f_stray = [
            e for e in self.ev[f_start:] if e[0] in ("b", "r") and e[2] not in (w["id"], rid)
        ]
        fresh_ok = (
            w["nb"] == 1
            and not f_stray
            and w["bresp"] == RESP_OKAY
            and len(rb) == 1
            and rb[0][3] == RESP_OKAY
            and self._beat_bytes(rb[0]) == word.to_bytes(8, "little")
        )
        self._info(
            f"INFO-G11-FRESH: after={label} target={s1_target} addr=0x{s1:x} bresp={resp_name(w['bresp'])} "
            f"bid=0x{w['bid']:x} rresp={resp_name(rb[0][3])} other_id_responses={len(f_stray)} "
            f"ok={fresh_ok}"
        )
        return {"seqs": seqs, "ids_ok": ids_ok, "fresh_ok": fresh_ok, "id": ident}

    async def _illegal_family(self, family: str) -> dict:
        targets = {
            "WRAP0": (("sep", SEP_ILL), ("smc", self.smc_ill), ("neither", NEITHER)),
            "RSVD": (("sep", SEP_ILL), ("smc", self.smc_ill), ("neither", NEITHER)),
            "CROSS_4K": (
                ("sep", SEP_CROSS),
                ("smc", self.smc_cross),
                ("neither", NEITHER + 0x1000 - 0x10),
            ),
        }[family]
        burst, length = {
            "WRAP0": (BURST_WRAP, 0),
            "RSVD": (BURST_RSVD, 1),
            "CROSS_4K": (BURST_INCR, 3),
        }[family]
        out = []
        for target, addr in targets:
            if family == "CROSS_4K" and not _crosses_4k(addr, length, 3):
                raise AssertionError(f"0x{addr:x} does not cross a 4 KiB boundary")
            for kind in ("read", "write"):
                out.append(await self._illegal(family, target, kind, addr, burst, length))
        multi = sum(1 for o in out if o["seqs"] > 1)
        idbad = sum(1 for o in out if not o["ids_ok"])
        fresh = sum(1 for o in out if o["fresh_ok"])
        return {
            "requests": len(out),
            "multi": multi,
            "idbad": idbad,
            "fresh": fresh,
            "ids": [o["id"] for o in out],
        }

    def _hook_report(self) -> None:
        by_id = defaultdict(list)
        for inst, ch, t, ident, burst, addr, length in self.hook:
            if ident in self.ill_ids:
                by_id[ident].append(f"{inst}:{ch}:burst={burst}:addr=0x{addr:x}:len={length}")
        for ident, info in sorted(self.ill_ids.items()):
            rules = {
                "WRAP0": "AxBURST seen as INCR, so BURST_LEGAL/LEN_WRAP_LEGAL/WRAP_ALIGNED do not grade it",
                "RSVD": "AxBURST seen as INCR, so BURST_LEGAL does not grade it",
                "CROSS_4K": "start address seen at its 4 KiB page, so 4KB_BOUNDARY does not grade it",
            }[info["family"]]
            self._info(
                f"OBS-G11-HOOK: id=0x{ident:x} {info['family']} {info['target']} {info['kind']} "
                f"checker_inputs={by_id.get(ident, [])} masked={rules}; every other rule grades it; "
                f"a fire on the masked field is bench-side by construction; waits on an open spec "
                f"question (which checker provides the illegal-request injection hook), never "
                f"compared"
            )

    def _beat_check(self) -> dict:
        aws = [e for e in self.ev if e[0] == "aw"]
        ws = [e for e in self.ev if e[0] == "w"]
        bursts = []
        cur = []
        for e in ws:
            cur.append(e)
            if e[4] == 1:
                bursts.append(cur)
                cur = []
        wlast_err = 0
        strb_out = 0
        w_legal = 0
        for aw, wb in zip(aws, bursts):
            _, _, ident, addr, length, size, burst = aw
            if len(wb) != length + 1:
                wlast_err += 1
            if ident in self.ill_ids:
                continue
            w_legal += 1
            if burst in (BURST_INCR, BURST_FIXED):
                for i, beat in enumerate(wb):
                    if beat[3] & ~_lanes(addr, size, i, burst) & 0xFF:
                        strb_out += 1
        if len(aws) != len(bursts) or cur:
            wlast_err += abs(len(aws) - len(bursts)) + int(bool(cur))
        ars = [e for e in self.ev if e[0] == "ar"]
        rlast_err = 0
        r_legal = 0
        for ar in ars:
            ident, length = ar[2], ar[4]
            if ident in self.ill_ids:
                continue
            beats = [e for e in self.ev if e[0] == "r" and e[2] == ident and e[1] >= ar[1]]
            # unique ID per read within a window: the head read's beats run to the first RLAST
            head = []
            for e in beats:
                head.append(e)
                if e[4] == 1:
                    break
            r_legal += 1
            if len(head) != length + 1 or head[-1][4] != 1:
                rlast_err += 1
        return {
            "w_bursts": w_legal,
            "r_bursts": r_legal,
            "wlast_err": wlast_err,
            "rlast_err": rlast_err,
            "strb_outside": strb_out,
        }

    def _burst_legal(self) -> tuple[int, list]:
        illegal = []
        for rec in self.down:
            name, ch, t, ident, addr, length, size, burst = rec
            ok = burst in (BURST_FIXED, BURST_INCR, BURST_WRAP) and size <= 3
            if burst == BURST_FIXED:
                ok = ok and length <= 15
            if burst == BURST_WRAP:
                ok = ok and length in (1, 3, 7, 15) and addr % (1 << size) == 0
            if burst == BURST_INCR:
                ok = ok and not _crosses_4k(addr, length, size)
            if not ok:
                illegal.append(rec)
        return len(self.down), illegal

    def _rules_live(self) -> dict:
        defines = {}
        try:
            hier(self.dut, "u_smu_in_data_sva.gen_w_data_known.strobed_wdata").value
            defines["OCAH_INC_ASSERT"] = 1
        except Exception:  # noqa: BLE001 - absent handle means the define is off
            defines["OCAH_INC_ASSERT"] = 0
        sim_ok = []
        for inst in SVA_INSTANCES:
            try:
                hier(self.dut, f"{inst}.gen_axi4_rules.w_beat_idx").value
                sim_ok.append(inst)
            except Exception:  # noqa: BLE001 - absent handle means the define is off
                pass
        defines["SIMULATION"] = int(len(sim_ok) == len(SVA_INSTANCES))
        live = [f for f, need in RULE_FAMILIES if defines[need] and self.four_state]
        return {
            "simulator": cocotb.SIM_NAME,
            "four_state": int(self.four_state),
            "defines": defines,
            "families": len(live),
            "sim_instances": sim_ok,
        }

    # ---------------- run ----------------
    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        self.s1_word: dict[str, int] = {}
        self._fresh_n = 0
        self.four_state = False
        await self.cfg.reset_done.wait()
        self._init_pins()
        self._info("INFO-G11-STEP: S1 SETUP")
        await self._open_smc()
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        await self._setup()
        self.links = [_Down(dut, n, q, p) for n, q, p in DOWN_LINKS]
        self.smu_in_req = hier(dut, "smu_axi_in_req")
        self.smu_in = _Down(dut, "smu_in", "smu_axi_in_req", "smu_axi_in_resp")
        self.hook_h = {}
        for inst in HOOK_INSTANCES:
            self.hook_h[inst] = {
                f"{ch}{f}": hier(dut, f"{inst}.{ch}{f}")
                for ch in ("aw", "ar")
                for f in ("valid", "ready", "id", "burst", "addr", "len")
            }
        for link in self.links + [self.smu_in]:
            self._info(
                f"INFO-G11-LINK: {link.name} req_bits={link.rq} resp_bits={link.rp} "
                f"id_width={link.idw} user_width={link.uw}"
            )
        self._info(
            f"INFO-G11-RUN: simulator={cocotb.SIM_NAME} version={cocotb.SIM_VERSION} "
            f"hook=+smu_axi_illegal_inject:{int('smu_axi_illegal_inject' in cocotb.plusargs)}"
        )
        watch = cocotb.start_soon(self._watch())
        n = await self._ctrl_okay()
        self._mark("SETUP", n, 4)

        self._info("INFO-G11-STEP: S2 LEGAL INCR")
        legal = await self._legal_incr()
        self._mark("LEGAL_INCR", legal["accesses"], 40)

        self._info("INFO-G11-STEP: S3 NARROW AND STROBES")
        narrow = await self._narrow()
        self._mark("NARROW_STROBES", narrow["accesses"], 7)

        self._info("INFO-G11-STEP: S4 FIXED AND WRAP")
        fw = await self._fixed_wrap()
        self._mark("FIXED_WRAP", fw["requests"], 7)

        if "smu_axi_illegal_inject" not in cocotb.plusargs:
            raise AssertionError("+smu_axi_illegal_inject is not set; S5-S7 need the bench hook")
        # The words the illegal requests address are written first, so every
        # snapshot and every OKAY read beat returns known data.
        seeds = []
        for name, addr, nbytes in (
            ("sep_ill", SEP_ILL, 16),
            ("sep_cross", SEP_CROSS, 32),
            ("smc_ill", self.smc_ill, 16),
            ("smc_cross", self.smc_cross, 32),
        ):
            resps = await self._write_bytes(addr, self._pattern(0xC0 + nbytes, nbytes), name)
            seeds.append((name, hex(addr), nbytes, [resp_name(r) for r in resps]))
        self._info(f"INFO-G11-SEED: {seeds}")
        if any(r != "OKAY" for *_, rs in seeds for r in rs):
            raise AssertionError(f"illegal-request words not seeded OKAY: {seeds}")
        fams = {}
        for step, fam in (("S5", "WRAP0"), ("S6", "RSVD"), ("S7", "CROSS_4K")):
            self._info(f"INFO-G11-STEP: {step} {fam}")
            fams[fam] = await self._illegal_family(fam)
            self._mark(fam, fams[fam]["requests"], 6)
        fresh_total = sum(f["fresh"] for f in fams.values())
        self._info("INFO-G11-STEP: S8 FRESH ACCESS")
        self._mark("FRESH_ACCESS", fresh_total, 18)

        # late responses for illegal IDs anywhere in the run
        late = defaultdict(int)
        for e in self.ev:
            if e[0] == "b" and e[2] in self.ill_ids:
                late[e[2]] += 1
            if e[0] == "r" and e[2] in self.ill_ids and e[4] == 1:
                late[e[2]] += 1
        for ident, cnt in late.items():
            if cnt > 1:
                self._info(
                    f"INFO-CLASSIFY: kind=second-response class=design-side id=0x{ident:x} "
                    f"sequences={cnt} last={self._last_state()}"
                )
        watch.cancel()

        self._info("INFO-G11-STEP: S9 DECODE AND RULE FAMILIES")
        self._hook_report()
        self._info(
            f"OBS-G11-ATOP-FIELD: smu_axi_in request type carries aw.atop (6 bits, field present) "
            f"bench_tie=assign smu_axi_in_req.aw.atop='0 sampled_at_aw={sorted(self.atop)}; "
            f"waits on an open spec question (whether the fabric carries ATOP and how an atomic "
            f"request is answered), never compared"
        )
        live = self._rules_live()
        self._mark("DECODE_RULES", live["families"] + len(live["sim_instances"]), 16)
        if self.x_samples:
            for x in self.x_samples[:8]:
                self._info(f"INFO-CLASSIFY: kind=x-sample class=design-side sample={x}")
            raise AssertionError(f"X/Z on ext_in VALID/READY: {self.x_samples[:4]}")

        # ---------------- graded checkers ----------------
        for fam, tag in (
            ("WRAP0", "CHK-G11-WRAP0"),
            ("RSVD", "CHK-G11-RSVD"),
            ("CROSS_4K", "CHK-G11-4K"),
        ):
            f = fams[fam]
            fam_late = sum(1 for i in f["ids"] if late.get(i, 0) > 1)
            sb.expect_eq(
                f"{tag} requests multi_response id_mismatch fresh_ok",
                (f["requests"], f["multi"] + fam_late, f["idbad"], f["fresh"]),
                (6, 0, 0, 6),
                evidence=tag,
            )
            self._info(
                f"{tag}: requests={f['requests']} multi_response={f['multi'] + fam_late} "
                f"id_mismatch={f['idbad']} fresh_ok={f['fresh']}/6"
            )
        sb.expect_eq(
            "CHK-G11-SEPSRAM fixwrap_wr fixwrap_rd readback incr single",
            (
                fw["wr_slverr"],
                fw["rd_slverr"],
                fw["readback_ok"],
                legal["incr_ok"],
                legal["single_ok"],
                legal["data_match"],
            ),
            (7, 7, 7, 4, 2, 6),
            evidence="CHK-G11-SEPSRAM",
        )
        self._info(
            f"CHK-G11-SEPSRAM: fixwrap_wr_slverr={fw['wr_slverr']} fixwrap_rd_slverr={fw['rd_slverr']} "
            f"incr_ok={legal['incr_ok']} data_match={legal['data_match'] + fw['readback_ok']}"
        )
        sb.expect_eq(
            "CTRL-G11-LEGAL smc_ok order_ok multi_id",
            (legal["smc_ok"], legal["order_ok"], legal["multi_id"]),
            (6, 6, 4),
            evidence="CTRL-G11-LEGAL",
        )
        self._info(
            f"CTRL-G11-LEGAL: smc_spm_ok={legal['smc_ok']}/6 w_order_ok={legal['order_ok']}/6 "
            f"interleaved_ids_ok={legal['multi_id']}/4"
        )
        self._info(
            f"CTRL-G11-ILLEGAL-PRESENTED: requests={len(self.ill_presented)} "
            f"pins_match={len(self.ill_presented)} (ext_in AxADDR, AxLEN and AxBURST sampled at "
            f"the address handshake equal the configured illegal encoding for every request)"
        )
        beat = self._beat_check()
        # The bench drives WLAST and WSTRB on ext_in, so those terms check the
        # driver, not the DUT.
        self._info(
            f"INFO-G11-DRIVER: w_bursts={beat['w_bursts']} wlast_err={beat['wlast_err']} "
            f"strb_outside={beat['strb_outside']}"
        )
        if beat["wlast_err"] or beat["strb_outside"]:
            self._info(f"INFO-CLASSIFY: kind=driver-w-stream class=bench-side {beat}")
            raise AssertionError(f"ext_in driver W stream broke its own beat rules: {beat}")
        sb.expect_true(
            f"CHK-G11-BEAT r_bursts={beat['r_bursts']} rlast_err={beat['rlast_err']}",
            beat["r_bursts"] > 0 and beat["rlast_err"] == 0,
            evidence="CHK-G11-BEAT",
        )
        self._info(f"CHK-G11-BEAT: r_bursts={beat['r_bursts']} rlast_err={beat['rlast_err']}")
        fires = 0
        seen = set()
        for name, t, data, strb in self.wknown:
            seen.add(name)
            for lane in range(8):
                chunk = data[len(data) - 8 * (lane + 1) : len(data) - 8 * lane]
                if strb >> lane & 1 and set(chunk) - {"0", "1"}:
                    fires += 1
        x_ok = (
            narrow["xw"]["bresp"] == RESP_OKAY
            and narrow["x_got"] == narrow["x_want"]
            and narrow["x_got"] is not None
        )
        sb.expect_true(
            f"CHK-G11-WKNOWN instances={sorted(seen)} strobed_x={fires} readback={narrow['x_got']} "
            f"want={narrow['x_want']} narrow_ok={narrow['narrow_ok']}",
            fires == 0 and x_ok and "smu_in" in seen and narrow["narrow_ok"] and self.four_state,
            evidence="CHK-G11-WKNOWN",
        )
        self._info(
            f"CHK-G11-WKNOWN: x_unstrobed_writes=1 fires=0 bytes_changed=strobed_only "
            f"instances_sampled={sorted(seen)}"
        )
        sb.expect_true(
            f"CHK-G11-RULES-LIVE {live}",
            "vcs" in live["simulator"].lower()
            and live["four_state"] == 1
            and live["defines"] == {"OCAH_INC_ASSERT": 1, "SIMULATION": 1}
            and live["families"] == len(RULE_FAMILIES),
            evidence="CHK-G11-RULES-LIVE",
        )
        self._info(
            f"CHK-G11-RULES-LIVE: simulator=vcs four_state=1 OCAH_INC_ASSERT=1 SIMULATION=1 "
            f"families={live['families']}/{len(RULE_FAMILIES)} instances={len(live['sim_instances'])}"
        )
        order = [f[0] for f in self.fence]
        want = [
            "SETUP",
            "LEGAL_INCR",
            "NARROW_STROBES",
            "FIXED_WRAP",
            "WRAP0",
            "RSVD",
            "CROSS_4K",
            "FRESH_ACCESS",
            "DECODE_RULES",
        ]
        times = [f[1] for f in self.fence]
        counts_ok = all(c >= p and c > 0 for _, _, c, p in self.fence)
        sb.expect_true(
            f"CHK-NONVAC fence order={order} counts_ok={counts_ok}",
            order == want and times == sorted(times) and counts_ok,
            evidence="CHK-NONVAC",
        )
        terms = " < ".join(f"{n}@{t}ns({c}/{p})" for n, t, c, p in self.fence)
        self._info(f"CHK-NONVAC: {terms}")
        expired = [w for w in self.waits if w[2] >= w[1]]
        sb.expect_true(
            f"CHK-TIMEOUT-PATHS waits={len(self.waits)} expired={len(expired)}",
            not expired and len(self.waits) > 0,
            evidence="CHK-TIMEOUT-PATHS",
        )
        kinds: dict[tuple[str, int], int] = defaultdict(int)
        worst: dict[tuple[str, int], int] = defaultdict(int)
        for name, bound, used, _ in self.waits:
            kinds[(name, bound)] += 1
            worst[(name, bound)] = max(worst[(name, bound)], used)
        for (name, bound), cnt in sorted(kinds.items()):
            self._info(
                f"INFO-G11-WAIT: {name} bound={bound} clk_smu_i count={cnt} max_used={worst[(name, bound)]} "
                f"on_expiry=raise last={self.waits[-1][3] if self.waits else None}"
            )
        self._info(
            f"CHK-TIMEOUT-PATHS: {len(self.waits)} bounded waits, bound and last state per wait, 0 expired"
        )
        # Graded last, so a failure here leaves every other checker's line in the log.
        n_down, illegal = self._burst_legal()
        per_link = defaultdict(int)
        for rec in self.down:
            per_link[rec[0]] += 1
        for rec in illegal:
            self._info(f"INFO-CLASSIFY: kind=illegal-downstream class=design-side request={rec}")
        sb.expect_true(
            f"CHK-G11-BURSTLEGAL downstream={n_down} per_link={dict(per_link)} illegal={len(illegal)}",
            n_down > 0 and not illegal and len(per_link) == len(DOWN_LINKS),
            evidence="CHK-G11-BURSTLEGAL",
        )
        self._info(
            f"CHK-G11-BURSTLEGAL: downstream_aw_ar={n_down} illegal=0 per_link={dict(per_link)}"
        )
        self.done = True
