# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SMU AXI links across the SMC primary reset with requests in flight. No Force.

The SMC primary reset is the AND of the stable cold reset, the de-glitched
cool-reset pin and the FLR cool reset (``hw/sys/smc/doc/clk_rst.adoc``,
"Primary and Warm Reset"), and it is the aresetn of every AXI link the bench
grades. This sequence leaves requests accepted and unanswered on the external
inbound port and on the DTP JTAG2AXI port, asserts the primary reset from the
cool-reset pin and then from an FLR request, and watches every link on every
``clk_smu_i`` edge:

S1 SETUP: the inbound window, the SMC aperture alias and the outbound filter
   are opened over JTAG2AXI; one write then read on each drivable route is the
   pre-reset reference.
S2 JTAG2AXI: a write and read of an SMC-window word, and a write and read
   toward the SEP aperture and toward neither aperture, sampled at
   ``xbar_smc_out`` and at the routing-table target port.
S3 LOAD: ext_in reads and writes under distinct IDs toward both apertures with
   BREADY and RREADY withheld, and one JTAG2AXI access toward ext_out that the
   bench responder answers without a hold.
S4 COOL RESET: the pin is held past the 32-sample de-glitcher; every VALID of
   every checked link is sampled on every edge with the primary reset low.
S5 RELEASE WATCH: every B and R on smu_in and dtp_dbg after release is paired
   with a request accepted after release.
S6 LIVENESS: X-free handshakes from release, then a fresh write and read on
   every route that answered OKAY before the reset.
S7 FLR LEG: S3 to S6 again with the FLR cool reset as the source.
S8 TIMEOUT: every wait is bounded, and an expiry fails the leaf with the last
   handshake and reset-net sample. Every CHK-G2A line, the ordered CHK-NONVAC
   fence and CHK-TIMEOUT-PATHS print here.
S9 HELD_RESP: the responder holds the B of one JTAG2AXI write toward ext_out
   across a cool reset. The responder resets on rst_cold_n_o, but the link's
   aresetn is the primary reset, which withdraws the request; the responder
   drops the held B on the primary reset's falling edge, as a subordinate on
   that reset must. What the DUT presents after release (B on smu_out, the
   crossbar ports and dtp_dbg, and the JTAG2AXI status) is printed as
   OBS-G2A-HELD-RESP, never compared. A B presented after release would be
   the bench's own protocol violation on that link, so it is not driven
   (HELD_B_AFTER_RELEASE).
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import cocotb
from cocotb.triggers import ClockCycles, Event, FallingEdge, RisingEdge
from cocotb.utils import get_sim_time
from ocah_axi_vip import RESP_OKAY, AxiTimingProfile, resp_name
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import c_header_u32, reset_unit_u32, smc_addr
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_compose_helpers import hier
from seq_lib.smu_filter_helpers import (
    PASS_ALL_END,
    program_inbound0_window,
    program_outbound0_pass_all,
    program_smc_aperture_local_alias,
)
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    SMC_DBG_AXSIZE_4B,
    SMC_DBG_AXSIZE_8B,
    axi64_pack32,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    pack_single_op,
    require_jtag_tdo_resolved,
    unpack_single_op,
)
from seq_lib.smu_tb_pins import smc_primary_reset

# --- addresses (generated headers; the routing table of hw/sys/smu/doc/index.adoc) ---
SPM_BASE = smc_addr("SMC_TOP_SPM_MEMORY_BASE_ADDR")
FLR_COUNTER = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_COUNTER_VALUE_BASE_ADDR")
FLR_RESET_COUNTER = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR")
ISOLATE_REQ_SMC_REG = smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_SMC_REG_BASE_ADDR")
ISOLATE_REQ_SMC_BM = reset_unit_u32("RESET_UNIT__ISOLATE_REQ_SMC_REG__ISOLATE_REQ_SMC_REG_bm")
RESET_COUNTER_BM = reset_unit_u32(
    "RESET_UNIT__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_bm"
)
_SEP_CPU_CTRL_H = (
    Path(__file__).resolve().parents[6] / "hw/sys/sep/regs/gen/c/blocks/sep_cpu_ctrl.h"
)
# The SEP aperture the leaf leaves at its SEP_GLOBAL_BASE_ADDR / SEP_REGION_SIZE
# reset values.
SEP_APERTURE_BASE = c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SEP_GLOBAL_BASE_ADDR__ADDR_reset")
SEP_APERTURE_SIZE = c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SEP_REGION_SIZE__SIZE_reset")
# Cell addresses: SPM words through the SMC aperture (local alias, smc_addr);
# SEP-aperture words inside the reset window; an address in neither aperture
# for the smc_out -> ext_out row of the routing table.
SMC_CELL = SPM_BASE + 0x700
SMC_LOAD = SPM_BASE + 0x800
SEP_CELL = SEP_APERTURE_BASE + 0x1000
SEP_LOAD = SEP_APERTURE_BASE + 0x2000
if SEP_LOAD + 0x80 > SEP_APERTURE_BASE + SEP_APERTURE_SIZE:
    raise AssertionError(
        f"SEP cells 0x{SEP_CELL:x}/0x{SEP_LOAD:x} lie outside the SEP aperture reset window "
        f"[0x{SEP_APERTURE_BASE:x}, +0x{SEP_APERTURE_SIZE:x})"
    )
EXT_CELL = 0x55_5555_5555_5500
EXT_LOAD = 0x55_5555_5555_5600
ADDR56 = (1 << 56) - 1

# --- bounds, all counted in clk_smu_i or clk_ref_i edges ---
DEGLITCH_SAMPLES = 32
ASSERT_BOUND_REF = 128
HOLD_PAST_ASSERT_REF = 40
RELEASE_BOUND_REF = 8192
FLR_ASSERT_BOUND_REF = 4096
FLR_RESET_HOLD = 64
HANDSHAKE_BOUND_SMU = 4096
SEP_RESET_BOUND_REF = 16384
J2A_POLL_LIMIT = 32
J2A_HELD_POLLS = 24
HELD_SEEN_BOUND_SMU = 48_000
AXI_BOUND_NS = 100_000
# The responder holds the one response it is armed for this many clk_smu_i
# cycles after the request, longer than the reset assertion plus release.
RESP_HOLD_CYCLES = 24_000
# BREADY / RREADY withheld on ext_in once the load is armed, cycles.
LOAD_READY_HOLD = 20_000
RESPONDER_DEPTH = 4
LOAD_IDS = {
    "w_smc": (0x10, 0x11),
    "w_sep": (0x12, 0x13),
    "r_smc": (0x14, 0x15),
    "r_sep": (0x16, 0x17),
}
FRESH_IDS = {"cool": (0x41, 0x42, 0x43, 0x44), "flr": (0x51, 0x52, 0x53, 0x54)}

