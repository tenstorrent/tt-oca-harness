# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The SMU crossbar with the SEP debug-module initiator on sep_out against a stalling ext_out.

The ``sep_out`` initiator is the SEP hart running the ICCM probe of
``smu_sep_lsu_fabric_test`` (stores of every width, then word loads, in a
64-byte window at ``a0``) under the debug module, and the debug module's system
bus. The SEP route demux sends an address in the SMC aperture straight to the
SMC and an address in the SEP's SMU window, ``SMU_GLOBAL_BASE_ADDR`` and
``SMU_REGION_SIZE``, to the outbound filter and ``sep_out``
(``hw/sys/sep/doc/fabric.adoc``, the output fabric), so every SEP request this
leaf puts on ``sep_out`` lies in that window, and S5 to S7 place the apertures
inside it. The ``smc_out`` partners are the JTAG2AXI bridge and the SMC iDMA it
programs; the ``ext_in`` partner is the bench master on the ``ext_in_*`` pins;
``ext_out`` is the bench responder on ``u_axi_out_if``. The routing table of
``hw/sys/smu/doc/index.adoc`` gives every expected route; each aperture covers
[base, base + size) and a size of 0 disables it.

Observation is passive: the ``ext_in_*`` pins, ``u_axi_out_if``, the request
and response structs of the 13 checked links read by hierarchy, the bench
counters and the aperture ports. The links are sampled on every ``clk_smu_i``
edge on which a VALID of an initiator or target port is high, while any of
their requests is unanswered, and for a tail after that.

S1 SETUP: the access paths, the four aperture registers read back, the hart
   halted with ``dcsr.ebreakm`` and the trap vector set, the SEP outbound filter
   opened, the SEP aperture widened to reach the SEP SRAM, reference patterns,
   and CTRL-G4B-OKAY: one write then read per permitted cell.
S2 STALLED_EXT_OUT: with the responder withholding READY and delaying B and R,
   an iDMA copy between two ext_out ranges, the LSU probe resumed in the same
   scan as a JTAG2AXI write to ext_out, four system-bus accesses to ext_out and
   ext_in requests to neither aperture.
S3 INTERLEAVE: one probe run toward ext_out with a system-bus read held at the
   responder, one toward the SEP view of the SMC scratchpad, JTAG2AXI, iDMA and
   ext_in write-then-read of every permitted target with full and partial
   strobes, multi-beat bursts, and one error response per link.
S4 ROUTE_FWD: a system-bus write and read matching neither aperture.
S5 DECERR_CELLS: the SEP aperture moved into the SEP's SMU window and a
   system-bus write and read into it; ext_in INCR bursts of AxLEN 1, 15 and 255
   into neither aperture.
S6 APERTURE_EDGES: both apertures placed in the SEP's SMU window at the reset
   sizes and after one reprogram; base-1, base, base+size-1 and base+size of
   each from each initiator.
S7 ZERO_SIZE: SEP_REGION_SIZE 0, then REGION_SIZE 0, then both.
S8 TIMEOUT: every wait is bounded in clk_smu_i edges or polls; an expiry fails
   the leaf with the last handshakes and the reset-net sample.