RESET_NETS = (
    "rst_primary_smc_clk_n_o",
    "rst_cold_n_o",
    "obs_smc_rst_n_o",
    "obs_xbar_rst_n_o",
    "sep_reset_n",
)
XBAR = "u_dut.u_smu.gen_sep.u_smu_axi_xbar"
# (name, request net, response net) of every checked link (tb_wrapper_top.sv
# checker region): the 13 ocah_axi_sva instances on rst_primary_smc_clk_n_o.
LINKS = (
    ("smu_in", "smu_axi_in_req", "smu_axi_in_resp"),
    ("incut", "u_dut.u_smu.smu_axi_in_cut_req", "u_dut.u_smu.smu_axi_in_cut_resp"),
    ("xbar_ext_in", f"{XBAR}.ext_in_req_i", f"{XBAR}.ext_in_resp_o"),
    ("xbar_sep_in", f"{XBAR}.sep_in_req_o", f"{XBAR}.sep_in_resp_i"),
    ("iwc_sep", "u_dut.u_smu.sep_smn_inbound_axi_req", "u_dut.u_smu.sep_smn_inbound_axi_resp"),
    ("xbar_smc_in", f"{XBAR}.smc_in_req_o", f"{XBAR}.smc_in_resp_i"),
    ("iwc_smc", "u_dut.u_smu.smc_sys_axi_in_req", "u_dut.u_smu.smc_sys_axi_in_resp"),
    ("dtp_dbg", "u_dut.u_smu.dtp_axi_smc_dbg_req", "u_dut.u_smu.dtp_axi_smc_dbg_resp"),
    ("xbar_smc_out", f"{XBAR}.smc_out_req_i", f"{XBAR}.smc_out_resp_o"),
    ("xbar_ext_out", f"{XBAR}.ext_out_req_o", f"{XBAR}.ext_out_resp_i"),
    ("smu_out", "smu_axi_out_req", "smu_axi_out_resp"),
    ("xbar_sep_out", f"{XBAR}.sep_out_req_i", f"{XBAR}.sep_out_resp_o"),
    ("sep_to_smc", "u_dut.u_smu.sep_ext_to_smc_axi_req", "u_dut.u_smu.sep_ext_to_smc_axi_resp"),
)
# Links read on every edge; any VALID on them opens a sampling window of
# ACTIVE_TAIL_EDGES over the DETAIL links.
CHEAP = ("smu_in", "dtp_dbg", "smu_out")
ACTIVE_TAIL_EDGES = 1024
# Edges after each release on which all checked links are sampled.
POST_RELEASE_FULL_EDGES = 2048
# Links whose handshake payloads are decoded; the others are counted.
DETAIL = (
    "smu_in",
    "dtp_dbg",
    "xbar_smc_out",
    "xbar_sep_in",
    "xbar_smc_in",
    "xbar_ext_out",
    "smu_out",
)
HS_SIGNALS = (
    "aw_valid",
    "aw_ready",
    "w_valid",
    "w_ready",
    "b_valid",
    "b_ready",
    "ar_valid",
    "ar_ready",
    "r_valid",
    "r_ready",
)
VALID_SIGNALS = ("aw_valid", "w_valid", "ar_valid", "b_valid", "r_valid")
# Address and data width of every checked link (ocah_axi_sva ADDR_WIDTH /
# DATA_WIDTH in the checker region).
LINK_ADDR_BITS = 56
LINK_DATA_BITS = 64
NOT_DRIVABLE = (
    (
        "SEP_LSU_TO_EXT_OUT",
        "the SEP debug-module LSU probe is not armed, so xbar_sep_out carries no traffic and "
        "+axi_sva_need_xbar_sep_out is not set",
    ),
    (
        "SEP_LSU_TO_SMC",
        "the SEP debug-module LSU probe is not armed, so sep_to_smc carries no traffic and "
        "+axi_sva_need_sep_to_smc is not set",
    ),
    (
        "EXT_IN_TO_SEP_OKAY",
        "the SEP aperture at its reset window maps no SEP resource; widening it needs "
        "the SEP debug module",
    ),
    (
        "J2A_TO_SEP_OKAY",
        "the SEP aperture at its reset window maps no SEP resource; widening it needs "
        "the SEP debug module",
    ),
    (
        "J2A_MULTI_OUTSTANDING",
        "one JTAG2AXI access per leg: the port holds a single operation",
    ),
    (
        "HELD_R",
        "the held-response leg holds one B; a held R is dropped at the reset the same way",
    ),
    (
        "HELD_B_AFTER_RELEASE",
        "the only responder outside the link's reset is the bench's; a B it presented after "
        "release would answer a request the link's reset withdrew, a protocol violation by the "
        "bench, so the SMU's handling of one waits on an open spec question (whether a request "
        "accepted before a reset completes or is withdrawn)",
    ),
    ("OTP_SMC", "the DTP OTP JTAG AXI-Lite port is outside this leaf's stimulus"),
    ("OTP_SEP", "the DTP OTP JTAG AXI-Lite port is outside this leaf's stimulus"),
    ("XTRIG_CSR", "the cross-trigger CSR port is outside this leaf's stimulus"),
)


ORPHAN_RULE = {"b": "OCAH_AXI_B_NOT_BEFORE_AW", "r": "OCAH_AXI_R_NOT_BEFORE_AR"}
# Reset of the agent that answers on each orphan-tracked link.
RESPONDER_RESET = {
    "smu_in": "rst_primary_smc_clk_n_o",
    "dtp_dbg": "rst_primary_smc_clk_n_o",
    "smu_out": "rst_cold_n_o",
}


def _now() -> int:
    return int(get_sim_time(unit="ns"))


class _Link:
    """Field positions in one pulp AXI4 request/response struct pair."""

    def __init__(self, dut, name: str, req_path: str, resp_path: str) -> None:
        self.name = name
        self.req = hier(dut, req_path)
        self.resp = hier(dut, resp_path)
        rq, rp = len(self.req), len(self.resp)
        a, d = LINK_ADDR_BITS, LINK_DATA_BITS
        # req = 2I + 2A + 9D/8 + 3U + 70 ; resp = 2I + D + 2U + 10
        x = rq - (2 * a + 9 * d // 8 + 70)
        y = rp - (d + 10)
        u = x - y
        i2 = y - 2 * u
        if u < 0 or i2 <= 0 or i2 % 2:
            raise AssertionError(
                f"{name}: {rq}/{rp}-bit request/response do not decode as AXI4 with "
                f"{a}-bit address and {d}-bit data"
            )
        self.idw, self.uw = i2 // 2, u
        self.rq_bits, self.rp_bits = rq, rp
        idw, uw = self.idw, self.uw
        ar = idw + a + 29 + uw
        w = d + d // 8 + 1 + uw
        q = {"r_ready": 0, "ar_valid": 1}
        base = 2
        q["ar_user"] = (base, uw)
        q["ar_burst"] = (base + uw + 16, 2)
        q["ar_len"] = (base + uw + 21, 8)
        q["ar_addr"] = (base + uw + 29, a)
        q["ar_id"] = (base + uw + 29 + a, idw)
        q["b_ready"] = 2 + ar
        q["w_valid"] = 3 + ar
        q["aw_valid"] = 4 + ar + w
        base = 5 + ar + w
        q["aw_user"] = (base, uw)
        q["aw_atop"] = (base + uw, 6)
        q["aw_burst"] = (base + uw + 22, 2)
        q["aw_len"] = (base + uw + 27, 8)
        q["aw_addr"] = (base + uw + 35, a)
        q["aw_id"] = (base + uw + 35 + a, idw)
        r = idw + d + 3 + uw
        b = idw + 2 + uw
        p = {
            "r_last": uw,
            "r_resp": (uw + 1, 2),
            "r_id": (uw + 3 + d, idw),
            "r_valid": r,
            "b_resp": (r + 1 + uw, 2),
            "b_id": (r + 3 + uw, idw),
            "b_valid": r + 1 + b,
            "w_ready": r + 2 + b,
            "ar_ready": r + 3 + b,
            "aw_ready": r + 4 + b,
        }
        self.q, self.p = q, p
        self.hs_idx = []
        for sig in HS_SIGNALS:
            if sig in q:
                self.hs_idx.append((sig, True, rq - 1 - q[sig]))
            else:
                self.hs_idx.append((sig, False, rp - 1 - p[sig]))

    def handshakes(self, qs: str, ps: str) -> dict[str, str]:
        return {sig: (qs[i] if is_req else ps[i]) for sig, is_req, i in self.hs_idx}

    @staticmethod
    def field(bits: str, lsb_width: tuple[int, int]) -> int | None:
        lsb, width = lsb_width
        text = bits[len(bits) - lsb - width : len(bits) - lsb]
        if set(text) - {"0", "1"}:
            return None
        return int(text, 2)

    def bit(self, bits: str, lsb: int) -> str:
        return bits[len(bits) - 1 - lsb]


class _Watch:
    """Per-edge passive sampler of every checked link and the five reset nets."""

    def __init__(self, dut, links: list[_Link], log) -> None:
        self.dut = dut
        self.log = log
        self.clk = dut.clk_smu_i
        self.links = links
        self.rst = [(n, getattr(dut, n)) for n in RESET_NETS]
        self.events: list[tuple] = []
        self.last: dict[tuple[str, str], tuple] = {}
        self.hs_count: dict[str, int] = defaultdict(int)
        self.edges = 0
        # reset-window state (set by the sequence)
        self.window: str | None = None
        self.reset_edges: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        self.low_edges: dict[str, int] = defaultdict(int)
        # requests outstanding per (link, kind, id) on the every-edge links
        self.outst: dict[tuple[str, str, int], int] = defaultdict(int)
        self.cleared: set[tuple[str, str, int]] = set()
        self.orphans: list[tuple] = []
        self.valid_in_reset: list[tuple] = []
        self.drops: list[tuple] = []
        self._prev: dict[tuple[str, str], str] = {}
        # x-check state
        self.xcheck: str | None = None
        self.x_edges: dict[str, int] = defaultdict(int)
        self.x_samples: list[tuple] = []
        self.x_full_edges: dict[str, int] = defaultdict(int)
        self.rst_low_first: dict[str, int] = {}
        self.full_until = 0
        self.tail = 0
        self.sampled_edges = 0
        self.paused = False
        self._resume = Event()
        self._task = cocotb.start_soon(self._run())

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False
        self._resume.set()

    def reset_sample(self) -> dict[str, str]:
        return {n: str(h.value) for n, h in self.rst}

    def _orphan(self, link: str, chan: str, ev: tuple, rst: dict[str, str]) -> None:
        """INFO-CLASSIFY for a response whose request the link's checker has not seen."""
        if link not in CHEAP or ev[3] is None:
            return
        kind = "w" if chan in ("aw", "b") else "r"
        key = (link, kind, ev[3])
        if chan in ("aw", "ar"):
            self.outst[key] += 1
            return
        if chan == "r" and ev[5] != "1":
            return
        if self.outst[key] > 0:
            self.outst[key] -= 1
            return
        if key in self.cleared:
            cls = (
                "checker-side (open spec question: whether a request accepted before a reset "
                "completes or is withdrawn)"
                if RESPONDER_RESET[link] != "rst_primary_smc_clk_n_o"
                else "design-side"
            )
        else:
            cls = "bench-side" if link == "smu_out" else "design-side"
        req = self.last.get((link, "aw" if chan == "b" else "ar"))
        self.orphans.append((ev, cls))
        self.log.info(
            f"INFO-CLASSIFY: kind=response-without-request class={cls} "
            f"rule={ORPHAN_RULE[chan]} link={link} id=0x{ev[3]:x} t={ev[0]}ns "
            f"responder_reset={RESPONDER_RESET[link]} checker_reset=rst_primary_smc_clk_n_o "
            f"last_request_handshake={req} reset_nets={rst}"
        )

    def _record(self, link: _Link, chan: str, qs: str, ps: str, t: int, rst=None) -> None:
        ev: tuple
        if link.name not in DETAIL:
            ev = (t, link.name, chan)
        elif chan == "aw":
            ev = (
                t,
                link.name,
                "aw",
                link.field(qs, link.q["aw_id"]),
                link.field(qs, link.q["aw_addr"]),
                link.field(qs, link.q["aw_len"]),
                link.field(qs, link.q["aw_burst"]),
                link.field(qs, link.q["aw_user"]) if link.uw else 0,
                link.field(qs, link.q["aw_atop"]),
            )
        elif chan == "ar":
            ev = (
                t,
                link.name,
                "ar",
                link.field(qs, link.q["ar_id"]),
                link.field(qs, link.q["ar_addr"]),
                link.field(qs, link.q["ar_len"]),
                link.field(qs, link.q["ar_burst"]),
                link.field(qs, link.q["ar_user"]) if link.uw else 0,
            )
        elif chan == "b":
            ev = (
                t,
                link.name,
                "b",
                link.field(ps, link.p["b_id"]),
                link.field(ps, link.p["b_resp"]),
            )
        elif chan == "r":
            ev = (
                t,
                link.name,
                "r",
                link.field(ps, link.p["r_id"]),
                link.field(ps, link.p["r_resp"]),
                link.bit(ps, link.p["r_last"]),
            )
        else:
            ev = (t, link.name, chan)
        if rst is not None and chan in ("aw", "ar", "b", "r"):
            self._orphan(link.name, chan, ev, rst)
        self.last[(link.name, chan)] = ev
        if chan in ("aw", "ar"):
            self.hs_count[link.name] += 1
        self.events.append(ev)

    async def _run(self) -> None:
        cheap = [link for link in self.links if link.name in CHEAP]
        detail = [link for link in self.links if link.name in DETAIL]
        while True:
            if self.paused:
                self._resume.clear()
                await self._resume.wait()
            await RisingEdge(self.clk)
            self.edges += 1
            sampled = {}
            active = False
            for link in cheap:
                qs = str(link.req.value)
                ps = str(link.resp.value)
                hs = link.handshakes(qs, ps)
                sampled[link.name] = (qs, ps, hs)
                if not active and any(hs[sig] != "0" for sig in VALID_SIGNALS):
                    active = True
            if active:
                self.tail = self.edges + ACTIVE_TAIL_EDGES
            forced = self.window is not None or self.edges <= self.full_until
            if not forced and self.edges > self.tail:
                continue
            self.sampled_edges += 1
            t = _now()
            rst = self.reset_sample()
            prim_low = rst["rst_primary_smc_clk_n_o"] == "0"
            if prim_low and self.window and self.window not in self.rst_low_first:
                self.rst_low_first[self.window] = t
            if prim_low:
                if self.window:
                    self.low_edges[self.window] += 1
                for key, n in self.outst.items():
                    if n > 0:
                        self.cleared.add(key)
                self.outst.clear()
            xcheck = self.xcheck if (self.xcheck and not prim_low) else None
            for link in self.links if forced else detail:
                if link.name in sampled:
                    qs, ps, hs = sampled[link.name]
                else:
                    qs = str(link.req.value)
                    ps = str(link.resp.value)
                    hs = link.handshakes(qs, ps)
                if self.window:
                    for sig in VALID_SIGNALS:
                        key = (link.name, sig)
                        prev = self._prev.get(key)
                        if prev == "1" and hs[sig] != "1":
                            self.drops.append((t, link.name, sig, rst))
                        self._prev[key] = hs[sig]
                    if prim_low:
                        self.reset_edges[self.window][link.name] += 1
                        for sig in VALID_SIGNALS:
                            if hs[sig] != "0":
                                self.valid_in_reset.append(
                                    (self.window, t, link.name, sig, hs[sig], rst)
                                )
                if xcheck:
                    bad = [sig for sig, v in hs.items() if v not in "01"]
                    if bad:
                        self.x_samples.append((xcheck, t, link.name, bad))
                for chan, v, r in (
                    ("aw", "aw_valid", "aw_ready"),
                    ("w", "w_valid", "w_ready"),
                    ("ar", "ar_valid", "ar_ready"),
                    ("b", "b_valid", "b_ready"),
                    ("r", "r_valid", "r_ready"),
                ):
                    if hs[v] == "1" and hs[r] == "1":
                        if chan == "w" and link.name not in DETAIL:
                            continue
                        self._record(link, chan, qs, ps, t, rst)
            if xcheck:
                self.x_edges[xcheck] += 1
                if forced:
                    self.x_full_edges[xcheck] += 1

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()

    def between(self, t0: int, t1: int | None = None, link: str | None = None, chan=None):
        out = []
        for ev in self.events:
            if ev[0] < t0 or (t1 is not None and ev[0] > t1):
                continue
            if link is not None and ev[1] != link:
                continue
            if chan is not None and ev[2] not in chan:
                continue
            out.append(ev)
        return out

    def last_state(self, link: str) -> str:
        parts = []
        for chan in ("aw", "ar", "w", "r", "b"):
            ev = self.last.get((link, chan))
            parts.append(f"{chan}={ev if ev is not None else 'none'}")
        return f"link={link} " + " ".join(parts) + f" reset_nets={self.reset_sample()}"


class smu_axi_smc_cool_reset_in_flight_test_seq:
    """Requests in flight on every SMU AXI link across the cool and FLR primary resets."""

    def __init__(self, test) -> None:
        self.test = test
        self.dut = cocotb.top
        self.cfg = test.cfg
        self.sb = test.env.scoreboard
        self.log = test.logger
        self.waits: list[tuple[str, int, str, int, str]] = []
        self.fence: list[tuple[str, int, int, int]] = []
        self.j2a_count = 0
        self.j2a_polls = 0
        self.ref: dict[str, tuple] = {}
        self.ref_ok: dict[str, bool] = {}
        self.done = False

    # ---------------- logging / bounded waits ----------------
    def _info(self, msg: str) -> None:
        self.log.info(msg)

    def _bounded(self, name: str, bound: int, unit: str, used: int, last: str) -> None:
        self.waits.append((name, bound, unit, used, last))

    def _expire(self, name: str, bound: int, unit: str, link: str, what: str) -> None:
        state = self.watch.last_state(link) if hasattr(self, "watch") else "watch not started"
        self._info(
            f"INFO-CLASSIFY: kind=unanswered-transaction class=design-side wait={name} "
            f"bound={bound} {unit} expired; {what}; last={state}"
        )
        raise AssertionError(f"TIMEOUT {name}: {what} not seen within {bound} {unit}; {state}")

    def _bit(self, name: str) -> int:
        val = getattr(self.dut, name).value
        if not val.is_resolvable:
            raise AssertionError(f"X/Z on {name}: {val}")
        return int(val) & 1

    async def _wait_level(self, name: str, level: int, bound: int, clk, unit: str, wait: str):
        for n in range(bound):
            if self._bit(name) == level:
                self._bounded(wait, bound, unit, n, f"{name}={level}")
                return n
            await RisingEdge(clk)
        self._expire(wait, bound, unit, "smu_in", f"{name}=={level}")
        return bound

    async def _wait_count(self, pred, bound: int, wait: str, link: str, what: str) -> int:
        for n in range(bound):
            if pred():
                self._bounded(wait, bound, "clk_smu_i", n, what)
                return n
            await RisingEdge(self.dut.clk_smu_i)
        self._expire(wait, bound, "clk_smu_i", link, what)
        return bound

    def _mark(self, term: str, count: int, planned: int) -> None:
        self.fence.append((term, _now(), count, planned))
        self._info(f"INFO-G2A-STEP: {term} t={_now()}ns count={count} planned={planned}")

    # ---------------- JTAG2AXI ----------------
    def _count_polls(self) -> None:
        """Count every SMC_AXI_SINGLE_OP capture the JTAG2AXI helpers issue."""
        read = self.jtag.read

        async def counted(reg, *args, **kwargs):
            if reg == "SMC_AXI_SINGLE_OP":
                self.j2a_polls += 1
            return await read(reg, *args, **kwargs)

        self.jtag.read = counted

    async def _j2a_wr(self, addr: int, data: int, *, size: int = SMC_DBG_AXSIZE_8B, wstrb=0xFF):
        self.j2a_count += 1
        p0 = self.j2a_polls
        st, _ = await jtag2axi_single_write(
            self.jtag, addr, data, wstrb=wstrb, size=size, poll_limit=J2A_POLL_LIMIT
        )
        require_jtag_tdo_resolved(f"J2A WR @0x{addr:x}")
        if st == J2A_STATUS_BUSY:
            self._expire("j2a_write", J2A_POLL_LIMIT, "polls", "dtp_dbg", f"J2A WR @0x{addr:x}")
        self._bounded("j2a_write", J2A_POLL_LIMIT, "polls", self.j2a_polls - p0, f"status={st}")
        return st

    async def _j2a_rd(self, addr: int, *, size: int = SMC_DBG_AXSIZE_8B):
        self.j2a_count += 1
        p0 = self.j2a_polls
        st, rdata = await jtag2axi_single_read(
            self.jtag, addr, size=size, poll_limit=J2A_POLL_LIMIT
        )
        require_jtag_tdo_resolved(f"J2A RD @0x{addr:x}")
        if st == J2A_STATUS_BUSY:
            self._expire("j2a_read", J2A_POLL_LIMIT, "polls", "dtp_dbg", f"J2A RD @0x{addr:x}")
        self._bounded("j2a_read", J2A_POLL_LIMIT, "polls", self.j2a_polls - p0, f"status={st}")
        return st, int(rdata)

    async def _wr32(self, addr: int, data: int) -> int:
        wstrb, beat = axi64_pack32(addr, data)
        return await self._j2a_wr(addr, beat, size=SMC_DBG_AXSIZE_4B, wstrb=wstrb)

    async def _open_paths(self, tag: str) -> None:
        """Aperture alias, inbound window and outbound filter over JTAG2AXI."""
        before = _now()
        self.watch.pause()
        await program_smc_aperture_local_alias(self.jtag, scoreboard=self.sb)
        await program_inbound0_window(self.jtag, 0, PASS_ALL_END, scoreboard=self.sb, tag=tag)
        await program_outbound0_pass_all(self.jtag, scoreboard=self.sb)
        self.watch.resume()
        self.j2a_count += 8
        self._info(
            f"OBS-G2A-ADDR: tag={tag} smc_aperture=local_alias inbound0=[0x0,0x{PASS_ALL_END:x}] "
            f"outbound0=pass_all smc_cell=0x{SMC_CELL:x} sep_cell=0x{SEP_CELL:x} "
            f"ext_cell=0x{EXT_CELL:x} t={before}..{_now()}ns; waits on an open spec question "
            "(which addresses and filter entries reach the SEP SRAM and SMC scratchpad), "
            "never compared"
        )

    async def _j2a_route(self, label: str, addr: int, data: int) -> dict:
        """One JTAG2AXI write then read; the dtp_dbg handshakes in its window."""
        t0 = _now()
        wst = await self._j2a_wr(addr, data)
        rst, rdata = await self._j2a_rd(addr)
        await ClockCycles(self.dut.clk_smu_i, 2)
        t1 = _now()
        evs = self.watch.between(t0, t1, "dtp_dbg")
        aw = [e for e in evs if e[2] == "aw"]
        ar = [e for e in evs if e[2] == "ar"]
        b = [e for e in evs if e[2] == "b"]
        r = [e for e in evs if e[2] == "r" and e[5] == "1"]
        smc_out = self.watch.between(t0, t1, "xbar_smc_out", ("aw", "ar"))
        targets = {
            port: [e for e in self.watch.between(t0, t1, port, ("aw", "ar")) if e[4] == addr]
            for port in ("xbar_sep_in", "xbar_ext_out", "xbar_smc_in")
        }
        res = {
            "label": label,
            "wst": wst,
            "rst": rst,
            "rdata": rdata,
            "aw": aw,
            "ar": ar,
            "b": b,
            "r": r,
            "smc_out": [e for e in smc_out if e[4] == addr],
            "targets": targets,
            "t0": t0,
            "t1": t1,
        }
        self._info(
            f"INFO-G2A-J2A: route={label} addr=0x{addr:x} wst={wst} rst={rst} "
            f"rdata=0x{rdata:016x} dtp_aw={[(e[3], hex(e[4] or 0), e[8]) for e in aw]} "
            f"dtp_ar={[(e[3], hex(e[4] or 0)) for e in ar]} dtp_b={[(e[3], e[4]) for e in b]} "
            f"dtp_r={[(e[3], e[4]) for e in r]} smc_out={[(e[2], e[7]) for e in res['smc_out']]} "
            f"targets={ {k: len(v) for k, v in targets.items()} }"
        )
        for e in aw:
            self._info(
                f"OBS-G2A-ATOP-DTP: route={label} awid={e[3]} awaddr=0x{(e[4] or 0):x} "
                f"awatop={e[8]} t={e[0]}ns; waits on an open spec question (whether the fabric "
                "carries ATOP and how an atomic request is answered), never compared"
            )
        return res

    @staticmethod
    def _one_resp_ok(res: dict) -> bool:
        """Exactly one AW, one B, one AR and one RLAST on dtp_dbg, IDs paired."""
        aw, b, ar, r = res["aw"], res["b"], res["ar"], res["r"]
        return (
            len(aw) == 1
            and len(b) == 1
            and len(ar) == 1
            and len(r) == 1
            and aw[0][3] == b[0][3]
            and ar[0][3] == r[0][3]
            and None not in (aw[0][3], b[0][3], ar[0][3], r[0][3])
        )

    # ---------------- ext_in ----------------
    async def _ext_route(self, label: str, addr: int, word: bytes, wid: int, rid: int) -> dict:
        t0 = _now()
        w = await self.master.write_bytes_result(
            addr,
            word,
            id=wid,
            check_response=False,
            timeout_ns=AXI_BOUND_NS,
            allow_timeout=True,
        )
        if w.timed_out:
            self._expire(f"ext_in_write_{label}", AXI_BOUND_NS, "ns", "smu_in", "B")
        r = await self.master.read_bytes_result(
            addr,
            len(word),
            id=rid,
            check_response=False,
            timeout_ns=AXI_BOUND_NS,
            allow_timeout=True,
        )
        if r.timed_out:
            self._expire(f"ext_in_read_{label}", AXI_BOUND_NS, "ns", "smu_in", "R")
        self._bounded(f"ext_in_{label}", AXI_BOUND_NS, "ns", _now() - t0, "B and R seen")
        await ClockCycles(self.dut.clk_smu_i, 2)
        t1 = _now()
        evs = self.watch.between(t0, t1, "smu_in")
        res = {
            "label": label,
            "wresp": w.resp,
            "bid": w.observed_id,
            "rresp": r.resp,
            "rid": r.observed_id,
            "data": bytes(r.data_bytes)[: len(word)],
            "word": word,
            "wid": wid,
            "arid": rid,
            "b": [e for e in evs if e[2] == "b"],
            "r": [e for e in evs if e[2] == "r" and e[5] == "1"],
        }
        self._info(
            f"INFO-G2A-EXT: route={label} addr=0x{addr:x} wid=0x{wid:x} bid={w.observed_id} "
            f"wresp={resp_name(w.resp)} rid_issued=0x{rid:x} rid={r.observed_id} "
            f"rresp={resp_name(r.resp)} data={res['data'].hex()} want={word.hex()} "
            f"b_on_pins={len(res['b'])} rlast_on_pins={len(res['r'])}"
        )
        return res

    @staticmethod
    def _ext_one_resp(res: dict) -> bool:
        return (
            len(res["b"]) == 1
            and len(res["r"]) == 1
            and res["bid"] == res["wid"]
            and res["rid"] == res["arid"]
            and res["b"][0][3] == res["wid"]
            and res["r"][0][3] == res["arid"]
        )

    # ---------------- steps ----------------
    async def _setup(self) -> None:
        dut = self.dut
        self.jtag = make_smu_jtag_tap(dut, self.cfg.jtag_period_ns)
        self._count_polls()
        await self.jtag.reset_tap()
        await self.jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await self.jtag.step_tms(0)
        idcode = await self.jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if self._bit("tb_smc_jtag2axi_security_disable"):
            raise AssertionError("SMC JTAG2AXI gated; the leaf cannot open its paths")
        self.links = [_Link(dut, n, q, p) for n, q, p in LINKS]
        for link in self.links:
            self._info(
                f"INFO-G2A-LINK: {link.name} req_bits={link.rq_bits} resp_bits={link.rp_bits} "
                f"id_width={link.idw} user_width={link.uw}"
            )
        self.watch = _Watch(dut, self.links, self.log)
        for net in RESET_NETS:
            await self._wait_level(
                net, 1, RELEASE_BOUND_REF, dut.clk_ref_i, "clk_ref_i", f"setup_{net}"
            )
        rst = self.watch.reset_sample()
        self._info(f"INFO-G2A-RESET-NETS: setup {rst}")
        if any(v != "1" for v in rst.values()):
            raise AssertionError(f"S1 reset nets not all 1 before the leaf: {rst}")
        mem = self.cfg.axi_out_mem
        self.sb.expect_eq("G2A responder depth", mem.max_outstanding, RESPONDER_DEPTH)
        await self._open_paths("INB_SETUP")
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))

        smc = await self._ext_route(
            "ext_in->smc", SMC_CELL, bytes.fromhex("11223344a1b2c3d4"), 0x01, 0x02
        )
        sep = await self._ext_route(
            "ext_in->sep", SEP_CELL, bytes.fromhex("5566778899aabbcc"), 0x03, 0x04
        )
        self.ref["ext_in->smc"] = (smc["wresp"], smc["rresp"])
        self.ref_ok["ext_in->smc"] = (
            smc["wresp"] == RESP_OKAY and smc["rresp"] == RESP_OKAY and smc["data"] == smc["word"]
        )
        self.ref["ext_in->sep"] = (sep["wresp"], sep["rresp"])
        ok = (
            smc["wresp"] == RESP_OKAY
            and smc["rresp"] == RESP_OKAY
            and smc["data"] == smc["word"]
            and self._ext_one_resp(smc)
        )
        self.sb.expect_true(
            "CTRL-G2A-OKAY ext_in->smc write then read OKAY with the word written",
            ok,
            evidence="CTRL-G2A-OKAY",
        )
        self._info(
            f"CTRL-G2A-OKAY: route=ext_in->smc wresp={resp_name(smc['wresp'])} "
            f"rresp={resp_name(smc['rresp'])} data_match={smc['data'] == smc['word']}"
        )
        self._info(
            f"INFO-CELL-NOT-DRIVABLE: EXT_IN_TO_SEP_OKAY reference wresp={resp_name(sep['wresp'])} "
            f"rresp={resp_name(sep['rresp'])} one_response_each={self._ext_one_resp(sep)}"
        )
        self.sb.expect_true(
            "ext_in->sep write and read each answered once with the issued ID",
            self._ext_one_resp(sep),
            evidence="CTRL-G2A-OKAY",
        )
        self._mark("SETUP", 2, 2)

    async def _jtag2axi(self, tag: str, base: int) -> tuple[bool, int, bool]:
        """S2 / S6: SMC window, SEP aperture and neither-aperture routes over JTAG2AXI."""
        win = await self._j2a_route(f"{tag}:j2a->smc", SMC_CELL, 0xC0DE_0000_0000_0001 + base)
        sep = await self._j2a_route(f"{tag}:j2a->sep", SEP_CELL, 0x5E50_0000_0000_0002 + base)
        ext = await self._j2a_route(f"{tag}:j2a->ext", EXT_CELL, 0xE7E7_0000_0000_0003 + base)
        win_ok = (
            win["wst"] == J2A_STATUS_SUCCESS
            and win["rst"] == J2A_STATUS_SUCCESS
            and win["rdata"] == 0xC0DE_0000_0000_0001 + base
            and self._one_resp_ok(win)
        )
        routed = 0
        user_ok = True
        wrong_port = []
        for res, port in ((sep, "xbar_sep_in"), (ext, "xbar_ext_out")):
            got = res["targets"][port]
            if any(e[2] == "aw" for e in got):
                routed += 1
            if any(e[2] == "ar" for e in got):
                routed += 1
            for other in ("xbar_sep_in", "xbar_ext_out", "xbar_smc_in"):
                if other != port and res["targets"][other]:
                    wrong_port.append((res["label"], other))
            ups = [e[7] for e in res["smc_out"]]
            if len(ups) != 2 or any(u is None or (u & 0xF) != 0x3 or (u >> 4) & 0xFF for u in ups):
                user_ok = False
            if not self._one_resp_ok(res):
                user_ok = False
        ext_ok = (
            ext["wst"] == J2A_STATUS_SUCCESS
            and ext["rst"] == J2A_STATUS_SUCCESS
            and ext["rdata"] == 0xE7E7_0000_0000_0003 + base
        )
        self._info(
            f"INFO-CELL-NOT-DRIVABLE: J2A_TO_SEP_OKAY wst={sep['wst']} rst={sep['rst']} "
            f"(status recorded, routing and ID still graded)"
        )
        self.sb.expect_true(
            f"CHK-G2A-JTAG2AXI {tag} window_rw={win_ok} routed={routed}/4 axuser_ok={user_ok} "
            f"ext_rw={ext_ok} wrong_port={wrong_port}",
            win_ok and routed == 4 and user_ok and ext_ok and not wrong_port,
            evidence="CHK-G2A-JTAG2AXI",
        )
        self._info(
            f"CHK-G2A-JTAG2AXI: {tag} window_rw=ok routed={routed}/4 axuser_low=0x3 "
            f"axuser_high=0x00 ext_rw=ok"
        )
        if tag == "S2":
            self.ref["j2a->sep"] = (sep["wst"], sep["rst"])
            self.ref_ok["j2a->smc"] = win_ok
            self.ref_ok["j2a->ext"] = ext_ok
        return win_ok and self._one_resp_ok(win), routed, ext_ok

    async def _load(self, leg: str, j2a_op: int) -> dict:
        """S3: ext_in requests outstanding with READY withheld; one JTAG2AXI access, no hold."""
        self.master.driver.set_timing(
            AxiTimingProfile(b_ready_delay=LOAD_READY_HOLD, r_ready_delay=LOAD_READY_HOLD)
        )
        t0 = _now()
        plan = []
        # single-beat and INCR AxLEN 3 (32 bytes of 8-byte beats inside one 4 KiB page)
        for (kind, ids), addr in (
            (("w_smc", LOAD_IDS["w_smc"]), SMC_LOAD),
            (("w_sep", LOAD_IDS["w_sep"]), SEP_LOAD),
            (("r_smc", LOAD_IDS["r_smc"]), SMC_LOAD),
            (("r_sep", LOAD_IDS["r_sep"]), SEP_LOAD),
        ):
            for n, axid in enumerate(ids):
                length = 8 if n == 0 else 32
                a = addr + 0x40 * n
                if kind.startswith("w"):
                    payload = bytes((axid + i) & 0xFF for i in range(length))
                    self.master.init_write(a, payload, id=axid, size=3)
                else:
                    self.master.init_read(a, length, id=axid, size=3)
                plan.append((kind, axid, a, length))
        n_w = sum(1 for p in plan if p[0].startswith("w"))
        n_r = len(plan) - n_w
        n_beats = sum(p[3] // 8 for p in plan if p[0].startswith("w"))
        await self._wait_count(
            lambda: (
                len(self.watch.between(t0, None, "smu_in", ("aw",))) >= n_w
                and len(self.watch.between(t0, None, "smu_in", ("ar",))) >= n_r
                and len(self.watch.between(t0, None, "smu_in", ("w",))) >= n_beats
            ),
            HANDSHAKE_BOUND_SMU,
            f"{leg}_load_ext_in_accept",
            "smu_in",
            f"{n_w} AW, {n_beats} W and {n_r} AR handshakes",
        )
        # JTAG2AXI toward ext_out; the responder answers at its default delay.
        t_j = _now()
        if j2a_op == J2A_OP_WRITE:
            raw = pack_single_op(J2A_OP_WRITE, EXT_LOAD, 0xD7D7_0000_0000_00AA, wstrb=0xFF)
        else:
            raw = pack_single_op(J2A_OP_READ, EXT_LOAD, 0, wstrb=0)
        await self.jtag.write("SMC_AXI_SINGLE_OP", raw)
        require_jtag_tdo_resolved(f"{leg} J2A load issue")
        self.j2a_count += 1
        chan = ("aw",) if j2a_op == J2A_OP_WRITE else ("ar",)
        await self._wait_count(
            lambda: (
                len(self.watch.between(t_j, None, "xbar_ext_out", chan)) >= 1
                and len(self.watch.between(t_j, None, "dtp_dbg", chan)) >= 1
            ),
            HANDSHAKE_BOUND_SMU,
            f"{leg}_load_j2a_accept",
            "dtp_dbg",
            f"J2A {chan[0].upper()} at dtp_dbg and ext_out",
        )
        t_issue = _now()
        out = self._outstanding(t0, t_issue)
        for (port, axid), (kind, n_req, n_resp) in sorted(out.items(), key=lambda kv: str(kv[0])):
            self._info(
                f"INFO-G2A-OUTSTANDING: leg={leg} port={port} id=0x{axid:x} kind={kind} "
                f"accepted={n_req} answered={n_resp} outstanding={n_req - n_resp} t={t_issue}ns"
            )
        per_port = defaultdict(int)
        for (port, _), (_, n_req, n_resp) in out.items():
            per_port[port] += n_req - n_resp
        planned = {"smu_in": len(plan)}
        short = {p: (per_port[p], n) for p, n in planned.items() if per_port[p] < n}
        if short:
            self._info(
                f"INFO-CLASSIFY: kind=load-below-plan class=bench-side leg={leg} short={short} "
                f"last={self.watch.last_state('smu_in')}"
            )
            raise AssertionError(f"{leg} LOAD below its planned outstanding count: {short}")
        return {"t0": t0, "t_issue": t_issue, "plan": plan, "out": out, "per_port": dict(per_port)}

    def _outstanding(self, t0: int, t1: int) -> dict:
        """Accepted minus answered per (port, ID) on smu_in and dtp_dbg in [t0, t1]."""
        out: dict[tuple[str, int], list] = {}
        for port in ("smu_in", "dtp_dbg"):
            for ev in self.watch.between(t0, t1, port, ("aw", "ar", "b", "r")):
                chan, axid = ev[2], ev[3]
                kind = "write" if chan in ("aw", "b") else "read"
                key = (port, axid)
                entry = out.setdefault(key, [kind, 0, 0])
                if chan in ("aw", "ar"):
                    entry[1] += 1
                elif chan == "b" or ev[5] == "1":
                    entry[2] += 1
        return {k: tuple(v) for k, v in out.items()}

    async def _reset(self, leg: str) -> dict:
        """S4 / S7: assert the primary reset from the cool pin or the FLR request."""
        dut = self.dut
        self.watch.window = leg
        t_assert = _now()
        if leg != "flr":
            dut.tb_cool_reset_pin.value = 1
            held = 0
            asserted = None
            while True:
                await RisingEdge(dut.clk_ref_i)
                held += 1
                if asserted is None and self._bit("rst_primary_smc_clk_n_o") == 0:
                    asserted = held
                if asserted is not None and held >= asserted + HOLD_PAST_ASSERT_REF:
                    break
                if asserted is None and held >= ASSERT_BOUND_REF:
                    self._expire(
                        "cool_assert", ASSERT_BOUND_REF, "clk_ref_i", "smu_in", "primary reset low"
                    )
            self._bounded("cool_assert", ASSERT_BOUND_REF, "clk_ref_i", asserted, "primary=0")
            if held <= DEGLITCH_SAMPLES:
                raise AssertionError(f"cool pin held {held} clk_ref, not above {DEGLITCH_SAMPLES}")
            dut.tb_cool_reset_pin.value = 0
            self._info(f"INFO-G2A-COOL: pin held {held} clk_ref, primary low after {asserted}")
        else:
            dut.tb_cfg_flr_pf_active.value = 1
            await self._wait_level(
                "rst_primary_smc_clk_n_o",
                0,
                FLR_ASSERT_BOUND_REF,
                dut.clk_ref_i,
                "clk_ref_i",
                "flr_assert",
            )
            dut.tb_cfg_flr_pf_active.value = 0
            held = None
        t_release_req = _now()
        for net in ("rst_primary_smc_clk_n_o", "obs_smc_rst_n_o", "obs_xbar_rst_n_o"):
            await self._wait_level(
                net, 1, RELEASE_BOUND_REF, dut.clk_ref_i, "clk_ref_i", f"{leg}_release_{net}"
            )
        t_release = _now()
        # Edges sampled after release by the VALID-drop tracker, then the window closes.
        await ClockCycles(dut.clk_smu_i, 4)
        self.watch.window = None
        self.watch.xcheck = leg
        self.watch.full_until = self.watch.edges + POST_RELEASE_FULL_EDGES
        edges = dict(self.watch.reset_edges[leg])
        low_first = self.watch.rst_low_first.get(leg)
        self._info(
            f"INFO-G2A-RESET: leg={leg} t_assert={t_assert}ns primary_low_first={low_first}ns "
            f"t_release_req={t_release_req}ns t_release={t_release}ns edges={edges}"
        )
        return {
            "t_assert": t_assert,
            "t_low": low_first,
            "t_release": t_release,
            "edges": edges,
            "held_ref": held,
        }

    async def _dtp_after_release(self, leg: str, rst: dict) -> tuple[int, int]:
        """S5: the JTAG2AXI state after release."""
        dut = self.dut
        t_rel = rst["t_release"]
        polls = 0
        status = J2A_STATUS_BUSY
        for polls in range(1, J2A_HELD_POLLS + 1):
            capt = await self.jtag.read("SMC_AXI_SINGLE_OP", shift_value=0)
            require_jtag_tdo_resolved(f"{leg} J2A status after release")
            status, _ = unpack_single_op(capt)
            if status != J2A_STATUS_BUSY:
                break
            await ClockCycles(dut.clk_smu_i, 512)
        self._bounded(
            f"{leg}_j2a_status_after_release", J2A_HELD_POLLS, "polls", polls, f"st={status}"
        )

        dtp = self.watch.between(t_rel, None, "dtp_dbg", ("b", "r"))
        self._info(
            f"OBS-G2A-DTP-RESET: leg={leg} j2a_status_after_release={status} polls={polls} "
            f"dtp_dbg_reset_edges={rst['edges'].get('dtp_dbg', 0)} "
            f"dtp_responses_after_release={len(dtp)}; waits on an open spec question (which reset "
            "drives dbg_rstb_i and the JTAG2AXI AXI side), never compared"
        )
        return status, polls

    def _stale(self, leg: str, load: dict, rst: dict, t_end: int) -> tuple[int, int, int]:
        """No pre-reset or never-issued response on smu_in or dtp_dbg after release."""
        t_rel = rst["t_release"]
        pre_ids = {(k[0], k[1]) for k, v in load["out"].items() if v[1] > v[2]}
        stale = 0
        phantom = 0
        detail = []
        for port in ("smu_in", "dtp_dbg"):
            req = defaultdict(int)
            resp = defaultdict(int)
            for ev in self.watch.between(t_rel, t_end, port, ("aw", "ar", "b", "r")):
                chan, axid = ev[2], ev[3]
                kind = "w" if chan in ("aw", "b") else "r"
                if chan in ("aw", "ar"):
                    req[(kind, axid)] += 1
                    continue
                if chan == "r" and ev[5] != "1":
                    continue
                resp[(kind, axid)] += 1
                if port == "smu_in" and (port, axid) in pre_ids and req[(kind, axid)] == 0:
                    stale += 1
                    detail.append(("stale", port, ev))
                elif resp[(kind, axid)] > req[(kind, axid)]:
                    phantom += 1
                    detail.append(("phantom", port, ev))
        for item in detail:
            self._info(
                f"INFO-CLASSIFY: kind={item[0]}-response class=design-side leg={leg} port={item[1]} "
                f"event={item[2]} last={self.watch.last_state(item[1])}"
            )
        return len(pre_ids), stale, phantom

    def _outcome(self, leg: str, load: dict, rst: dict, t_end: int) -> None:
        """OBS-G2A-OUTCOME / OBS-G2A-FLR-OUTCOME per port and ID."""
        t_low = rst["t_low"] or rst["t_assert"]
        tag = "OBS-G2A-OUTCOME" if leg == "cool" else "OBS-G2A-FLR-OUTCOME"
        for (port, axid), (kind, n_req, n_resp) in sorted(load["out"].items(), key=str):
            if n_req <= n_resp:
                outcome = "completed_before_reset"
            else:
                after = [
                    e
                    for e in self.watch.between(rst["t_release"], t_end, port, ("b", "r"))
                    if e[3] == axid and (e[2] == "b" or e[5] == "1")
                ]
                before = [
                    e
                    for e in self.watch.between(load["t_issue"], t_low, port, ("b", "r"))
                    if e[3] == axid and (e[2] == "b" or e[5] == "1")
                ]
                during = [
                    e
                    for e in self.watch.between(t_low, rst["t_release"], port, ("b", "r"))
                    if e[3] == axid
                ]
                if before:
                    outcome = "completed_before_reset"
                elif after:
                    outcome = "answered_after_release"
                elif during:
                    outcome = "answered_during_reset_window"
                else:
                    outcome = "withdrawn"
                    self._info(
                        f"INFO-CLASSIFY: kind=unanswered-transaction class=checker-side "
                        f"graded=no leg={leg} port={port} id=0x{axid:x} reason=withdrawn by the "
                        "primary reset (open spec question: whether a request accepted before a "
                        f"reset completes or is withdrawn) last={self.watch.last_state(port)}"
                    )
            self._info(
                f"{tag}: leg={leg} port={port} id=0x{axid:x} kind={kind} accepted={n_req} "
                f"answered_before={n_resp} outcome={outcome} reset_low_at={t_low}ns; "
                f"aresetn=rst_primary_smc_clk_n_o; waits on an open spec question (whether a "
                "request accepted before a reset completes or is withdrawn), never compared"
            )

    async def _liveness(self, leg: str) -> dict:
        """S6: fresh write and read on every route that answered OKAY before the reset."""
        ids = FRESH_IDS[leg]
        smc = await self._ext_route(
            f"{leg}:ext_in->smc",
            SMC_CELL + 8,
            bytes((ids[0] + i) & 0xFF for i in range(8)),
            ids[0],
            ids[1],
        )
        sep = await self._ext_route(
            f"{leg}:ext_in->sep",
            SEP_CELL + 8,
            bytes((ids[2] + i) & 0xFF for i in range(8)),
            ids[2],
            ids[3],
        )
        win_ok, routed, ext_ok = await self._jtag2axi(leg, 0x100 if leg == "cool" else 0x200)
        smc_ok = (
            smc["wresp"] == RESP_OKAY
            and smc["rresp"] == RESP_OKAY
            and smc["data"] == smc["word"]
            and self._ext_one_resp(smc)
        )
        sep_same = (sep["wresp"], sep["rresp"]) == self.ref["ext_in->sep"]
        self._info(
            f"OBS-G2A-SEP-ROUTE-LIVENESS: leg={leg} wresp={resp_name(sep['wresp'])} "
            f"rresp={resp_name(sep['rresp'])} same_as_s1={sep_same} "
            f"one_response_each={self._ext_one_resp(sep)}; the SEP aperture at its RDL reset "
            f"window reaches no SEP resource, never compared"
        )
        fresh = {"ext_in->smc": smc_ok, "j2a->smc": win_ok, "j2a->ext": ext_ok}
        graded = [r for r in fresh if self.ref_ok.get(r)]
        ok = [r for r in graded if fresh[r]]
        self._info(
            f"INFO-G2A-LIVENESS: leg={leg} graded={graded} ok={ok} "
            f"not_graded={[r for r in fresh if r not in graded]}"
        )
        return {"graded": len(graded), "ok": len(ok), "win_ok": win_ok, "routed": routed}

    async def _leg(self, leg: str, j2a_op: int) -> dict:
        load = await self._load(leg, j2a_op)
        self._mark(
            "LOAD" if leg == "cool" else "FLR_LOAD",
            sum(load["per_port"].values()),
            len(load["plan"]),
        )
        rst = await self._reset(leg)
        valid_hi = [v for v in self.watch.valid_in_reset if v[0] == leg]
        edges = rst["edges"]
        for v in valid_hi:
            self._info(
                f"INFO-CLASSIFY: kind=valid-high-in-reset class=design-side leg={leg} link={v[2]} "
                f"sig={v[3]} value={v[4]} t={v[1]}ns reset_nets={v[5]} last={self.watch.last_state(v[2])}"
            )
        for t, link, sig, nets in [
            d for d in self.watch.drops if rst["t_assert"] <= d[0] <= rst["t_release"]
        ]:
            self._info(
                f"OBS-G2A-RESET-DOMAIN: leg={leg} link={link} {sig} dropped t={t}ns nets={nets} "
                f"graded_against=rst_primary_smc_clk_n_o; waits on open spec questions (which "
                "reset resets the crossbar, converters and inbound cut; which reset grades the "
                "SMC-facing links; where the inbound boundary cut sits and whether it is "
                "transparent), never compared"
            )
        self._info(
            f"OBS-G2A-RESET-DOMAIN: leg={leg} incut=u_dut.u_smu.smu_axi_in_cut "
            f"incut_reset_edges={edges.get('incut', 0)} smu_in_reset_edges={edges.get('smu_in', 0)}; "
            f"waits on open spec questions (which reset resets the crossbar, converters and "
            "inbound cut; which reset grades the SMC-facing links; where the inbound boundary cut "
            "sits and whether it is transparent), never compared"
        )
        self._mark(
            "COOL_RESET" if leg == "cool" else "FLR_RESET",
            min(edges.values() or [0]),
            self.watch.low_edges.get(leg, 0),
        )
        status, polls = await self._dtp_after_release(leg, rst)
        if status == J2A_STATUS_BUSY:
            self._expire(
                f"{leg}_j2a_after_release",
                J2A_HELD_POLLS,
                "polls",
                "dtp_dbg",
                "JTAG2AXI leaving BUSY after the primary reset released",
            )
        if leg == "flr":
            st = await self._wr32(ISOLATE_REQ_SMC_REG, ISOLATE_REQ_SMC_BM)
            self._info(f"CTRL-G2A-FLR-RECOVER: ISOLATE_REQ_SMC cleared status={st}")
        watch_edges = self.watch.x_full_edges.get(leg, 0)
        since = self.watch.edges - (self.watch.full_until - POST_RELEASE_FULL_EDGES)
        s5_hs = self.watch.between(rst["t_release"], None, None, ("aw", "ar", "b", "r"))
        self._info(
            f"INFO-G2A-RELEASE-WATCH: leg={leg} edges_since_release={since} "
            f"all_link_edges={watch_edges} handshakes_watched={len(s5_hs)}"
        )
        self._mark(
            "RELEASE_WATCH" if leg == "cool" else "FLR_RELEASE_WATCH",
            watch_edges,
            min(since, POST_RELEASE_FULL_EDGES),
        )
        await self._wait_level(
            "sep_reset_n",
            1,
            SEP_RESET_BOUND_REF,
            self.dut.clk_ref_i,
            "clk_ref_i",
            f"{leg}_sep_reset_n",
        )
        await self._open_paths(f"INB_{leg.upper()}")
        self.master.driver.set_timing(AxiTimingProfile())
        live = await self._liveness(leg)
        t_end = _now()
        self._mark("LIVENESS" if leg == "cool" else "FLR_LIVENESS", live["ok"], live["graded"])
        pre, stale, phantom = self._stale(leg, load, rst, t_end)
        self._outcome(leg, load, rst, t_end)
        return {
            "rst": rst,
            "valid_hi": valid_hi,
            "edges": edges,
            "graded": live["graded"],
            "ok": live["ok"],
            "win_ok": live["win_ok"],
            "pre": pre,
            "stale": stale,
            "phantom": phantom,
            "watch_edges": watch_edges,
        }

    async def run(self) -> None:
        dut = self.dut
        sb = self.sb
        await self.cfg.reset_done.wait()
        dut.tb_cool_reset_pin.value = 0
        dut.tb_cfg_flr_pf_active.value = 0
        await ClockCycles(dut.clk_smu_i, 16)
        self._info("STEP S1: SETUP")
        await self._setup()
        for cell, why in NOT_DRIVABLE:
            self._info(f"INFO-CELL-NOT-DRIVABLE: {cell}: {why}")
        self._info("STEP S2: JTAG2AXI")
        j0 = self.j2a_count
        await self._jtag2axi("S2", 0)
        self._info(f"INFO-G2A-REFERENCE: routes answering OKAY before the reset {self.ref_ok}")
        self._mark("JTAG2AXI", self.j2a_count - j0, 6)

        self._info("STEP S3-S6: cool-reset leg, no response held")
        cool = await self._leg("cool", J2A_OP_WRITE)
        self._info("STEP S7: FLR leg")
        st0 = await self._wr32(FLR_COUNTER, 0)
        st1 = await self._wr32(FLR_RESET_COUNTER, FLR_RESET_HOLD & RESET_COUNTER_BM)
        self._info(
            f"CTRL-G2A-FLR-ARM: FLR_COUNTER=0 st={st0} FLR_RESET_COUNTER={FLR_RESET_HOLD} st={st1}"
        )
        if (st0, st1) != (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS):
            raise AssertionError(f"FLR counters not programmed: status {st0},{st1}")
        flr = await self._leg("flr", J2A_OP_READ)
        self._mark("FLR_LEG", flr["ok"], flr["graded"])
        self._info("STEP S8: TIMEOUT and graded checkers")

        # --- graded checkers ---
        links = len(self.links)
        valid_hi = cool["valid_hi"]
        cool_edges = cool["edges"]
        no_edge = [link.name for link in self.links if cool_edges.get(link.name, 0) == 0]
        sb.expect_true(
            f"CHK-G2A-VALID-LOW cool links={links} valid_high_in_reset={len(valid_hi)} "
            f"links_without_edges={no_edge}",
            not valid_hi and not no_edge and len(cool_edges) == links,
            evidence="CHK-G2A-VALID-LOW",
        )
        self._info(
            f"CHK-G2A-VALID-LOW: links={links} edges_sampled={min(cool_edges.values())}.."
            f"{max(cool_edges.values())} valid_high_in_reset={len(valid_hi)}"
        )
        x_all = self.watch.x_samples
        x_edges = sum(self.watch.x_edges.values())
        x_full = sum(self.watch.x_full_edges.values())
        for x in x_all[:16]:
            self._info(f"INFO-CLASSIFY: kind=x-sample class=design-side sample={x}")
        sb.expect_true(
            f"CHK-G2A-XKNOWN links={links} edges={x_edges} all_link_edges={x_full} "
            f"x_samples={len(x_all)}",
            not x_all and x_full > 0,
            evidence="CHK-G2A-XKNOWN",
        )
        self._info(
            f"CHK-G2A-XKNOWN: links={links} edges={x_edges} all_link_edges={x_full} "
            f"x_samples={len(x_all)}"
        )
        sb.expect_true(
            f"CHK-G2A-NO-STALE-RESP pre_reset_reqs={cool['pre']} stale={cool['stale']} "
            f"phantom={cool['phantom']} watch_edges={cool['watch_edges']}",
            cool["pre"] > 0
            and cool["stale"] == 0
            and cool["phantom"] == 0
            and cool["watch_edges"] > 0,
            evidence="CHK-G2A-NO-STALE-RESP",
        )
        self._info(
            f"CHK-G2A-NO-STALE-RESP: pre_reset_reqs={cool['pre']} "
            f"stale_after_release={cool['stale']} phantom={cool['phantom']}"
        )
        sb.expect_true(
            f"CHK-G2A-LIVENESS routes_graded={cool['graded']} okay_and_data={cool['ok']}",
            cool["graded"] > 0 and cool["ok"] == cool["graded"],
            evidence="CHK-G2A-LIVENESS",
        )
        self._info(
            f"CHK-G2A-LIVENESS: routes_graded={cool['graded']} (ext_in->smc, j2a->smc, j2a->ext "
            f"where OKAY in S1/S2) okay_and_data={cool['ok']}/{cool['graded']}"
        )
        flr_edges = flr["edges"]
        flr_ok = (
            flr["rst"]["t_low"] is not None
            and not flr["valid_hi"]
            and len(flr_edges) == links
            and min(flr_edges.values()) > 0
            and flr["stale"] == 0
            and flr["phantom"] == 0
            and flr["graded"] > 0
            and flr["ok"] == flr["graded"]
        )
        sb.expect_true(
            f"CHK-G2A-FLR reset_edges={min(flr_edges.values() or [0])} valid_high={len(flr['valid_hi'])} "
            f"stale={flr['stale']} phantom={flr['phantom']} fresh={flr['ok']}/{flr['graded']}",
            flr_ok,
            evidence="CHK-G2A-FLR",
        )
        self._info(
            f"CHK-G2A-FLR: reset_edges={min(flr_edges.values())} "
            f"valid_high_in_reset={len(flr['valid_hi'])} stale={flr['stale']} "
            f"fresh_ok={flr['ok']}/{flr['graded']}"
        )
        dtp_hi = [v for v in valid_hi + flr["valid_hi"] if v[2] == "dtp_dbg"]
        dtp_ok = (
            not dtp_hi
            and cool_edges.get("dtp_dbg", 0) > 0
            and flr_edges.get("dtp_dbg", 0) > 0
            and cool["win_ok"]
            and flr["win_ok"]
        )
        sb.expect_true(
            f"CHK-G2A-DTP-LINK reset_edges={cool_edges.get('dtp_dbg', 0)}+{flr_edges.get('dtp_dbg', 0)} "
            f"valid_high={len(dtp_hi)} fresh_cool={cool['win_ok']} fresh_flr={flr['win_ok']}",
            dtp_ok,
            evidence="CHK-G2A-DTP-LINK",
        )
        self._info(
            f"CHK-G2A-DTP-LINK: reset_edges={cool_edges.get('dtp_dbg', 0)}+{flr_edges.get('dtp_dbg', 0)} "
            f"valid_high_in_reset={len(dtp_hi)} fresh_cool={cool['win_ok']} fresh_flr={flr['win_ok']}"
        )
        # ordered fence
        order = [f[0] for f in self.fence]
        want = [
            "SETUP",
            "JTAG2AXI",
            "LOAD",
            "COOL_RESET",
            "RELEASE_WATCH",
            "LIVENESS",
            "FLR_LOAD",
            "FLR_RESET",
            "FLR_RELEASE_WATCH",
            "FLR_LIVENESS",
            "FLR_LEG",
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
        expired = [w for w in self.waits if w[3] >= w[1]]
        sb.expect_true(
            f"CHK-TIMEOUT-PATHS waits={len(self.waits)} expired={len(expired)}",
            not expired and len(self.waits) > 0,
            evidence="CHK-TIMEOUT-PATHS",
        )
        kinds = defaultdict(int)
        for w in self.waits:
            kinds[(w[0].split("_", 1)[-1], w[1], w[2])] += 1
        for (name, bound, unit), n in sorted(kinds.items(), key=str):
            self._info(f"INFO-G2A-WAIT: {name} bound={bound} {unit} count={n} on_expiry=raise")
        self._info(
            f"CHK-TIMEOUT-PATHS: {len(self.waits)} bounded waits, bound and last state per wait, "
            f"0 expired; j2a_accesses={self.j2a_count} j2a_polls={self.j2a_polls}"
        )
        self._info(
            f"INFO-G2A-ORPHANS: responses without a request on smu_in, dtp_dbg, smu_out in S1-S8: "
            f"{len(self.watch.orphans)}"
        )
        self._info("STEP S9: HELD_RESP")
        await self._held_resp()
        self.done = True

    async def _held_resp(self) -> None:
        """S9: one B held across a cool reset and dropped at the link's reset; observation only."""
        dut = self.dut
        mem = self.cfg.axi_out_mem
        window = mem.driver.write_if.window
        word = 0xD7D7_0000_0000_00BB
        mem.set_response_delay(iter([RESP_HOLD_CYCLES]), read=False, write=True)
        t_j = _now()
        raw = pack_single_op(J2A_OP_WRITE, EXT_LOAD, word, wstrb=0xFF)
        await self.jtag.write("SMC_AXI_SINGLE_OP", raw)
        require_jtag_tdo_resolved("S9 J2A held write issue")
        self.j2a_count += 1
        # The responder stores the beat before it queues the B, so the word in
        # its memory means the B is in its hold.
        await self._wait_count(
            lambda: (
                len(self.watch.between(t_j, None, "dtp_dbg", ("aw",))) >= 1
                and len(self.watch.between(t_j, None, "smu_out", ("aw",))) >= 1
                and mem.read_int(EXT_LOAD, 8) == word
            ),
            HANDSHAKE_BOUND_SMU,
            "held_write_landed",
            "smu_out",
            "J2A AW at dtp_dbg and smu_out and the written word in the responder memory",
        )
        await ClockCycles(dut.clk_smu_i, 2)
        held = window.outstanding()
        aw = self.watch.between(t_j, None, "smu_out", ("aw",))
        self._info(
            f"CTRL-G2A-HELD-ISSUE: addr=0x{EXT_LOAD:x} "
            f"smu_out_aw={[(e[3], hex(e[4] or 0)) for e in aw]} responder_writes_held={held} "
            f"t={_now()}ns"
        )
        if held != 1:
            self._info(
                f"INFO-CLASSIFY: kind=hold-not-armed class=bench-side responder_writes_held={held} "
                f"last={self.watch.last_state('smu_out')}"
            )
            raise AssertionError(f"S9 responder holds {held} writes, not the one armed")
        # The responder resets on rst_cold_n_o; the link's aresetn is the
        # primary reset, which withdraws the request, so the bench drops the B
        # there as a subordinate on that reset must.
        dropped: list[tuple[int, int]] = []

        async def drop_at_link_reset() -> None:
            await FallingEdge(dut.rst_primary_smc_clk_n_o)
            dropped.append((_now(), window.outstanding()))
            window.reset()

        dropper = cocotb.start_soon(drop_at_link_reset())
        rst = await self._reset("held")
        mem.clear_response_delay()
        if not dropped:
            dropper.cancel()
            raise AssertionError("S9 primary reset released without a falling edge seen")
        status, polls = await self._dtp_after_release("held", rst)
        await ClockCycles(dut.clk_smu_i, RESP_HOLD_CYCLES)
        t_rel = rst["t_release"]
        b_after = {
            name: len(self.watch.between(t_rel, None, name, ("b",)))
            for name in ("smu_out", "xbar_ext_out", "xbar_smc_out", "dtp_dbg")
        }
        self._info(
            f"OBS-G2A-HELD-RESP: responder_writes_held_at_reset={dropped[0][1]} "
            f"dropped_at={dropped[0][0]}ns release_at={t_rel}ns watched_after_release="
            f"{_now() - t_rel}ns b_after_release={b_after} j2a_status_after_release={status} "
            f"polls={polls} reset_nets={self.watch.reset_sample()}; the bench drops its held B "
            f"at the link's reset, a B presented after release is HELD_B_AFTER_RELEASE "
            f"(not driven); waits on an open spec question (whether a request accepted before a "
            "reset completes or is withdrawn), never compared"
        )
        self.watch.stop()