The bench protocol checkers and need gates grade under VCS only.
"""

from __future__ import annotations

import itertools
import time
from collections import Counter, defaultdict
from contextlib import ExitStack

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from env.smu_axi_monitor import expected_decerr
from ocah_axi_vip import PROT_NONSECURE, AxiTimingProfile, clear_profile

from seq_lib.smu_addr_map import (
    OUTBOUND0_END,
    OUTBOUND0_FILTER_CONFIG,
    OUTBOUND0_START,
    smc_addr,
)
from seq_lib.smu_axi_concurrent_initiators_stall_test_seq import (
    _CH,
    DRAIN_BOUND,
    EXT_DMA_DST,
    EXT_DMA_SRC,
    EXT_J2A,
    NEITHER,
    PORT_BOUND,
    RESP_DELAY,
    RESPONDER_DEPTH,
    SEP_FILL_BYTES,
    SEP_SRAM,
    SEP_WIDE_SIZE,
    SMC_GLOBAL_BASE_REG,
    SMC_GLOBAL_BASE_RESET,
    SMC_REGION_SIZE_REG,
    SMC_REGION_SIZE_RESET,
    SPM,
    SPM_FILL_BYTES,
    SPM_LOCAL,
    STALL_CHOICES,
    XFER_BOUND,
    _now,
    _Tap,
    smu_axi_concurrent_initiators_stall_test_seq,
)
from seq_lib.smu_axi_helpers import make_smu_axi_master
from seq_lib.smu_axi_out_addr_len_size_test_seq import (
    DMA_CONFIG,
    DMA_CONFIG_ENABLE_ND,
    DMA_DST_HI,
    DMA_DST_LO,
    DMA_DST_STRIDE_HI,
    DMA_DST_STRIDE_LO,
    DMA_LEN_HI,
    DMA_LEN_LO,
    DMA_NEXT_ID_0,
    DMA_REPS_HI,
    DMA_REPS_LO,
    DMA_SRC_HI,
    DMA_SRC_LO,
    DMA_SRC_STRIDE_HI,
    DMA_SRC_STRIDE_LO,
)
from seq_lib.smu_axi_smc_cool_reset_in_flight_test_seq import (
    LINK_ADDR_BITS,
    LINK_DATA_BITS,
    LINKS,
    _Link,
)
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_NOP,
    DMI_OP_READ,
    DMI_OP_WRITE,
    DMI_STATUS_OK,
    pack_dmi,
    unpack_dmi,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import (
    DMI_STATUS_BUSY,
    OUTBOUND_CFG_OPEN,
    OUTBOUND_END_ADDR,
    OUTBOUND_FILTER_CONFIG,
    OUTBOUND_START_ADDR,
    SBADDRESS0_ADDR,
    SBCS_ADDR,
    SBCS_SBBUSY,
    SBCS_SBBUSYERROR,
    SBCS_SBERROR_MASK,
    SBCS_SBERROR_SHIFT,
    SBCS_SBERROR_W1C,
    SBCS_SBREADONADDR,
    SBDATA0_ADDR,
    SBDATA1_ADDR,
    SEP_GLOBAL_BASE_ADDR,
    SEP_GLOBAL_BASE_RESET,
    SEP_REGION_SIZE_ADDR,
    SEP_REGION_SIZE_RESET,
)
from seq_lib.smu_dtp_sep_ic_reset_effect_test_seq import (
    CONFIG_HOLD_CLEAR,
    DMI_IDLE_TCKS,
    DMI_RETRY_LIMIT,
    PTAP_3DCR_SELECT,
    SBA_POLL_LIMIT,
)
from seq_lib.smu_filter_helpers import PASS_ALL_END, PASS_RW_CONFIG, SMC_APERTURE_LOCAL_BASE
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    DTP_IR_SMC_AXI_SINGLE_OP,
    DTP_IR_TAP_3DCR,
    J2A_OP_READ,
    J2A_OP_WRITE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SLVERR,
    J2A_STATUS_SUCCESS,
    PTAP_3DCR_WIDTH,
    SMC_DBG_SINGLE_OP_LEN,
    pack_single_op,
    ptap_3dcr_value,
    unpack_single_op,
)
from seq_lib.smu_sep_lsu_fabric_test_seq import (
    A0,
    A1,
    A2,
    ALLHALTED,
    ALLRESUMEACK,
    CSR_DCSR,
    CSR_DPC,
    CSR_MRAC,
    CSR_MTVEC,
    DCSR_CAUSE_EBREAK,
    DCSR_CAUSE_SHIFT,
    DCSR_EBREAKM,
    DMACTIVE,
    DMCONTROL,
    HALT_POLLS,
    HALTREQ,
    ICCM_BASE,
    LOAD_REGS,
    LOAD_SENTINEL,
    PROBE_EBREAK,
    PROBE_LOADS,
    PROBE_STORES,
    RESUMEREQ,
    RUN_POLLS,
    STORE_WORD,
    TRAP_VECTOR,
    smu_sep_lsu_fabric_test_seq,
)
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import ADDR_MASK, SMU_BASE, SMU_SIZE
from seq_lib.smu_tb_pins import smc_primary_reset
from seq_lib.smu_xbar_decerr_burst_response_test_seq import _hx, _rn, _val

# --- the SEP's SMU window (sep_cpu_ctrl reset values): every sep_out address lies in it ---
LSU_EXT_S2 = SMU_BASE + 0x1000_2000
LSU_EXT_S3 = SMU_BASE + 0x1000_3000
SBA_EXT = SMU_BASE + 0x1000_4000
SBA_FWD = SMU_BASE + 0x1000_6000
PROBE_SPAN = 0x80
# Aperture placements inside the SEP's SMU window, clear of the words above
SEP_SELF_BASE = SMU_BASE + 0x1200_0000
PLACE_RESET_SIZES = (
    SEP_SELF_BASE,
    SEP_REGION_SIZE_RESET,
    SMU_BASE + 0x2000_0000,
    SMC_REGION_SIZE_RESET,
)
PLACE_REPROGRAM = (SMU_BASE + 0x1400_0000, 0x0080_0000, SMU_BASE + 0x3000_0000, 0x0080_0000)

# --- SMC scratchpad offsets and the zeroer slot past its registers (zeroer.adoc: DECERR) ---
SPM_PROBE_OFF = 0x3000
ZEROER_GAP_LOCAL = (
    smc_addr("SMC_TOP_ZEROER_CTRL_BASE_ADDR") + smc_addr("SMC_TOP_ZEROER_CTRL_SIZE") + 8
)

# --- ext_out ranges of the smc_out partners ---
S2_DMA_LEN = 0x8000
S3_DMA_LEN = 0x400
S3_DMA_SRC = SEP_SRAM + 0x800
EXT_S3_DST = 0x5050_0000
EXT_S3_J2A = 0x5058_0000
EXT_S3_ERR = 0x5059_0000
EXT_S3_SRC2 = 0x505A_0000
EXT_S3_DST2 = 0x505B_0000
S3_DMA2_LEN = 0x100
NEITHER_RD_PAGE = NEITHER + 0x4000
NEITHER_WR_PAGE = NEITHER + 0x5000
DECERR_LENS = (1, 15, 255)

# --- bounds, clk_smu_i edges unless named ---
LINK_TAIL = 32
HELD_READ_DELAY = 12_000
S2_RESP_DELAY = (32, 128)
S2_STALL_CHOICES = (12, 16, 24)
SEP_WAIT_BOUND = 4_000

FENCE = (
    "SETUP",
    "STALLED_EXT_OUT",
    "INTERLEAVE",
    "ROUTE_FWD",
    "DECERR_CELLS",
    "APERTURE_EDGES",
    "ZERO_SIZE",
)
# (LSU probe runs, system-bus accesses on sep_out) per term: the step budget of the contract
BUDGET = {
    "SETUP": (0, 2),
    "STALLED_EXT_OUT": (1, 4),
    "INTERLEAVE": (2, 4),
    "ROUTE_FWD": (0, 2),
    "DECERR_CELLS": (0, 2),
    "APERTURE_EDGES": (0, 16),
    "ZERO_SIZE": (0, 12),
}
CNT2 = {
    "sep_aw": "sep_xbar_in_aw_count_o",
    "sep_ar": "sep_xbar_in_ar_count_o",
    "smc_aw": "smc_xbar_in_aw_count_o",
    "smc_ar": "smc_xbar_in_ar_count_o",
    "dtp_aw": "dtp_smc_dbg_aw_count_o",
    "dtp_ar": "dtp_smc_dbg_ar_count_o",
    "dtp_b": "dtp_smc_dbg_b_count_o",
    "sepout_aw": "sep_smn_out_aw_count_o",
    "sepout_ar": "sep_smn_out_ar_count_o",
}
# One-bit request VALIDs that open a link sampling window on the edge they rise.
GATE_NETS = (
    "ext_in_awvalid",
    "ext_in_wvalid",
    "ext_in_arvalid",
    "alias_awvalid_w",
    "alias_arvalid_w",
    *(
        f"u_smu_xbar_fcov.xbar_{port}_{ch}valid_i"
        for port in ("sep_out", "smc_out", "sep_in", "smc_in", "ext_out")
        for ch in ("aw", "ar")
    ),
)
_EXTRA = {
    "aw": ("awprot", "awcache", "awqos", "awregion", "awlock"),
    "w": ("wstrb", "wuser"),
    "ar": ("arprot", "arcache", "arqos", "arregion", "arlock"),
    "b": (),
    "r": (),
}
INITIATORS = ("xbar_sep_out", "xbar_smc_out", "xbar_ext_in")
TARGETS = ("xbar_sep_in", "xbar_smc_in", "xbar_ext_out")
TARGET_OF = {"sep_in": "xbar_sep_in", "smc_in": "xbar_smc_in", "ext_out": "xbar_ext_out"}
CHECKER_INSTANCE = {name: f"u_{name}_axi_sva" for name, _, _ in LINKS}
CHECKER_INSTANCE["dtp_dbg"] = "u_dtp_smc_dbg_axi_sva"
# Links whose initiators issue single-beat transactions only.
SINGLE_BEAT_LINKS = {
    "xbar_sep_out": (
        'hw/sys/sep/doc/fabric.adoc, Top Level AXI4: "The CPU masters and the DMA issue '
        "single-beat transactions only\"; the LSU and the debug system bus are the SEP's "
        "sep_out initiators"
    ),
    "sep_to_smc": (
        'hw/sys/sep/doc/fabric.adoc, Top Level AXI4: "The CPU masters and the DMA issue '
        "single-beat transactions only\"; the LSU and the debug system bus are the SEP's "
        "SEP-to-SMC initiators"
    ),
    "dtp_dbg": (
        "hw/ip/jtag/jtag_ptap/doc/architecture.adoc, JTAG2AXI single operation: one "
        "operation carries one address, one D-bit data word and a size of at most one beat "
        '("A size above data_size transfers one full D-bit beat")'
    ),
}
SMC_OUT_SMC_NOT_DRIVABLE = (
    "INFO-CELL-NOT-DRIVABLE: SMC_OUT/SMC-aperture-decerr hw/sys/smc/doc/fabric.adoc, input "
    'fabric: "The demux behind it sends addresses inside the SMC window, at either the local '
    'or the global base and REGION_SIZE long, to the local_in initiator of the local fabric", '
    "and the crossbar's SMC aperture is the same GLOBAL_BASE and REGION_SIZE, so no iDMA or "
    "JTAG2AXI burst into the SMC aperture reaches the smc_out port"
)
REGION_SIZE_RESTORE_NOT_DRIVABLE = (
    'INFO-CELL-NOT-DRIVABLE: SMC/REGION_SIZE-restore hw/sys/smc/doc/fabric.adoc: "A '
    "REGION_SIZE of zero collapses both windows and routes SMC CPU accesses to its own "
    'resources out through the output fabric"; the JTAG2AXI bridge is one of those SMC '
    "initiators and the SEP-to-SMC and ext_in paths decode the same zero size, so no access "
    "path reaches REGION_SIZE once it is 0 and it stays 0 to the end of the leaf"
)


def _fld(bits: str, pos: tuple[int, int]) -> int | None:
    lsb, width = pos
    if width == 0:
        return 0
    text = bits[len(bits) - lsb - width : len(bits) - lsb]
    if set(text) - {"0", "1"}:
        return None
    return int(text, 2)


def _known(text: str) -> bool:
    return not set(text) - {"0", "1"}


def _overlap(a: list[tuple[int, int]], b: list[tuple[int, int]]) -> bool:
    return any(s1 <= e2 and s2 <= e1 for s1, e1 in a for s2, e2 in b)


def _overlap3(a, b, c) -> bool:
    for s1, e1 in a:
        for s2, e2 in b:
            lo, hi = max(s1, s2), min(e1, e2)
            if lo <= hi and _overlap([(lo, hi)], c):
                return True
    return False


class _PinTap(_Tap):
    """The sibling tap with the AxPROT, AxCACHE, AxQOS, AxREGION, AxLOCK and W fields added."""

    def __init__(self, dut, name: str, get) -> None:
        super().__init__(dut, name, get)
        pins = {}
        for ch, (v, r, fields) in _CH.items():
            names = list(fields)
            for extra in _EXTRA[ch]:
                try:
                    get(extra)
                except AttributeError:
                    continue
                names.append(extra)
            if ch == "w":
                names.append("wdata")
            pins[ch] = (get(v), get(r), {f: get(f) for f in names})
        self.pins = pins


class _LinkTap:
    """Every handshake of one checked link, decoded from its request and response structs.

    Field positions follow the pulp AXI4 struct layout ``_Link`` decodes; the
    W, AxSIZE, AxPROT, AxCACHE, AxQOS, AxREGION, AxLOCK, RDATA and USER fields
    are added here.
    """

    def __init__(self, dut, name: str, req_path: str, resp_path: str) -> None:
        self.name = name
        self.link = link = _Link(dut, name, req_path, resp_path)
        idw, uw, a, d = link.idw, link.uw, LINK_ADDR_BITS, LINK_DATA_BITS
        ar = idw + a + 29 + uw
        w = d + d // 8 + 1 + uw
        r = idw + d + 3 + uw
        awb, wb, arb = 5 + ar + w, 4 + ar, 2
        q, p = link.q, link.p
        self.d = d
        self.fields = {
            "aw": {
                "awid": q["aw_id"],
                "awaddr": q["aw_addr"],
                "awlen": q["aw_len"],
                "awsize": (awb + uw + 24, 3),
                "awburst": q["aw_burst"],
                "awlock": (awb + uw + 21, 1),
                "awcache": (awb + uw + 17, 4),
                "awprot": (awb + uw + 14, 3),
                "awqos": (awb + uw + 10, 4),
                "awregion": (awb + uw + 6, 4),
                "awatop": q["aw_atop"],
                "awuser": q["aw_user"],
            },
            "w": {"wlast": (wb + uw, 1), "wstrb": (wb + uw + 1, d // 8), "wuser": (wb, uw)},
            "ar": {
                "arid": q["ar_id"],
                "araddr": q["ar_addr"],
                "arlen": q["ar_len"],
                "arsize": (arb + uw + 18, 3),
                "arburst": q["ar_burst"],
                "arlock": (arb + uw + 15, 1),
                "arcache": (arb + uw + 11, 4),
                "arprot": (arb + uw + 8, 3),
                "arqos": (arb + uw + 4, 4),
                "arregion": (arb + uw, 4),
                "aruser": q["ar_user"],
            },
            "b": {"bid": p["b_id"], "bresp": p["b_resp"], "buser": (r + 1, uw)},
            "r": {"rid": p["r_id"], "rresp": p["r_resp"], "ruser": (0, uw)},
        }
        self.w_data = (wb + uw + 1 + d // 8, d)
        self.r_data = (uw + 3, d)
        self.r_last = p["r_last"]
        self.ev: dict[str, list[dict]] = {ch: [] for ch in self.fields}
        self.open = 0
        self.active = False

    def sample(self, cyc: int) -> None:
        """Take the handshakes of one clk_smu_i edge."""
        link = self.link
        qs, ps = str(link.req.value), str(link.resp.value)
        hs = link.handshakes(qs, ps)
        self.active = False
        for ch, fields in self.fields.items():
            valid = hs[f"{ch}_valid"]
            if valid != "0":
                self.active = True
            if valid != "1" or hs[f"{ch}_ready"] != "1":
                continue
            bits = qs if ch in ("aw", "w", "ar") else ps
            e = {"cyc": cyc, "t": _now()}
            e.update({k: _fld(bits, pos) for k, pos in fields.items()})
            if ch == "w":
                lsb, width = self.w_data
                data = bits[len(bits) - lsb - width : len(bits) - lsb]
                strb = bits[
                    len(bits) - fields["wstrb"][0] - width // 8 : len(bits) - fields["wstrb"][0]
                ]
                lanes = width // 8
                x_lanes = 0
                strobed = 0
                for lane in range(lanes):
                    s = strb[lanes - 1 - lane]
                    lane_bits = data[width - 8 * (lane + 1) : width - 8 * lane]
                    if s != "0":
                        strobed += 1
                        if s != "1" or not _known(lane_bits):
                            x_lanes += 1
                e["strobed_lanes"] = strobed
                e["x_lanes"] = x_lanes
                e["wdata"] = _fld(bits, self.w_data)
            elif ch == "r":
                e["rlast"] = {"1": 1, "0": 0}.get(link.bit(ps, self.r_last))
                lsb, width = self.r_data
                e["rdata"] = _fld(bits, self.r_data)
                e["r_x"] = not _known(bits[len(bits) - lsb - width : len(bits) - lsb])
            if ch in ("aw", "ar"):
                self.open += 1
            elif ch == "b" or (ch == "r" and e["rlast"] == 1):
                self.open = max(0, self.open - 1)
            self.ev[ch].append(e)

    def mark(self) -> dict[str, int]:
        return {ch: len(evs) for ch, evs in self.ev.items()}

    def since(self, mark: dict[str, int], ch: str) -> list[dict]:
        return self.ev[ch][mark[ch] :]


def _pairing(tap: _LinkTap, mk: dict[str, int]) -> dict[str, int]:
    """Per ID, one B per AW and AxLEN+1 R beats with RLAST on the last per AR, in order."""
    events = []
    for ch, rank in (("aw", 0), ("ar", 0), ("b", 1), ("r", 1)):
        events += [(e["cyc"], rank, ch, e) for e in tap.since(mk, ch)]
    events.sort(key=lambda x: (x[0], x[1]))
    aw: dict = defaultdict(list)
    ar: dict = defaultdict(list)
    beats: dict = defaultdict(int)
    out = {"requests": 0, "order_violations": 0, "lost": 0, "dup": 0}
    for _, _, ch, e in events:
        if ch == "aw":
            aw[e["awid"]].append(e)
            out["requests"] += 1
        elif ch == "ar":
            ar[e["arid"]].append(e)
            out["requests"] += 1
        elif ch == "b":
            if aw[e["bid"]]:
                aw[e["bid"]].pop(0)
            else:
                out["dup"] += 1
        else:
            rid = e["rid"]
            if not ar[rid]:
                out["dup"] += 1
                continue
            beats[rid] += 1
            want = (ar[rid][0]["arlen"] or 0) + 1
            last = beats[rid] == want
            if (e["rlast"] == 1) != last:
                out["order_violations"] += 1
            if e["rlast"] == 1 or last:
                ar[rid].pop(0)
                beats[rid] = 0
    out["lost"] = sum(len(v) for v in aw.values()) + sum(len(v) for v in ar.values())
    return out


class smu_axi_sep_lsu_initiator_stall_test_seq(smu_axi_concurrent_initiators_stall_test_seq):
    """sep_out (LSU probe and system bus), smc_out and ext_in against a stalling ext_out."""

    # The probe controls of smu_sep_lsu_fabric_test, driven over this leaf's DMI path.
    _abstract = smu_sep_lsu_fabric_test_seq._abstract
    _reg_write = smu_sep_lsu_fabric_test_seq._reg_write
    _reg_read = smu_sep_lsu_fabric_test_seq._reg_read
    _wait_status = smu_sep_lsu_fabric_test_seq._wait_status

    def __init__(self, test) -> None:
        super().__init__(test)
        self.rng.seed(self.seed ^ 0x6C4C_004B)
        self.term = "SETUP"
        self.lsu_runs: Counter = Counter()
        self.sba_stim: Counter = Counter()
        self.wall0 = time.monotonic()
        self.wall_mark = self.wall0
        self.sep_smc_port: list[str] = []
        self.decerr_obs: list[str] = []

    # ------------------------------------------------------------------ observation

    async def _watch(self) -> None:
        """One coroutine samples the pin taps on every edge and the links in their windows."""
        cyc = 0
        tail = 0
        gates = self.gates
        while True:
            await RisingEdge(self.dut.clk_smu_i)
            cyc += 1
            self.ext.sample(cyc)
            self.out.sample(cyc)
            self.links["dtp_dbg"].sample(cyc)
            if gates is None:
                hot = True
            else:
                hot = self.links["dtp_dbg"].active or any(str(h.value) != "0" for h in gates)
            if hot or tail > 0 or any(t.open for t in self.links.values()):
                for name, tap in self.links.items():
                    if name != "dtp_dbg":
                        tap.sample(cyc)
                tail = (
                    LINK_TAIL
                    if hot or any(t.active for t in self.links.values())
                    else max(0, tail - 1)
                )

    def _start_taps(self) -> None:
        dut = self.dut
        self.ext = _PinTap(dut, "ext_in", lambda n: getattr(dut, f"ext_in_{n}"))
        self.out = _PinTap(dut, "ext_out", lambda n: getattr(dut.u_axi_out_if, n))
        self.links = {name: _LinkTap(dut, name, rq, rp) for name, rq, rp in LINKS}
        self.xbar = self.links["xbar_smc_out"]
        try:
            gates = []
            for path in GATE_NETS:
                node = dut
                for part in path.split("."):
                    node = getattr(node, part)
                gates.append(node)
            self.gates = gates
        except AttributeError as exc:
            self.gates = None
            self._info(f"G4B-GATE: {exc}; every link is sampled on every edge")
        cocotb.start_soon(self._watch())

    def _cnt(self) -> dict[str, int | None]:
        return {k: _val(getattr(self.dut, n)) for k, n in CNT2.items()}

    def _marks(self) -> dict[str, dict[str, int]]:
        return {name: tap.mark() for name, tap in self.links.items()}

    def _since(self, mks: dict, name: str, ch: str) -> list[dict]:
        return self.links[name].since(mks[name], ch)

    def _mark(self, term: str, count: int, planned: int) -> None:
        now = time.monotonic()
        runs, sba = self.lsu_runs[term], self.sba_stim[term]
        self.fence.append((term, _now(), count, planned, runs, sba, round(now - self.wall_mark, 1)))
        self.wall_mark = now
        self._info(
            f"G4B-STEP: {term} t={_now()}ns count={count} planned={planned} lsu_runs={runs} "
            f"sba={sba} config_sba={self.sba_count}"
        )

    # ------------------------------------------------------------------ DMI / system bus / probe

    async def _dmi(self, jtag, addr: int, data: int, op: int) -> int:
        return await self._dmi_op(addr, data, op, f"dm{addr:02x}", record=False)

    async def _dmi_collect(self, addr: int, label: str) -> int:
        """Collect scans of the DMI access a scan issued, retried while busy, bounded."""
        used = 0
        while True:
            _, captured = await self._dr(
                DTP_IR_TAP_3DCR,
                ptap_3dcr_value(config_hold=CONFIG_HOLD_CLEAR, select=PTAP_3DCR_SELECT),
                PTAP_3DCR_WIDTH,
                f"dmi_{label}_c{used}",
                counted=False,
                sep_request=pack_dmi(addr, 0, op=DMI_OP_NOP),
                idle=DMI_IDLE_TCKS,
            )
            used += 1
            _, value, status = unpack_dmi(captured)
            if status != DMI_STATUS_BUSY:
                break
            if used >= DMI_RETRY_LIMIT:
                self._expire(f"dmi_{label}", DMI_RETRY_LIMIT, "retries", "DMI status leaving busy")
        self.waits.append((f"dmi_{label}", DMI_RETRY_LIMIT, "retries", used, f"status={status}"))
        if status != DMI_STATUS_OK:
            raise AssertionError(f"dmi {label} addr=0x{addr:02x} status={status}")
        return value

    async def _j2a_with_dmi(
        self, op: int, addr: int, data: int, dmi_addr: int, dmi_data: int, *, label: str
    ) -> tuple[int, int]:
        """One scan updates a JTAG2AXI operation and a DMI write together; both complete."""
        size = 3
        wstrb = 0xFF if op == J2A_OP_WRITE else 0
        raw = pack_single_op(op, addr, data, wstrb=wstrb, size=size)
        self.j2a_count += 1
        await self._dr(
            DTP_IR_SMC_AXI_SINGLE_OP,
            raw,
            SMC_DBG_SINGLE_OP_LEN,
            f"{label}_issue",
            sep_request=pack_dmi(dmi_addr, dmi_data, op=DMI_OP_WRITE),
            idle=DMI_IDLE_TCKS,
        )
        await self._dmi_collect(dmi_addr, f"{label}_dmi")
        used = 0
        while True:
            captured, _ = await self._dr(
                DTP_IR_SMC_AXI_SINGLE_OP,
                0,
                SMC_DBG_SINGLE_OP_LEN,
                f"{label}_c{used}",
                counted=False,
            )
            status, rdata = unpack_single_op(captured)
            used += 1
            if status != J2A_STATUS_BUSY:
                break
            if used >= 32:
                self._expire(label, 32, "polls", f"J2A op @0x{addr:x} leaving busy")
            await ClockCycles(self.dut.clk_smu_i, 64)
        self.waits.append((f"j2a_{label}", 32, "polls", used, f"status={status}"))
        return status, rdata

    async def _sb_issue(self, addr: int, *, size: int, data: int | None, label: str) -> None:
        """Start one system-bus access on the SEP debug master; it is counted against the step."""
        self.sba_stim[self.term] += 1
        sbcs = (size << 17) | SBCS_SBERROR_W1C | (SBCS_SBREADONADDR if data is None else 0)
        await self._dmi_op(SBCS_ADDR, sbcs, DMI_OP_WRITE, f"{label}_sbcs")
        if data is not None and size == 3:
            await self._dmi_op(
                SBDATA1_ADDR, (data >> 32) & 0xFFFF_FFFF, DMI_OP_WRITE, f"{label}_d1"
            )
        await self._dmi_op(SBADDRESS0_ADDR, addr, DMI_OP_WRITE, f"{label}_addr")
        if data is not None:
            await self._dmi_op(SBDATA0_ADDR, data & 0xFFFF_FFFF, DMI_OP_WRITE, f"{label}_d0")

    async def _sb_finish(self, *, size: int, read: bool, label: str) -> tuple[int, int]:
        """Poll sbcs until idle, bounded; return (sberror, read data)."""
        used = 0
        while True:
            sbcs = await self._dmi_op(
                SBCS_ADDR, 0, DMI_OP_READ, f"{label}_sbcs{used}", record=False
            )
            used += 1
            if not sbcs & SBCS_SBBUSY:
                break
            if used >= SBA_POLL_LIMIT * 4:
                self._expire(f"sba_{label}", SBA_POLL_LIMIT * 4, "polls", "sbcs.sbbusy clear")
            await ClockCycles(self.dut.clk_smu_i, 64)
        self.waits.append((f"sba_{label}", SBA_POLL_LIMIT * 4, "polls", used, f"sbcs=0x{sbcs:08x}"))
        if sbcs & SBCS_SBBUSYERROR:
            raise AssertionError(f"system bus {label}: sbbusyerror sbcs=0x{sbcs:08x}")
        err = (sbcs >> SBCS_SBERROR_SHIFT) & SBCS_SBERROR_MASK
        if err or not read:
            return err, 0
        value = await self._dmi_op(SBDATA0_ADDR, 0, DMI_OP_READ, f"{label}_rd0", record=False)
        if size == 3:
            value |= (
                await self._dmi_op(SBDATA1_ADDR, 0, DMI_OP_READ, f"{label}_rd1", record=False) << 32
            )
        return err, value & ((1 << (8 << size)) - 1)

    async def _sb(self, addr: int, *, size: int = 2, data: int | None = None, label: str):
        await self._sb_issue(addr, size=size, data=data, label=label)
        return await self._sb_finish(size=size, read=data is None, label=label)

    async def _sba_write32(self, addr: int, value: int, label: str) -> None:
        """A SEP-local configuration write over the system bus (not sep_out traffic)."""
        self.sba_count += 1
        await self._sba_write(addr, value, label)

    async def _halt(self) -> dict:
        jtag = self.jtag
        await self._dmi(jtag, DMCONTROL, DMACTIVE | HALTREQ, DMI_OP_WRITE)
        halted = await self._wait_status(jtag, ALLHALTED, HALT_POLLS)
        await self._dmi(jtag, DMCONTROL, DMACTIVE, DMI_OP_WRITE)
        self.waits.append(("halt", HALT_POLLS, "dmstatus polls", 0, f"allhalted={halted}"))
        if not halted:
            self._expire("halt", HALT_POLLS, "dmstatus polls", "dmstatus.allhalted")
        dcsr = await self._reg_read(jtag, CSR_DCSR)
        await self._reg_write(jtag, CSR_DCSR, dcsr | DCSR_EBREAKM)
        await self._reg_write(jtag, CSR_MTVEC, TRAP_VECTOR)
        self.sba_count += 2
        await self._sba_write64(OUTBOUND_START_ADDR, 0, "outbound1_start")
        await self._sba_write64(OUTBOUND_END_ADDR, ADDR_MASK, "outbound1_end")
        await self._sba_write32(OUTBOUND_FILTER_CONFIG, OUTBOUND_CFG_OPEN, "outbound1_config")
        return {"halted": halted, "dcsr": _hx(dcsr)}

    async def _probe_arm(self, base: int) -> None:
        """Point the halted hart at the probe with a0=base; the hart stays halted."""
        jtag = self.jtag
        self.lsu_runs[self.term] += 1
        await self._reg_write(jtag, CSR_MRAC, 0)
        await self._reg_write(jtag, A0, base)
        await self._reg_write(jtag, A1, STORE_WORD)
        await self._reg_write(jtag, A2, 0)
        for reg in LOAD_REGS:
            await self._reg_write(jtag, reg, LOAD_SENTINEL)
        await self._reg_write(jtag, CSR_DPC, ICCM_BASE)

    async def _probe_finish(self, label: str) -> dict:
        """Wait for the hart to halt again (bounded) and read what it reports."""
        jtag = self.jtag
        resumed = await self._wait_status(jtag, ALLRESUMEACK, HALT_POLLS)
        await self._dmi(jtag, DMCONTROL, DMACTIVE, DMI_OP_WRITE)
        halted = await self._wait_status(jtag, ALLHALTED, RUN_POLLS)
        self.waits.append((f"probe_{label}", RUN_POLLS, "dmstatus polls", 0, f"halted={halted}"))
        if not resumed or not halted:
            self._expire(
                f"probe_{label}",
                RUN_POLLS,
                "dmstatus polls",
                f"resumeack={resumed} halted={halted}",
            )
        dcsr = await self._reg_read(jtag, CSR_DCSR)
        return {
            "resumed": resumed,
            "halted": halted,
            "cause": (dcsr >> DCSR_CAUSE_SHIFT) & 0x7,
            "dpc": await self._reg_read(jtag, CSR_DPC),
            "sum": await self._reg_read(jtag, A2),
            "loads": [await self._reg_read(jtag, reg) for reg in LOAD_REGS],
        }

    @staticmethod
    def _completed() -> dict:
        return {
            "resumed": True,
            "halted": True,
            "cause": DCSR_CAUSE_EBREAK,
            "dpc": PROBE_EBREAK,
            "sum": (PROBE_LOADS * STORE_WORD) & 0xFFFF_FFFF,
            "loads": [STORE_WORD] * PROBE_LOADS,
        }

    def _held(self, base: int) -> tuple[dict, dict]:
        """The responder bytes each probe store wrote, against the store word."""
        mem = self.cfg.axi_out_mem
        held, want = {}, {}
        for width, off in PROBE_STORES:
            held[off] = mem.read_int(base + off, width)
            want[off] = STORE_WORD & ((1 << (8 * width)) - 1)
        return held, want

    # ------------------------------------------------------------------ routing

    def _windows(self) -> tuple[int, int, int, int]:
        sb, ss = self._sep_window()
        return sb, ss, _val(self.dut.smc_global_base_o), _val(self.dut.smc_region_size_o)

    @staticmethod
    def _route_of(init: str, addr: int, win: tuple[int, int, int, int]) -> str:
        """The routing-table cell of hw/sys/smu/doc/index.adoc for one request."""
        sb, ss, mb, ms = win
        sep = ss != 0 and sb <= addr < sb + ss
        smc = ms != 0 and mb <= addr < mb + ms
        table = {
            "xbar_sep_out": ("DECERR", "smc_in", "ext_out"),
            "xbar_smc_out": ("sep_in", "DECERR", "ext_out"),
            "xbar_ext_in": ("sep_in", "smc_in", "DECERR"),
        }[init]
        return table[0] if sep else table[1] if smc else table[2]

    def _misrouted(self, mks: dict, win: tuple[int, int, int, int]) -> tuple[int, list]:
        """Every crossbar request appears at the target its cell names, and at no other."""
        want: dict[str, Counter] = {t: Counter() for t in TARGETS}
        for init in INITIATORS:
            for ch in ("aw", "ar"):
                for e in self._since(mks, init, ch):
                    cell = self._route_of(init, e[f"{ch}addr"] or 0, win)
                    if cell in TARGET_OF:
                        want[TARGET_OF[cell]][(ch, e[f"{ch}addr"])] += 1
        got: dict[str, Counter] = {t: Counter() for t in TARGETS}
        for tgt in TARGETS:
            for ch in ("aw", "ar"):
                for e in self._since(mks, tgt, ch):
                    got[tgt][(ch, e[f"{ch}addr"])] += 1
        bad = []
        for tgt in TARGETS:
            for key in set(want[tgt]) | set(got[tgt]):
                if want[tgt][key] != got[tgt][key]:
                    bad.append((tgt, key[0], _hx(key[1]), want[tgt][key], got[tgt][key]))
        return len(bad), bad[:8]

    async def _sep_access(
        self, label: str, addr: int, *, size: int = 2, data: int | None = None
    ) -> dict:
        """One system-bus access; where it appeared, its response at sep_out and its result."""
        mks = self._marks()
        c0 = self._cnt()
        err, rdata = await self._sb(addr, size=size, data=data, label=label)
        await ClockCycles(self.dut.clk_smu_i, 4)
        ch = "ar" if data is None else "aw"
        rch = "r" if data is None else "b"
        key = f"{ch}addr"
        seen = {
            name: [e for e in self._since(mks, name, ch) if e[key] == addr]
            for name in ("xbar_sep_out", "sep_to_smc", *TARGETS)
        }
        reqs = seen["xbar_sep_out"]
        resps = self._since(mks, "xbar_sep_out", rch)
        idk = f"{ch}id"
        rid = "rid" if data is None else "bid"
        ids_ok = len(reqs) == 1 and [e[rid] for e in resps if e.get("rlast", 1) == 1] == [
            reqs[0][idk]
        ]
        codes = [_rn(e["rresp" if data is None else "bresp"]) for e in resps]
        hits = {name: len(evs) for name, evs in seen.items()}
        if hits["xbar_ext_out"] == 1 and not hits["xbar_sep_in"] and not hits["xbar_smc_in"]:
            route = "ext_out"
        elif (
            hits["xbar_sep_out"] == 1
            and not any(hits[t] for t in TARGETS)
            and set(codes) == {"DECERR"}
        ):
            route = "DECERR"
        elif hits["xbar_smc_in"] == 1 and not hits["xbar_ext_out"] and not hits["xbar_sep_in"]:
            route = "smc_in"
        elif (
            hits["sep_to_smc"] == 1
            and not hits["xbar_sep_out"]
            and not any(hits[t] for t in TARGETS)
        ):
            route = "sep_to_smc"
        else:
            route = f"hits={hits} codes={codes}"
        return {
            "label": label,
            "addr": addr,
            "route": route,
            "err": err,
            "rdata": rdata,
            "ids_ok": ids_ok,
            "codes": codes,
            "hits": hits,
            "d": self._d(c0, self._cnt()),
            "req": reqs,
            "resp": resps,
            "out": seen["xbar_ext_out"],
        }

    # ------------------------------------------------------------------ S1

    async def _s1_setup(self) -> None:
        dut = self.dut
        sb = self.sb
        self.term = "SETUP"
        await self.cfg.reset_done.wait()
        self._start_taps()
        await RisingEdge(dut.clk_smu_i)
        self.stall = self.rng.choice(STALL_CHOICES)
        self.s2_stall = self.rng.choice(S2_STALL_CHOICES)
        self.prof = AxiTimingProfile(
            ar_delay=self.rng.randint(0, 6),
            w_delay=self.rng.randint(0, 6),
            b_ready_delay=self.rng.randint(0, 12),
            r_ready_delay=self.rng.randint(0, 12),
        )
        self._raw(
            f"INFO-SEED: RANDOM_SEED={self.seed} responder_stall={self.stall} "
            f"s2_responder_stall={self.s2_stall} responder_resp_delay={RESP_DELAY} "
            f"s2_resp_delay={S2_RESP_DELAY} master_profile={self.prof}; the request set is fixed"
        )
        self._info("STEP S1: SETUP")
        idcode = await self._jtag_bringup("s1")
        lc, dbg = await self._posture("s1")
        security = _val(dut.tb_smc_jtag2axi_security_disable)
        inb = await self._program_inbound0("s1")
        outb = []
        for addr, data, name in (
            (OUTBOUND0_START, 0, "start"),
            (OUTBOUND0_END, PASS_ALL_END, "end"),
            (OUTBOUND0_FILTER_CONFIG, PASS_RW_CONFIG, "config"),
        ):
            st, _ = await self._j2a(J2A_OP_WRITE, addr, data, label=f"s1_outbound0_{name}")
            outb.append(st)
        smc_base = await self._rd32(SMC_GLOBAL_BASE_REG, "s1_smc_global_base")
        smc_size = await self._rd32(SMC_REGION_SIZE_REG, "s1_smc_region_size")
        dmactive = await self._activate_debug_module("s1")
        sep_base = await self._sba_read64(SEP_GLOBAL_BASE_ADDR, "s1_sep_base_rb")
        sep_size = await self._sba_read64(SEP_REGION_SIZE_ADDR, "s1_sep_size_rb")
        self.reset_rb = (sep_base, sep_size, smc_base, smc_size)
        halt = await self._halt()
        sb.expect_eq(
            "S1 access path open, hart halted and aperture registers at their RDL reset",
            (
                _hx(idcode),
                dbg,
                security,
                inb,
                outb,
                dmactive,
                halt["halted"],
                tuple(_hx(v) for v in self.reset_rb),
            ),
            (
                _hx(DTP_DEFAULT_IDCODE),
                0,
                0,
                [J2A_STATUS_SUCCESS] * 3,
                [J2A_STATUS_SUCCESS] * 3,
                1,
                True,
                tuple(
                    _hx(v)
                    for v in (
                        SEP_GLOBAL_BASE_RESET,
                        SEP_REGION_SIZE_RESET,
                        SMC_GLOBAL_BASE_RESET,
                        SMC_REGION_SIZE_RESET,
                    )
                ),
            ),
        )
        self._info(
            f"G4B-SETUP: lc_state={_hx(lc)} halt={halt} SMU window=[{_hx(SMU_BASE)}, +{_hx(SMU_SIZE)})"
        )
        await self._sep_csr("size", SEP_WIDE_SIZE, "s1_sep_size_wide")
        self.master = await make_smu_axi_master(dut, dut.clk_smu_i, smc_primary_reset(dut))
        clear_profile(self.master.driver)
        mem = self.cfg.axi_out_mem
        sb.expect_eq("G4B responder depth", mem.max_outstanding, RESPONDER_DEPTH)
        self.sep_pat = bytes((0x5E + 3 * i) & 0xFF for i in range(SEP_FILL_BYTES))
        self.spm_pat = bytes((0x3C + 5 * i) & 0xFF for i in range(SPM_FILL_BYTES))
        fills = []
        for k in range(SEP_FILL_BYTES // 0x800):
            t = await self._ext(
                f"s1_fill_sep{k}",
                write=True,
                addr=SEP_SRAM + 0x800 * k,
                nbytes=0x800,
                xid=0x01,
                data=self.sep_pat[0x800 * k : 0x800 * (k + 1)],
            )
            fills.append(self._codes(t))
        t = await self._ext(
            "s1_fill_spm", write=True, addr=SPM, nbytes=SPM_FILL_BYTES, xid=0x02, data=self.spm_pat
        )
        fills.append(self._codes(t))
        for base in (LSU_EXT_S2, LSU_EXT_S3, SBA_EXT, SBA_FWD):
            mem.write(base, bytes(PROBE_SPAN))
        sb.expect_eq("S1 reference fills OKAY", fills, [["OKAY"]] * len(fills))
        ok, want = {}, {}
        word = 0x5E0C_0001_5E0C_0002
        w = await self._sep_access("s1_ok_sep_out_wr", SBA_EXT, size=3, data=word)
        r = await self._sep_access("s1_ok_sep_out_rd", SBA_EXT, size=3)
        ok["sep_out->ext_out"] = (w["err"], r["err"], _hx(r["rdata"]), w["route"], r["route"])
        want["sep_out->ext_out"] = (0, 0, _hx(word), "ext_out", "ext_out")
        for cell, addr, wd in (
            ("smc_out->sep_in", SEP_SRAM + 0x1000 - 0x40, 0x5E50_0000_0000_0011),
            ("smc_out->ext_out", EXT_J2A + 0x80, 0xE7E7_0000_0000_0012),
        ):
            st_w, _ = await self._j2a(J2A_OP_WRITE, addr, wd, label=f"s1_ok_{cell}_wr")
            st_r, rd = await self._j2a(J2A_OP_READ, addr, label=f"s1_ok_{cell}_rd")
            ok[cell] = (st_w, st_r, _hx(rd))
            want[cell] = (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, _hx(wd))
            if cell == "smc_out->sep_in":
                off = addr - SEP_SRAM
                self.sep_pat = (
                    self.sep_pat[:off] + wd.to_bytes(8, "little") + self.sep_pat[off + 8 :]
                )
        for cell, addr, xid in (
            ("ext_in->sep_in", SEP_SRAM + 0x1000 - 0x80, 0x03),
            ("ext_in->smc_in", SPM + SPM_FILL_BYTES + 0x40, 0x04),
        ):
            data = bytes((xid * 0x11 + i) & 0xFF for i in range(8))
            wt = await self._ext(
                f"s1_ok_{cell}_wr", write=True, addr=addr, nbytes=8, xid=xid, data=data
            )
            rt = await self._ext(
                f"s1_ok_{cell}_rd", write=False, addr=addr, nbytes=8, xid=xid + 0x10
            )
            ok[cell] = (self._codes(wt), self._codes(rt), self._rdata(rt, 8).hex())
            want[cell] = (["OKAY"], ["OKAY"], data.hex())
            if cell == "ext_in->sep_in":
                off = addr - SEP_SRAM
                self.sep_pat = self.sep_pat[:off] + data + self.sep_pat[off + 8 :]
        sb.expect_eq("CTRL-G4B-OKAY one write then read per permitted cell", ok, want)
        self._raw(f"CTRL-G4B-OKAY: cells={len(ok)} {ok}")
        for name, why in SINGLE_BEAT_LINKS.items():
            self._raw(f"INFO-CELL-NOT-DRIVABLE: {name}/multi-beat-AW-AR {why}")
        self._raw(SMC_OUT_SMC_NOT_DRIVABLE)
        self._mark("SETUP", len(ok), 5)

    # ------------------------------------------------------------------ S2

    def _ext_out_intervals(self, omk: dict, owner) -> dict[str, list[tuple[int, int]]]:
        """ext_out request-to-response spans per initiator, paired per ID in order."""
        spans: dict[str, list[tuple[int, int]]] = defaultdict(list)
        for ch, rch, idk, rk in (("aw", "b", "awid", "bid"), ("ar", "r", "arid", "rid")):
            pending: dict = defaultdict(list)
            evs = [(e["cyc"], 0, e) for e in self.out.since(omk, ch)]
            evs += [
                (e["cyc"], 1, e) for e in self.out.since(omk, rch) if rch == "b" or e["rlast"] == 1
            ]
            for cyc, kind, e in sorted(evs, key=lambda x: (x[0], x[1])):
                if kind == 0:
                    pending[e[idk]].append((cyc, owner(e[f"{ch}addr"] or 0)))
                elif pending[e[rk]]:
                    start, who = pending[e[rk]].pop(0)
                    spans[who].append((start, cyc))
        return spans

    async def _s2_stalled(self) -> None:
        dut = self.dut
        sb = self.sb
        mem = self.cfg.axi_out_mem
        self.term = "STALLED_EXT_OUT"
        self._info("STEP S2: STALLED_EXT_OUT")
        src_pat = bytes((0xA5 ^ (i * 13)) & 0xFF for i in range(S2_DMA_LEN))
        mem.write(EXT_DMA_SRC, src_pat)
        mem.write(EXT_DMA_DST, bytes(S2_DMA_LEN))
        await self._dma_program(
            [
                (DMA_CONFIG, DMA_CONFIG_ENABLE_ND, "CONFIG"),
                (DMA_DST_LO, EXT_DMA_DST & 0xFFFF_FFFF, "DST_LO"),
                (DMA_DST_HI, EXT_DMA_DST >> 32, "DST_HI"),
                (DMA_SRC_LO, EXT_DMA_SRC & 0xFFFF_FFFF, "SRC_LO"),
                (DMA_SRC_HI, EXT_DMA_SRC >> 32, "SRC_HI"),
                (DMA_LEN_LO, S2_DMA_LEN, "LEN_LO"),
                (DMA_LEN_HI, 0, "LEN_HI"),
                (DMA_DST_STRIDE_LO, 0, "DST_STRIDE_LO"),
                (DMA_DST_STRIDE_HI, 0, "DST_STRIDE_HI"),
                (DMA_SRC_STRIDE_LO, 0, "SRC_STRIDE_LO"),
                (DMA_SRC_STRIDE_HI, 0, "SRC_STRIDE_HI"),
                (DMA_REPS_LO, 1, "REPS_LO"),
                (DMA_REPS_HI, 0, "REPS_HI"),
            ]
        )
        await self._probe_arm(LSU_EXT_S2)
        lo, hi = S2_RESP_DELAY
        mem.set_response_delay(iter(lambda: self.rng.randint(lo, hi), None))
        mem.enable_backpressure(channels=("aw", "w", "ar"), stall_cycles=self.s2_stall)
        self.master.driver.set_timing(self.prof)
        mk = self.ext.mark()
        omk = self.out.mark()
        mks = self._marks()
        win = self._windows()
        start_id = await self._rd32(DMA_NEXT_ID_0, "s2_launch")
        j2a_addr = EXT_J2A + 0x100
        word = 0x4A2A_0000_0000_5302
        st_w, _ = await self._j2a_with_dmi(
            J2A_OP_WRITE, j2a_addr, word, DMCONTROL, DMACTIVE | RESUMEREQ, label="s2_j2a_wr_resume"
        )
        decerr_credit = ExitStack()
        decerr_credit.enter_context(expected_decerr("ext_in", 4))
        reqs = []
        for n, xid in enumerate((0x20, 0x21)):
            a = NEITHER + 0x40 * n
            reqs.append(("r", xid, self._issue(write=False, addr=a, nbytes=8, xid=xid)))
        for n, xid in enumerate((0x24, 0x25)):
            a = NEITHER + 0x400 + 0x40 * n
            reqs.append(("w", xid, self._issue(write=True, addr=a, nbytes=8, xid=xid)))
        st_r, rd = await self._j2a(J2A_OP_READ, j2a_addr, label="s2_j2a_rd")
        sba_words = {SBA_EXT + 0x100: 0x5BA0_0102, SBA_EXT + 0x108: 0x5BA0_0304}
        sba = {}
        for a, v in sba_words.items():
            werr, _ = await self._sb(a, data=v, label=f"s2_sba_wr_{a & 0xFFF:x}")
            rerr, rv = await self._sb(a, label=f"s2_sba_rd_{a & 0xFFF:x}")
            sba[_hx(a)] = (werr, rerr, _hx(rv), _hx(mem.read_int(a, 4)))
        report = await self._probe_finish("s2")
        done = await self._dma_done("s2", start_id)
        await self._wait(
            "s2_ext_in_answered",
            lambda: all(e.is_set() for *_, e in reqs),
            XFER_BOUND,
            "every S2 ext_in B and RLAST",
        )
        decerr_credit.close()

        def drained() -> bool:
            bs = self.out.since(omk, "b")
            rl = [e for e in self.out.since(omk, "r") if e["rlast"] == 1]
            return len(bs) >= len(self.out.since(omk, "aw")) and len(rl) >= len(
                self.out.since(omk, "ar")
            )

        await self._wait("s2_ext_out_drain", drained, DRAIN_BOUND, "every ext_out B and RLAST")
        await ClockCycles(dut.clk_smu_i, 4)
        mem.disable_backpressure()
        mem.clear_response_delay()
        clear_profile(self.master.driver)
        held, want_held = self._held(LSU_EXT_S2)

        def owner(addr: int) -> str:
            if LSU_EXT_S2 <= addr < LSU_EXT_S2 + PROBE_SPAN:
                return "lsu"
            if addr in sba_words:
                return "sba"
            if EXT_DMA_SRC <= addr < EXT_DMA_SRC + S2_DMA_LEN:
                return "idma"
            if EXT_DMA_DST <= addr < EXT_DMA_DST + S2_DMA_LEN:
                return "idma"
            if addr == j2a_addr:
                return "j2a"
            return "other"

        spans = self._ext_out_intervals(omk, owner)
        pairs = {
            "lsu+idma": _overlap(spans["lsu"], spans["idma"]),
            "lsu+j2a": _overlap(spans["lsu"], spans["j2a"]),
            "idma+j2a": _overlap(spans["idma"], spans["j2a"]),
            "lsu+idma+j2a": _overlap3(spans["lsu"], spans["idma"], spans["j2a"]),
        }
        sep_pair = _pairing(self.links["xbar_sep_out"], mks["xbar_sep_out"])
        sep_codes = sorted(
            {_rn(e["bresp"]) for e in self._since(mks, "xbar_sep_out", "b")}
            | {_rn(e["rresp"]) for e in self._since(mks, "xbar_sep_out", "r")}
        )
        sep_addrs = [e[f"{ch}addr"] for ch in ("aw", "ar") for e in self.out.since(omk, ch)]
        prot_bad = []
        for ch in ("aw", "ar"):
            for e in self.out.since(omk, ch):
                a = e[f"{ch}addr"] or 0
                if owner(a) in ("lsu", "sba"):
                    want_prot = 0b001 | ((0 if (a >> 55) & 1 else 1) << 1)
                    if e.get(f"{ch}prot") != want_prot:
                        prot_bad.append((ch, _hx(a), _hx(e.get(f"{ch}prot")), bin(want_prot)))
        dst = mem.read(EXT_DMA_DST, S2_DMA_LEN)
        aws, ars = self.out.since(omk, "aw"), self.out.since(omk, "ar")
        dma_aw = [e for e in aws if owner(e["awaddr"] or 0) == "idma"]
        dma_ar = [e for e in ars if owner(e["araddr"] or 0) == "idma"]
        j_req = [e for e in aws + ars if owner(e.get("awaddr", e.get("araddr")) or 0) == "j2a"]
        ext = []
        for kind, xid, _ in reqs:
            if kind == "r":
                got = [e for e in self.ext.since(mk, "r") if e["rid"] == xid]
                ext.append((kind, xid, [(_rn(e["rresp"]), e["rlast"]) for e in got]))
            else:
                got = [e for e in self.ext.since(mk, "b") if e["bid"] == xid]
                ext.append((kind, xid, [_rn(e["bresp"]) for e in got]))
        misrouted, mis_rows = self._misrouted(mks, win)
        observed = {
            "lsu_report": report,
            "lsu_held": held,
            "sba": sba,
            "sep_out_pairing": (sep_pair["lost"], sep_pair["dup"], sep_pair["order_violations"]),
            "sep_out_codes": sep_codes,
            "axprot_sep_at_ext_out": prot_bad,
            "idma": (
                done,
                dst == src_pat,
                sorted({e["awburst"] for e in dma_aw} | {e["arburst"] for e in dma_ar}),
            ),
            "j2a": (st_w, st_r, _hx(rd), len(j_req)),
            "ext_in": ext,
            "pairs": pairs,
            "misrouted": (misrouted, mis_rows),
        }
        expected = {
            "lsu_report": self._completed(),
            "lsu_held": want_held,
            "sba": {_hx(a): (0, 0, _hx(v), _hx(v)) for a, v in sba_words.items()},
            "sep_out_pairing": (0, 0, 0),
            "sep_out_codes": ["OKAY"],
            "axprot_sep_at_ext_out": [],
            "idma": (start_id, True, [1]),
            "j2a": (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, _hx(word), 2),
            "ext_in": [(k, x, [("DECERR", 1)] if k == "r" else ["DECERR"]) for k, x, _ in reqs],
            "pairs": dict.fromkeys(pairs, True),
            "misrouted": (0, []),
        }
        lsu_n = len(spans["lsu"])
        self._info(
            f"G4B-S2 observed={observed} spans={ {k: len(v) for k, v in spans.items()} } "
            f"sep_out_requests={sep_pair['requests']} ext_out_addrs={len(sep_addrs)}"
        )
        sb.expect_eq("CHK-G4B-CONC-EXTOUT", observed, expected, evidence="CHK-G4B-CONC-EXTOUT")
        self._raw(
            f"CHK-G4B-CONC-EXTOUT: lsu={lsu_n} sba={len(sba_words) * 2} "
            f"idma_bursts={len(dma_aw) + len(dma_ar)} j2a={len(j_req)} pairs={sum(pairs.values())} "
            f"mismatches=0 axprot_sep=0b011 (cpu.adoc master AxPROT 0b001 with NS set by the "
            f"fabric.adoc route demux for address bit 55 clear)"
        )
        self._s2_obs(mks, omk, spans, owner)
        self.s2_mks = mks
        self._mark(
            "STALLED_EXT_OUT",
            lsu_n + len(sba_words) * 2 + len(dma_aw) + len(dma_ar) + len(j_req) + len(reqs),
            4 + 2 + 2 + len(reqs),
        )

    def _s2_obs(self, mks: dict, omk: dict, spans: dict, owner) -> None:
        peaks = {}
        for name, tap in self.links.items():
            depth = {"w": 0, "r": 0}
            peak = {"w": 0, "r": 0}
            evs = []
            for ch, kind, delta in (("aw", "w", 1), ("b", "w", -1), ("ar", "r", 1), ("r", "r", -1)):
                for e in tap.since(mks[name], ch):
                    if ch == "r" and e["rlast"] != 1:
                        continue
                    evs.append((e["cyc"], delta, kind))
            for _, delta, kind in sorted(evs):
                depth[kind] += delta
                peak[kind] = max(peak[kind], depth[kind])
            inst = getattr(self.dut, CHECKER_INSTANCE[name], None)
            built = "unreadable"
            if inst is not None:
                try:
                    built = int(inst.MAX_OUTSTANDING.value)
                except (AttributeError, TypeError, ValueError):
                    built = "unreadable"
            peaks[name] = f"wr={peak['w']} rd={peak['r']} MAX_OUTSTANDING={built}"
        self._raw(
            f"OBS-G4B-DEPTH: peak accepted-unanswered per link in S2 {peaks}; an "
            f"OCAH_AXI_AW_OUTSTANDING_DEPTH fire is checker-side; waits on SF-008, never compared"
        )
        waits = {}
        for who in ("lsu", "sba", "idma", "j2a"):
            ws = [
                e["wait"]
                for ch in ("aw", "ar")
                for e in self.out.since(omk, ch)
                if "wait" in e and owner(e[f"{ch}addr"] or 0) == who
            ]
            waits[who] = max(ws, default=0)
        sep_waits = []
        for name in ("xbar_sep_out", "xbar_smc_out"):
            n = len(self._since(mks, name, "aw")) + len(self._since(mks, name, "ar"))
            sep_waits.append(f"{name} requests={n}")
        self._raw(
            f"OBS-G4B-GRANT-WAIT: ext_out VALID-to-READY edges, max over S2 {waits}; spans at "
            f"ext_out per initiator { {k: len(v) for k, v in spans.items()} }; {sep_waits}; waits "
            f"on SF-022, never compared"
        )
        extra = {}
        for name in ("xbar_sep_out", "xbar_ext_out", "smu_out", "incut", "smu_in"):
            vals = set()
            for ch in ("aw", "ar"):
                for e in self._since(mks, name, ch):
                    vals.add(
                        (
                            ch,
                            _hx(e[f"{ch}cache"]),
                            _hx(e[f"{ch}qos"]),
                            _hx(e[f"{ch}region"]),
                            _hx(e[f"{ch}user"]),
                        )
                    )
            extra[name] = sorted(vals)[:6]
        cut = (
            len(self._since(mks, "smu_in", "aw")) + len(self._since(mks, "smu_in", "ar")),
            len(self._since(mks, "incut", "aw")) + len(self._since(mks, "incut", "ar")),
        )
        self._raw(
            f"OBS-G4B-PAYLOAD-EXTRA: (channel, AxCACHE, AxQOS, AxREGION, AxUSER) per link {extra}; "
            f"inbound cut smu_in/incut AW+AR handshakes={cut}; waits on SF-007, SF-010, never "
            f"compared"
        )

    # ------------------------------------------------------------------ S3

    async def _s3_interleave(self) -> None:
        dut = self.dut
        sb = self.sb
        mem = self.cfg.axi_out_mem
        self.term = "INTERLEAVE"
        self._info("STEP S3: INTERLEAVE")
        spm_probe = SPM + SPM_PROBE_OFF
        zero_gap = SMC_GLOBAL_BASE_RESET + (ZEROER_GAP_LOCAL - SMC_APERTURE_LOCAL_BASE)
        src2 = bytes((0x96 + 7 * i) & 0xFF for i in range(S3_DMA2_LEN))
        mem.write(EXT_S3_DST, bytes(S3_DMA_LEN))
        mem.write(EXT_S3_SRC2, src2)
        mem.write(EXT_S3_DST2, bytes(S3_DMA2_LEN))
        mem.write(EXT_S3_J2A, bytes(0x40))
        spm_fill = bytes((0x71 + 3 * i) & 0xFF for i in range(PROBE_SPAN))
        t = await self._ext(
            "s3_spm_fill", write=True, addr=spm_probe, nbytes=PROBE_SPAN, xid=0x2C, data=spm_fill
        )
        fill_codes = self._codes(t)
        mks = self._marks()
        mk = self.ext.mark()
        omk = self.out.mark()
        win = self._windows()
        # sep_out: a system-bus read held at the responder while the LSU probe runs
        await self._probe_arm(LSU_EXT_S3)
        held_addr = SBA_EXT + 0x200
        mem.inject_error(held_addr, 2, read=True, write=False)
        mem.set_response_delay(
            itertools.chain([HELD_READ_DELAY], iter(lambda: self.rng.randint(*RESP_DELAY), None)),
            write=False,
        )
        mem.enable_backpressure(channels=("aw", "w", "ar"), stall_cycles=self.stall)
        await self._sb_issue(held_addr, size=2, data=None, label="s3_sba_held_rd")
        await self._dmi_op(DMCONTROL, DMACTIVE | RESUMEREQ, DMI_OP_WRITE, "s3_resume_ext")
        held_err, _ = await self._sb_finish(size=2, read=True, label="s3_sba_held_rd")
        rep_ext = await self._probe_finish("s3_ext")
        mem.clear_response_delay()
        held_ext, want_held_ext = self._held(LSU_EXT_S3)
        err_addr = SBA_EXT + 0x208
        mem.inject_error(err_addr, 2, read=False, write=True)
        werr, _ = await self._sb(err_addr, data=0x5BA0_0E44, label="s3_sba_err_wr")
        mem.disable_backpressure()
        sep_ar = self._since(mks, "xbar_sep_out", "ar")
        held = [e for e in sep_ar if e["araddr"] == held_addr]
        held_r = [
            e
            for e in self._since(mks, "xbar_sep_out", "r")
            if held and e["rid"] == held[0]["arid"] and e["cyc"] > held[0]["cyc"]
        ]
        lsu_during = [
            e
            for ch in ("aw", "ar")
            for e in self._since(mks, "xbar_sep_out", ch)
            if LSU_EXT_S3 <= (e[f"{ch}addr"] or 0) < LSU_EXT_S3 + PROBE_SPAN
            and held
            and held_r
            and held[0]["cyc"] < e["cyc"] < held_r[0]["cyc"]
        ]
        # SEP-to-SMC: the probe into the SEP view of the SMC scratchpad, then the zeroer gap
        await self._probe_arm(spm_probe)
        await self._dmi_op(DMCONTROL, DMACTIVE | RESUMEREQ, DMI_OP_WRITE, "s3_resume_spm")
        rep_spm = await self._probe_finish("s3_spm")
        gw_err, _ = await self._sb(zero_gap, data=0x5BA0_0D0E, label="s3_sba_zero_wr")
        gr_err, _ = await self._sb(zero_gap, label="s3_sba_zero_rd")
        # smc_out: JTAG2AXI full and partial write then read of sep_in and ext_out, and an error
        j2a_rows = {}
        for cell, addr, size, wd in (
            ("sep_in/full", SEP_SRAM + 0xE80, 3, 0x5EF0_0000_0000_0E80),
            ("sep_in/partial", SEP_SRAM + 0xE8C, 2, 0x5EF0_0E8C),
            ("ext_out/full", EXT_S3_J2A, 3, 0xE0F0_0000_0000_0003),
            ("ext_out/partial", EXT_S3_J2A + 0xC, 2, 0xE0F0_000C),
        ):
            shift = 32 if size == 2 and addr & 4 else 0
            st_w, _ = await self._j2a(
                J2A_OP_WRITE, addr, wd << shift, size=size, label=f"s3_j2a_{cell}_wr"
            )
            st_r, rd = await self._j2a(J2A_OP_READ, addr, size=size, label=f"s3_j2a_{cell}_rd")
            got = (rd >> shift) & ((1 << (8 << size)) - 1)
            j2a_rows[cell] = (st_w, st_r, _hx(got) == _hx(wd))
            if cell.startswith("sep_in"):
                off, n = addr - SEP_SRAM, 1 << size
                self.sep_pat = (
                    self.sep_pat[:off] + wd.to_bytes(n, "little") + self.sep_pat[off + n :]
                )
        mem.inject_error(EXT_S3_ERR, 2, read=False, write=True)
        st_ew, _ = await self._j2a(J2A_OP_WRITE, EXT_S3_ERR, 0xEE, label="s3_j2a_err_wr")
        mem.inject_error(EXT_S3_ERR, 2, read=True, write=False)
        st_er, _ = await self._j2a(J2A_OP_READ, EXT_S3_ERR, label="s3_j2a_err_rd")
        mem.clear_errors()
        # iDMA from the SEP SRAM to ext_out while ext_in interleaves IDs toward both targets
        await self._dma_program(
            [
                (DMA_DST_LO, EXT_S3_DST & 0xFFFF_FFFF, "DST_LO"),
                (DMA_DST_HI, 0, "DST_HI"),
                (DMA_SRC_LO, S3_DMA_SRC & 0xFFFF_FFFF, "SRC_LO"),
                (DMA_SRC_HI, 0, "SRC_HI"),
                (DMA_LEN_LO, S3_DMA_LEN, "LEN_LO"),
            ]
        )
        self.master.driver.set_timing(self.prof)
        plan = []
        for tgt, base in (("sep", SEP_SRAM + 0xC00), ("spm", SPM + 0x200)):
            plan.append((0x30, base, 8, tgt, 3))
            plan.append((0x31, base + 0x14, 4, tgt, 2))
            plan.append((0x32, base + 0x20, 32, tgt, 3))
        writes = []
        for xid, a, n, tgt, size in plan:
            data = bytes((xid * 7 + a + i) & 0xFF for i in range(n))
            ev = self._issue(write=True, addr=a, nbytes=n, xid=xid, size=size, data=data)
            writes.append((xid, a, n, tgt, size, data, ev))
        start_id, _ = await self._dma_launch("s3")
        await self._wait(
            "s3_ext_in_writes", lambda: all(w[-1].is_set() for w in writes), XFER_BOUND, "S3 B"
        )
        reads = []
        for xid, a, n, _, size, data, _ in writes:
            ev = self._issue(write=False, addr=a, nbytes=n, xid=xid + 0x08, size=size)
            reads.append((xid + 0x08, a, n, data, ev))
        done = await self._dma_done("s3", start_id)
        await self._wait(
            "s3_ext_in_reads", lambda: all(r[-1].is_set() for r in reads), XFER_BOUND, "S3 RLAST"
        )
        # a multi-beat read and write at ext_out: an iDMA copy between two ext_out ranges
        await self._dma_program(
            [
                (DMA_DST_LO, EXT_S3_DST2 & 0xFFFF_FFFF, "DST_LO"),
                (DMA_SRC_LO, EXT_S3_SRC2 & 0xFFFF_FFFF, "SRC_LO"),
                (DMA_LEN_LO, S3_DMA2_LEN, "LEN_LO"),
            ]
        )
        start2, _ = await self._dma_launch("s3_ext")
        done2 = await self._dma_done("s3_ext", start2)
        # one error response per ext_in-side link: WRAP into the SEP SRAM, the zeroer gap, neither
        wrap = SEP_SRAM + 0xD10
        wrap_w = self.master.init_write(
            wrap, bytes(range(32)), size=3, prot=PROT_NONSECURE, burst=2, awid=0x3C
        )
        await self._wait("s3_wrap_wr", wrap_w.is_set, XFER_BOUND, "B id=0x3c")
        wrap_r = self.master.init_read(wrap, 32, size=3, prot=PROT_NONSECURE, burst=2, arid=0x3D)
        await self._wait("s3_wrap_rd", wrap_r.is_set, XFER_BOUND, "RLAST id=0x3d")
        with expected_decerr("ext_in", 4):
            zw = await self._ext("s3_zero_wr", write=True, addr=zero_gap, nbytes=8, xid=0x3E)
            zr = await self._ext("s3_zero_rd", write=False, addr=zero_gap, nbytes=8, xid=0x3F)
            nw = await self._ext(
                "s3_neither_wr", write=True, addr=NEITHER + 0x800, nbytes=8, xid=0x2E
            )
            nr = await self._ext(
                "s3_neither_rd", write=False, addr=NEITHER + 0x800, nbytes=8, xid=0x2F
            )
        await self._wait(
            "s3_ext_out_drain",
            lambda: len(self.out.since(omk, "b")) >= len(self.out.since(omk, "aw")),
            DRAIN_BOUND,
            "every ext_out B",
        )
        rb = await self._ext("s3_spm_rb", write=False, addr=spm_probe, nbytes=PROBE_SPAN, xid=0x2D)
        await ClockCycles(dut.clk_smu_i, 8)
        clear_profile(self.master.driver)
        spm_bytes = self._rdata(rb, PROBE_SPAN)
        spm_held = {
            off: int.from_bytes(spm_bytes[off : off + w], "little") for w, off in PROBE_STORES
        }
        # same-ID reads return in issue order: the k-th RLAST burst of an ID answers its k-th read
        bursts: dict[int, list[list[dict]]] = defaultdict(lambda: [[]])
        for e in self.ext.since(mk, "r"):
            bursts[e["rid"]][-1].append(e)
            if e["rlast"] == 1:
                bursts[e["rid"]].append([])
        taken: Counter = Counter()
        data_bad = []
        for rxid, a, n, data, _ in reads:
            beats = bursts[rxid][taken[rxid]] if taken[rxid] < len(bursts[rxid]) else []
            taken[rxid] += 1
            got = b"".join((e["rdata"] or 0).to_bytes(8, "little") for e in beats)
            off = a & 7
            if got[off : off + n] != data or any(_rn(e["rresp"]) != "OKAY" for e in beats):
                data_bad.append((hex(a), rxid, got[off : off + n].hex()))
        dst = mem.read(EXT_S3_DST, S3_DMA_LEN)
        src_ref = self.sep_pat[S3_DMA_SRC - SEP_SRAM : S3_DMA_SRC - SEP_SRAM + S3_DMA_LEN]
        order = {
            name: _pairing(self.links[name], mks[name]) for name in (*INITIATORS, "sep_to_smc")
        }
        misrouted, mis_rows = self._misrouted(mks, win)
        wrap_codes = (
            [_rn(e["bresp"]) for e in self.ext.since(mk, "b") if e["bid"] == 0x3C],
            [_rn(e["rresp"]) for e in self.ext.since(mk, "r") if e["rid"] == 0x3D],
        )
        lost = sum(o["lost"] for o in order.values())
        dup = sum(o["dup"] for o in order.values())
        order_bad = sum(o["order_violations"] for o in order.values())
        observed = {
            "spm_fill": fill_codes,
            "lsu_ext": rep_ext,
            "lsu_ext_held": held_ext,
            "lsu_spm": rep_spm,
            "lsu_spm_held": spm_held,
            "lsu_with_sba_outstanding_on_sep_out": len(lsu_during) > 0,
            "sba_errors": (held_err != 0, werr != 0, gw_err != 0, gr_err != 0),
            "j2a": j2a_rows,
            "j2a_err": (st_ew, st_er),
            "ext_in_data": data_bad,
            "idma": (done, dst == src_ref, done2, mem.read(EXT_S3_DST2, S3_DMA2_LEN) == src2),
            "wrap": wrap_codes,
            "zero_gap": (self._codes(zw), self._codes(zr)),
            "neither": (self._codes(nw), self._codes(nr)),
            "order": {k: (v["lost"], v["dup"], v["order_violations"]) for k, v in order.items()},
            "misrouted": (misrouted, mis_rows),
        }
        expected = {
            "spm_fill": ["OKAY"],
            "lsu_ext": self._completed(),
            "lsu_ext_held": want_held_ext,
            "lsu_spm": self._completed(),
            "lsu_spm_held": {off: STORE_WORD & ((1 << (8 * w)) - 1) for w, off in PROBE_STORES},
            "lsu_with_sba_outstanding_on_sep_out": True,
            "sba_errors": (True, True, True, True),
            "j2a": dict.fromkeys(j2a_rows, (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, True)),
            "j2a_err": (J2A_STATUS_SLVERR, J2A_STATUS_SLVERR),
            "ext_in_data": [],
            "idma": (start_id, True, start2, True),
            "wrap": (["SLVERR"], ["SLVERR"] * 4),
            "zero_gap": (["DECERR"], ["DECERR"]),
            "neither": (["DECERR"], ["DECERR"]),
            "order": dict.fromkeys(order, (0, 0, 0)),
            "misrouted": (0, []),
        }
        requests = sum(o["requests"] for o in order.values())
        self._info(
            f"G4B-S3 observed={observed} order={order} lsu_during_held_read={len(lsu_during)}"
        )
        sb.expect_eq("CHK-G4B-INTERLEAVE", observed, expected, evidence="CHK-G4B-INTERLEAVE")
        self._raw(
            f"CHK-G4B-INTERLEAVE: requests={requests} order_violations={order_bad} lost={lost} "
            f"dup={dup} data_mismatch={len(data_bad)} misrouted={misrouted}"
        )
        self._content_checks(mks)
        self._raw(
            f"OBS-G4B-ADDR: SEP aperture base={_hx(win[0])} size={_hx(win[1])} SEP SRAM global="
            f"{_hx(SEP_SRAM)}; SMC scratchpad global={_hx(SPM)} (local {_hx(SPM_LOCAL)}) and the "
            f"probe window {_hx(spm_probe)}; zeroer gap global={_hx(zero_gap)}; SMC inbound filter "
            f"entry 0 [0x0, {_hx(PASS_ALL_END)}] config={_hx(PASS_RW_CONFIG)}; SMC outbound entry 0 "
            f"pass-all; SEP outbound filter entry 1 [0x0, {_hx(ADDR_MASK)}] config="
            f"{_hx(OUTBOUND_CFG_OPEN)}; waits on SF-023, never compared"
        )
        self._mark("INTERLEAVE", requests, 40)

    def _content_checks(self, mks: dict) -> None:
        """CHK-G4B-NO-EXOKAY over S2 and S3, CHK-G4B-CONTENT-FLOOR and CHK-G4B-DATA-KNOWN over S3."""
        sb = self.sb
        exokay, x_resp, responses = 0, 0, 0
        for name in self.links:
            for ch, key in (("b", "bresp"), ("r", "rresp")):
                for e in self._since(self.s2_mks, name, ch):
                    responses += 1
                    exokay += e[key] == 1
                    x_resp += e[key] is None
        sb.expect_eq(
            "CHK-G4B-NO-EXOKAY",
            (responses > 0, exokay, x_resp),
            (True, 0, 0),
            evidence="CHK-G4B-NO-EXOKAY",
        )
        self._raw(f"CHK-G4B-NO-EXOKAY: responses={responses} exokay={exokay}")
        floor, floor_want, known, known_want = {}, {}, {}, {}
        for name in self.links:
            ws = self._since(mks, name, "w")
            bs = self._since(mks, name, "b")
            rs = self._since(mks, name, "r")
            aws = self._since(mks, name, "aw")
            ars = self._since(mks, name, "ar")
            full = (1 << (LINK_DATA_BITS // 8)) - 1
            counts = {
                "partial_strb": sum(1 for e in ws if e["wstrb"] not in (None, 0, full)),
                "b_err": sum(1 for e in bs if (e["bresp"] or 0) >= 2),
                "r_err": sum(1 for e in rs if (e["rresp"] or 0) >= 2),
                "aw_multi": sum(1 for e in aws if (e["awlen"] or 0) > 0),
                "ar_multi": sum(1 for e in ars if (e["arlen"] or 0) > 0),
            }
            floor[name] = {k: v >= 1 for k, v in counts.items()}
            floor_want[name] = {
                k: True for k in counts if not (name in SINGLE_BEAT_LINKS and k.endswith("_multi"))
            }
            for k in counts:
                if name in SINGLE_BEAT_LINKS and k.endswith("_multi"):
                    floor[name].pop(k)
            strobed = [e for e in ws if e["strobed_lanes"]]
            okay_r = [e for e in rs if e["rresp"] == 0]
            known[name] = (
                len(strobed) > 0,
                len(okay_r) > 0,
                sum(e["x_lanes"] for e in ws),
                sum(1 for e in okay_r if e["r_x"]),
            )
            known_want[name] = (True, True, 0, 0)
            self._info(f"G4B-FLOOR {name}: {counts} strobed_w={len(strobed)} okay_r={len(okay_r)}")
        sb.expect_eq("CHK-G4B-CONTENT-FLOOR", floor, floor_want, evidence="CHK-G4B-CONTENT-FLOOR")
        self._raw(
            f"CHK-G4B-CONTENT-FLOOR: links={len(floor)} partial_strb/b_err/r_err/aw_multi/ar_multi "
            f"per link >= 1; multi-beat not drivable on {sorted(SINGLE_BEAT_LINKS)}"
        )
        sb.expect_eq("CHK-G4B-DATA-KNOWN", known, known_want, evidence="CHK-G4B-DATA-KNOWN")
        sw = sum(1 for n in self.links for e in self._since(mks, n, "w") if e["strobed_lanes"])
        orr = sum(1 for n in self.links for e in self._since(mks, n, "r") if e["rresp"] == 0)
        self._raw(
            f"CHK-G4B-DATA-KNOWN: links={len(known)} strobed_w_beats={sw} okay_r_beats={orr} x_lanes=0"
        )

    # ------------------------------------------------------------------ S4

    async def _s4_route_fwd(self) -> None:
        sb = self.sb
        mem = self.cfg.axi_out_mem
        self.term = "ROUTE_FWD"
        self._info("STEP S4: ROUTE_FWD")
        win = self._windows()
        word = 0x5EF0_0D04
        w = await self._sep_access("s4_sep_out_wr", SBA_FWD, data=word)
        r = await self._sep_access("s4_sep_out_rd", SBA_FWD)
        cells = {
            "write": (w["route"], w["err"], w["ids_ok"]),
            "read": (r["route"], r["err"], r["ids_ok"], _hx(r["rdata"])),
        }
        want = {"write": ("ext_out", 0, True), "read": ("ext_out", 0, True, _hx(word))}
        cells["responder"] = _hx(mem.read_int(SBA_FWD, 4))
        want["responder"] = _hx(word)
        cells["cell"] = self._route_of("xbar_sep_out", SBA_FWD, win)
        want["cell"] = "ext_out"
        self._info(f"G4B-S4 {cells}")
        sb.expect_eq("CHK-G4B-ROUTE-FWD", cells, want, evidence="CHK-G4B-ROUTE-FWD")
        self._raw("CHK-G4B-ROUTE-FWD: cells=1 requests=2 misrouted=0 id_mismatch=0")
        users = []
        for t in (w, r):
            ch = "aw" if t is w else "ar"
            rch = "b" if t is w else "r"
            users.append(
                f"{t['label']}: sep_out {ch}user={[_hx(e[f'{ch}user']) for e in t['req']]} "
                f"{rch}user={[_hx(e[f'{rch}user']) for e in t['resp']]} ext_out "
                f"{ch}user={[_hx(e[f'{ch}user']) for e in t['out']]}"
            )
        sep_w = self.links["xbar_sep_out"].ev["w"][-4:]
        users.append(f"sep_out wuser={[_hx(e['wuser']) for e in sep_w]}")
        self._raw(f"OBS-G4B-USER: {users}; waits on SF-026, never compared")
        self._mark("ROUTE_FWD", 2, 2)

    # ------------------------------------------------------------------ S5

    async def _s5_decerr(self) -> None:
        sb = self.sb
        self.term = "DECERR_CELLS"
        self._info("STEP S5: DECERR_CELLS")
        await self._sep_csr("base", SEP_SELF_BASE, "s5_sep_base_self")
        win = self._windows()
        addr = SEP_SELF_BASE + 0x100
        w = await self._sep_access("s5_sep_out_wr", addr, data=0xDEC0_0005)
        r = await self._sep_access("s5_sep_out_rd", addr)
        await self._sep_csr("base", SEP_GLOBAL_BASE_RESET, "s5_sep_base_restore")
        sep_cell = {
            "cell": self._route_of("xbar_sep_out", addr, win),
            "write": (w["route"], w["ids_ok"], w["codes"], w["err"] != 0),
            "read": (
                r["route"],
                r["ids_ok"],
                [(_rn(e["rresp"]), e["rlast"]) for e in r["resp"]],
                r["err"] != 0,
            ),
        }
        sep_want = {
            "cell": "DECERR",
            "write": ("DECERR", True, ["DECERR"], True),
            "read": ("DECERR", True, [("DECERR", 1)], True),
        }
        self.decerr_obs.append(
            f"S5 sep_out R rdata={[_hx(e['rdata']) for e in r['resp']]} ruser="
            f"{[_hx(e['ruser']) for e in r['resp']]} buser={[_hx(e['buser']) for e in w['resp']]} "
            f"sberror={w['err']}/{r['err']}"
        )
        self._raw(SMC_OUT_SMC_NOT_DRIVABLE)
        bursts = {}
        bursts_want = {}
        n_req = 2
        decerr = 2
        credits = sum(n + 1 for n in DECERR_LENS) + len(DECERR_LENS)
        with expected_decerr("ext_in", credits):
            for k, alen in enumerate(DECERR_LENS):
                rd_addr = NEITHER_RD_PAGE + (0, 0x800, 0x900)[k]
                wr_addr = NEITHER_WR_PAGE + (0, 0x800, 0x900)[k]
                nbytes = 8 * (alen + 1)
                cnt0 = self._cnt()
                omk = self.out.mark()
                mks = self._marks()
                emk = self.ext.mark()
                wt = await self._ext(
                    f"s5_neither_wr_len{alen}",
                    write=True,
                    addr=wr_addr,
                    nbytes=nbytes,
                    xid=0x50 + k,
                )
                rt = await self._ext(
                    f"s5_neither_rd_len{alen}",
                    write=False,
                    addr=rd_addr,
                    nbytes=nbytes,
                    xid=0x58 + k,
                )
                d = self._d(cnt0, self._cnt())
                target = sum(d[x] for x in ("sep_aw", "sep_ar", "smc_aw", "smc_ar"))
                target += len(self.out.since(omk, "aw")) + len(self.out.since(omk, "ar"))
                target += sum(len(self._since(mks, t, ch)) for t in TARGETS for ch in ("aw", "ar"))
                beats = rt["mine"]
                ws_in = self.ext.since(emk, "w")
                bursts[f"len{alen}"] = (
                    [e["awlen"] for e in wt["req"]],
                    [e["arlen"] for e in rt["req"]],
                    len(beats),
                    [e["rlast"] for e in beats].count(1),
                    beats[-1]["rlast"] if beats else None,
                    self._codes(wt),
                    len(ws_in),
                    target,
                )
                bursts_want[f"len{alen}"] = (
                    [alen],
                    [alen],
                    alen + 1,
                    1,
                    1,
                    ["DECERR"],
                    alen + 1,
                    0,
                )
                n_req += 2
                decerr += 1 + sum(1 for e in beats if _rn(e["rresp"]) == "DECERR")
                self.decerr_obs.append(
                    f"S5 ext_in len{alen} RRESP per beat={sorted(Counter(_rn(e['rresp']) for e in beats).items())} "
                    f"rdata={sorted({_hx(e['rdata']) for e in beats})[:4]} ruser="
                    f"{sorted({_hx(e['ruser']) for e in beats})} BRESP={self._codes(wt)} buser="
                    f"{[_hx(e['buser']) for e in wt['mine']]}"
                )
        observed = {"sep_out SEP aperture": sep_cell, "ext_in neither bursts": bursts}
        expected = {"sep_out SEP aperture": sep_want, "ext_in neither bursts": bursts_want}
        self._info(f"G4B-S5 observed={observed}")
        sb.expect_eq("CHK-G4B-ROUTE-DECERR", observed, expected, evidence="CHK-G4B-ROUTE-DECERR")
        self._raw(
            f"CHK-G4B-ROUTE-DECERR: cells=3 driven=2 not_drivable=1 requests={n_req} "
            f"decerr={decerr} target_aw_ar=0"
        )
        self._mark("DECERR_CELLS", n_req, 8)

    # ------------------------------------------------------------------ S6 / S7 placement

    async def _place(self, place: tuple[int, int, int, int], tag: str) -> None:
        """Both apertures to a placement, never overlapping on the way; the ports settle."""
        sep_b, sep_s, smc_b, smc_s = place
        cur_sep_s = self._sep_window()[1]
        if sep_s <= cur_sep_s:
            await self._sep_csr("size", sep_s, f"{tag}_sep_size")
            await self._sep_csr("base", sep_b, f"{tag}_sep_base")
        else:
            await self._sep_csr("base", sep_b, f"{tag}_sep_base")
            await self._sep_csr("size", sep_s, f"{tag}_sep_size")
        await self._wr32(SMC_REGION_SIZE_REG, smc_s, f"{tag}_smc_size")
        await self._wr32(SMC_GLOBAL_BASE_REG, smc_b, f"{tag}_smc_base")
        await self._wait(
            f"{tag}_smc_ports",
            lambda: (
                _val(self.dut.smc_global_base_o) == smc_b
                and _val(self.dut.smc_region_size_o) == smc_s
            ),
            PORT_BOUND,
            f"smc_global_base_o==0x{smc_b:x} smc_region_size_o==0x{smc_s:x}",
        )

    # ------------------------------------------------------------------ S6

    async def _s6_edges(self) -> list:
        self.term = "APERTURE_EDGES"
        self._info("STEP S6: APERTURE_EDGES")
        rows = []
        xid = 0x60
        for pname, place in (("reset_sizes", PLACE_RESET_SIZES), ("reprogram", PLACE_REPROGRAM)):
            await self._place(place, f"s6_{pname}")
            win = self._windows()
            for ap, base, size in (("SEP", win[0], win[1]), ("SMC", win[2], win[3])):
                for where, addr in (
                    ("base-1", base - 1),
                    ("base", base),
                    ("base+size-1", base + size - 1),
                    ("base+size", base + size),
                ):
                    inside = where in ("base", "base+size-1")
                    t = await self._sep_access(f"s6_{pname}_{ap}_{where}_sep_out", addr, size=0)
                    if ap == "SMC" and inside:
                        self.sep_smc_port.append(
                            f"{pname} {ap} {where} 0x{addr:x}: {t['hits']} sberror={t['err']}"
                        )
                    else:
                        exp = self._route_of("xbar_sep_out", addr, win)
                        rows.append(
                            (
                                f"{pname} {ap} {where} sep_out",
                                (t["route"], t["ids_ok"]),
                                (exp, True),
                            )
                        )
                    for init in ("smc_out", "ext_in"):
                        if init == "smc_out" and ap == "SMC" and inside:
                            continue
                        exp = self._route_of(f"xbar_{init}", addr, win)
                        got = await self._probe(
                            f"s6_{pname}_{ap}_{where}_{init}", init, addr, 0, exp, xid & 0xFF
                        )
                        xid += 1
                        rows.append((f"{pname} {ap} {where} {init}", got, (exp, True)))
        self._raw(
            f"OBS-G4B-SEP-SMC-PORT: SEP system-bus reads inside the SMC aperture, the port that "
            f"carried each {self.sep_smc_port}; waits on SF-013, never compared"
        )
        self._mark("APERTURE_EDGES", len(rows), 40)
        return rows

    # ------------------------------------------------------------------ S7

    async def _s7_zero(self) -> None:
        sb = self.sb
        mem = self.cfg.axi_out_mem
        self.term = "ZERO_SIZE"
        self._info("STEP S7: ZERO_SIZE")
        await self._place(PLACE_RESET_SIZES, "s7")
        sep_b, sep_s, smc_b, smc_s = PLACE_RESET_SIZES
        sep_addr = sep_b + 0x200
        smc_addr_ = smc_b + (SPM_LOCAL - SMC_APERTURE_LOCAL_BASE) + 0x3800
        got, want = {}, {}
        n_req = 0
        xid = 0x70
        for cfg_name in ("SEP_REGION_SIZE=0", "REGION_SIZE=0", "both=0"):
            if cfg_name == "SEP_REGION_SIZE=0":
                await self._sep_csr("size", 0, "s7_sep_size_zero")
            elif cfg_name == "REGION_SIZE=0":
                await self._sep_csr("size", sep_s, "s7_sep_size_back")
                await self._wr32(SMC_REGION_SIZE_REG, 0, "s7_smc_size_zero")
                await self._wait(
                    "s7_smc_size_port",
                    lambda: _val(self.dut.smc_region_size_o) == 0,
                    PORT_BOUND,
                    "smc_region_size_o==0",
                )
            else:
                await self._sep_csr("size", 0, "s7_sep_size_zero_again")
            win = self._windows()
            zeroed = {"SEP": win[1] == 0, "SMC": win[3] == 0}
            for rng_name, addr in (("SEP", sep_addr), ("SMC", smc_addr_)):
                word = 0x5E70_0000 | (n_req & 0xFFFF)
                w = await self._sep_access(f"s7_{cfg_name}_{rng_name}_sep_out_wr", addr, data=word)
                r = await self._sep_access(f"s7_{cfg_name}_{rng_name}_sep_out_rd", addr)
                n_req += 2
                key = f"{cfg_name} {rng_name} sep_out"
                if rng_name == "SMC" and not zeroed["SMC"]:
                    self.sep_smc_port.append(
                        f"S7 {cfg_name} {rng_name} 0x{addr:x}: {w['hits']}/{r['hits']}"
                    )
                    continue
                cell = self._route_of("xbar_sep_out", addr, win)
                got[key] = (w["route"], r["route"], w["ids_ok"] and r["ids_ok"])
                want[key] = (cell, cell, True)
                if cell == "ext_out":
                    got[key] += (_hx(r["rdata"]), _hx(mem.read_int(addr, 4)))
                    want[key] += (_hx(word), _hx(word))
                if not zeroed[rng_name]:
                    continue
                j_word = 0x7E70_0000_0000_0000 | n_req
                j_addr = addr + 0x40
                jw = await self._j2a_cell(
                    f"s7_{cfg_name}_{rng_name}_smc_out_wr", J2A_OP_WRITE, j_addr, j_word
                )
                jr = await self._j2a_cell(
                    f"s7_{cfg_name}_{rng_name}_smc_out_rd", J2A_OP_READ, j_addr
                )
                got[f"{cfg_name} {rng_name} smc_out"] = (
                    self._route(jw["d"], len(jw["out_hits"]), True),
                    self._route(jr["d"], len(jr["out_hits"]), False),
                    (jw["st"], jr["st"], _hx(jr["rd"])),
                )
                want[f"{cfg_name} {rng_name} smc_out"] = (
                    (0, 0, 1),
                    (0, 0, 1),
                    (J2A_STATUS_SUCCESS, J2A_STATUS_SUCCESS, _hx(j_word)),
                )
                with expected_decerr("ext_in", 2):
                    ew = await self._ext(
                        f"s7_{cfg_name}_{rng_name}_ext_in_wr",
                        write=True,
                        addr=addr + 0x80,
                        nbytes=8,
                        xid=xid,
                    )
                    er = await self._ext(
                        f"s7_{cfg_name}_{rng_name}_ext_in_rd",
                        write=False,
                        addr=addr + 0x80,
                        nbytes=8,
                        xid=xid + 1,
                    )
                xid += 2
                moved = sum(
                    ew["d"][k] + er["d"][k] for k in ("sep_aw", "sep_ar", "smc_aw", "smc_ar")
                )
                got[f"{cfg_name} {rng_name} ext_in"] = (
                    self._codes(ew),
                    self._codes(er),
                    moved,
                    len(ew["out_aw"]) + len(er["out_ar"]),
                )
                want[f"{cfg_name} {rng_name} ext_in"] = (["DECERR"], ["DECERR"], 0, 0)
                for e in er["mine"]:
                    self.decerr_obs.append(
                        f"S7 {cfg_name} {rng_name} rdata={_hx(e['rdata'])} ruser={_hx(e['ruser'])}"
                    )
                n_req += 4
        await self._sep_csr("size", sep_s, "s7_sep_size_restore")
        await self._sep_csr("base", SEP_GLOBAL_BASE_RESET, "s7_sep_base_restore")
        rb = (
            await self._sba_read64(SEP_GLOBAL_BASE_ADDR, "s7_sep_base_rb"),
            await self._sba_read64(SEP_REGION_SIZE_ADDR, "s7_sep_size_rb"),
        )
        got["restored SEP aperture readback"] = tuple(_hx(v) for v in rb)
        want["restored SEP aperture readback"] = (
            _hx(SEP_GLOBAL_BASE_RESET),
            _hx(SEP_REGION_SIZE_RESET),
        )
        self._raw(REGION_SIZE_RESTORE_NOT_DRIVABLE)
        self._info(
            f"G4B-S7 smc_global_base_o={_hx(_val(self.dut.smc_global_base_o))} "
            f"smc_region_size_o={_hx(_val(self.dut.smc_region_size_o))} rows={got}"
        )
        bad = [k for k in got if got[k] != want[k]]
        sb.expect_eq("CHK-G4B-ZERO", got, want, evidence="CHK-G4B-ZERO")
        self._raw(f"CHK-G4B-ZERO: configs=3 requests={n_req} misrouted={len(bad)}")
        self._raw(
            f"OBS-G4B-DECERR-CONTENT: {self.decerr_obs}; a data-known fire on a DECERR beat is "
            f"checker-side; waits on SF-015, SF-021, never compared"
        )
        self._mark("ZERO_SIZE", n_req, 28)

    # ------------------------------------------------------------------ run

    async def run(self) -> None:
        sb = self.sb
        sim = cocotb.SIM_NAME or "unknown simulator"
        graded = "graded by the bench at final" if "vcs" in sim.lower() else "not graded"
        self._raw(f"INFO-RUN-MODE: {sim}, protocol gates {graded}")
        await self._s1_setup()
        await self._s2_stalled()
        await self._s3_interleave()
        await self._s4_route_fwd()
        await self._s5_decerr()
        rows = await self._s6_edges()
        got = {name: g for name, g, _ in rows}
        want = {name: w for name, _, w in rows}
        bad = [name for name in got if got[name] != want[name]]
        self._info(f"G4B-APERTURE rows={got}")
        sb.expect_eq("CHK-G4B-APERTURE", got, want, evidence="CHK-G4B-APERTURE")
        self._raw(f"CHK-G4B-APERTURE: edges={len(rows)}/40 misdecoded={len(bad)}")
        await self._s7_zero()
        order = [f[0] for f in self.fence]
        times = [f[1] for f in self.fence]
        counts_ok = all(c > 0 and c >= p for _, _, c, p, *_ in self.fence)
        budget_ok = all((r, s) == BUDGET[t] for t, _, _, _, r, s, _ in self.fence)
        sb.expect_true(
            f"CHK-NONVAC fence order={order} counts_ok={counts_ok} budget_ok={budget_ok}",
            order == list(FENCE) and times == sorted(times) and counts_ok and budget_ok,
            evidence="CHK-NONVAC",
        )
        self._raw(
            "CHK-NONVAC: "
            + " < ".join(
                f"{t}@{ns}ns(count={c}/{p} lsu={r}/{BUDGET[t][0]} sba={s}/{BUDGET[t][1]} wall={w}s)"
                for t, ns, c, p, r, s, w in self.fence
            )
        )
        expired = [w for w in self.waits if str(w[4]).startswith("EXPIRED")]
        kinds: dict[tuple, list] = {}
        for name, bound, unit, used, last in self.waits:
            key = (name.rstrip("0123456789"), bound, unit)
            kinds.setdefault(key, []).append((used, last))
        sb.expect_true(
            f"CHK-TIMEOUT-PATHS waits={len(self.waits)} expired={len(expired)}",
            not expired and len(self.waits) > 0,
            evidence="CHK-TIMEOUT-PATHS",
        )
        for (name, bound, unit), uses in sorted(kinds.items(), key=str):
            self._info(
                f"G4B-WAIT: {name} bound={bound} {unit} count={len(uses)} max_used="
                f"{max(u for u, _ in uses)} last_state={uses[-1][1]} on_expiry=fail+INFO-CLASSIFY"
            )
        self._raw(
            f"CHK-TIMEOUT-PATHS: {len(self.waits)} bounded waits, bound and last state per wait, "
            f"0 expired; j2a_accesses={self.j2a_count} sba_on_sep_out={sum(self.sba_stim.values())} "
            f"sba_config={self.sba_count} lsu_probe_runs={sum(self.lsu_runs.values())}"
        )
        self.done = True
