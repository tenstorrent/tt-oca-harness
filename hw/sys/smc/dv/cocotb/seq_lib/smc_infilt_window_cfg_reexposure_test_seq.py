# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The inbound filter window over its own control aperture and the base-config block, from SYS_IN.

Spec sources: filter_ctrl.rdl (FILTER_CONFIG fields, locked steering, START_ADDR/END_ADDR
granule and write-back, reset values); fabric.adoc inbound filtering (lowest-hit priority,
BLOCK_BY_DEFAULT, DECERR responder); smc_base_config register descriptions (GLOBAL_BASE,
LOCAL_BASE, REGION_SIZE, CLOCK_GATE_CONTROL, hang-detector threshold); memmap.adoc (read-only
fields, bits outside every field, gated peripheral windows); clk_rst.adoc peripheral access
gates; the AXI rules transcribed in the ocah_axi_sva header.

Every SYS_IN and SEP_IN access is graded from a passive per-port sampler of the tb_top AR, AW,
W, R and B handshakes. Where an access through a reprogrammed entry is graded, the expected
answer comes from a lowest-hit decode of the sixteen inbound entries read back from SEP_IN.
Values the contract leaves open (landing of unlocked writes through the window, reconfiguration
timing, mixed bursts, the global-base switch point, burst beat codes and the REGION_SIZE
recovery path) are OBS lines and are never compared.
"""

from __future__ import annotations

from dataclasses import dataclass

import cocotb
from cocotb.triggers import First, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_reset_item import RESET_SAMPLE_FIELDS, SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    _REPO,
    CLOCK_GATE_CONTROL,
    CLOCK_GATE_CONTROL_RESET,
    DMA_CTRL_CONFIG,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    UART_CG_EN,
    _field_mask,
    generated_window,
    reg_field_encode,
    reg_reset_word,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq

OKAY, EXOKAY, SLVERR, DECERR = 0, 1, 2, 3
_RESP = {OKAY: "OKAY", EXOKAY: "EXOKAY", SLVERR: "SLVERR", DECERR: "DECERR", None: "X"}
INCR = 1

BEAT = 8
PAGE = 0x1000
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
ACCESS_BOUND_NS = 100_000
DRIVER_TIMEOUT_NS = 2 * ACCESS_BOUND_NS
RESET_ASSERT_BOUND_REF_CYCLES = 400
RESET_RELEASE_BOUND_REF_CYCLES = 2000
GB_POLL_BOUND = 16
ALL64 = (1 << 64) - 1

PORTS = ("SEP_IN", "SYS_IN")
PREFIX = {"SEP_IN": "s_axi", "SYS_IN": "sys_axi"}
AXI_ID = {"SEP_IN": 0x15, "SYS_IN": 0x2A}
SYS_PROT_NS = 0

_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"
_BASE_CFG_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "smc_base_config.h"
_CPU_CTRL_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks" / "cpu_ctrl.h"


def _fc_bm(name: str) -> int:
    return _field_mask(_FILTER_H, f"FILTER_CTRL__FILTER_CONFIG__{name}_bm")


RA = _fc_bm("READ_ALLOWED")
WA = _fc_bm("WRITE_ALLOWED")
EN = _fc_bm("ENTRY_ENABLED")
NS = _fc_bm("ALLOW_NS")
DBW = _fc_bm("DATA_BUS_WIDTH")
SRC = _fc_bm("SRC_ID")
GRP = _fc_bm("GROUP_ID")
AB = _fc_bm("ALLOW_BURST")
LOCKED = _fc_bm("LOCKED")
DBW_BP = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__DATA_BUS_WIDTH_bp")
SRC_BP = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__SRC_ID_bp")
NS_BP = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__ALLOW_NS_bp")
FC_RW = RA | WA | EN | NS | SRC | GRP | AB | LOCKED
FC_NONFIELD = ALL64 & ~(FC_RW | DBW)
ADDR_MASK = _field_mask(_FILTER_H, "FILTER_CTRL__START_ADDR__START_ADDR_bm")
FC_RESET = reg_reset_word(_FILTER_H, "FILTER_CTRL", "FILTER_CONFIG")
SA_RESET = reg_reset_word(_FILTER_H, "FILTER_CTRL", "START_ADDR")
EA_RESET = reg_reset_word(_FILTER_H, "FILTER_CTRL", "END_ADDR")
DBW_RESET = FC_RESET & DBW

THR_MASK = _field_mask(_BASE_CFG_H, "SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_bm")
THR_RESET = reg_reset_word(_BASE_CFG_H, "SMC_BASE_CONFIG", "HANG_DET_TIMEOUT_THRESHOLD")
FILTER_IB_REG_CG_EN = _field_mask(
    _BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__FILTER_IB_REG_CG_EN_bm"
)
SCRATCH_MASK = _field_mask(_CPU_CTRL_H, "CPU_CTRL__SCRATCH__DATA_bm")

NUM_ENTRIES = smc_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_NUM")
E_IDX, J_IDX, L_IDX, U_IDX, G_IDX, B_IDX, F_IDX, H_IDX, N9_IDX, UNTOUCHED_IDX = (
    4,
    2,
    8,
    10,
    11,
    3,
    6,
    7,
    9,
    12,
)


def FC(i: int) -> int:
    return smc_indexed_addr(
        "SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_FILTER_CONFIG_BASE_ADDR", i
    )


def SA(i: int) -> int:
    return smc_indexed_addr(
        "SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_START_ADDR_BASE_ADDR", i
    )


def EA(i: int) -> int:
    return smc_indexed_addr(
        "SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_END_ADDR_BASE_ADDR", i
    )


def cfg(**fields: int) -> int:
    return reg_field_encode(
        _FILTER_H, "FILTER_CTRL", "FILTER_CONFIG", data_bus_width=DBW_RESET >> DBW_BP, **fields
    )


def rb(word: int) -> int:
    """FILTER_CONFIG readback of a written word: RW fields as written, data_bus_width at reset."""
    return (word & FC_RW) | DBW_RESET


def range_rb(fc: int, sa: int, ea: int) -> tuple[int, int]:
    """START_ADDR/END_ADDR readback after a range write under ``fc``.

    filter_ctrl.rdl start_addr: both are written back rounded to the granule (4 KiB with
    allow_burst, else 2^data_bus_width bytes) only when they land in the same granule.
    """
    g = PAGE if fc & AB else 1 << ((fc & DBW) >> DBW_BP)
    if sa & ~(g - 1) == ea & ~(g - 1):
        return sa & ~(g - 1), ea | (g - 1)
    return sa, ea


GLOBAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_GLOBAL_BASE_BASE_ADDR")
LOCAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
T_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD_BASE_ADDR")
BASE_CFG_OFF = smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR") - LOCAL_BASE_RESET
LOCAL_BASE_OFF = LOCAL_BASE_REG - LOCAL_BASE_RESET

# Window of E: BASE+0x1_0000..0x1_5FFF (base config through the inbound filter control page).
E_START = smc_addr("SMC_TOP_SMC_BASE_CONFIG_BASE_ADDR")
E_END = (FC(0) & ~(PAGE - 1)) + PAGE - 1
E_CFG = cfg(read_allowed=1, write_allowed=1, entry_enabled=1, allow_ns=SYS_PROT_NS, allow_burst=1)

J_CFG1 = cfg(read_allowed=1, allow_ns=1, src_id=0x5, allow_burst=1)
J_SA1, J_EA1 = 0x00AB_CD00_1000, 0x00AB_CD00_2FFF
J_CFG2 = cfg(write_allowed=1, src_id=0xA)
J_SA2, J_EA2 = 0x0012_3456_7000, 0x0012_3456_8FFF
J_RO_WORD = (J_CFG2 & ~DBW) | FC_NONFIELD
DENY_CFG = cfg(entry_enabled=1, allow_ns=SYS_PROT_NS)

L_CFG0 = cfg(read_allowed=1, allow_burst=1)
L_SA0, L_EA0 = 0x0044_0000_0000, 0x0044_0000_0FFF
L_CFG_A = cfg(read_allowed=1, write_allowed=1, allow_ns=1, src_id=0x3)
L_SA_A, L_EA_A = 0x0055_0000_0100, 0x0055_0000_01FF
L_CFG_B = cfg(write_allowed=1, src_id=0x9, allow_burst=1)
L_SA_B, L_EA_B = 0x0066_0000_0000, 0x0066_0000_1FFF
L_CFG_C = cfg(read_allowed=1, write_allowed=1, entry_enabled=1, allow_burst=1)
L_SA_C, L_EA_C = 0x0077_0000_0000, 0x0077_0000_0FFF
N9_SPAN_CFG = cfg(read_allowed=1, src_id=0x6)

UART_ADDR = LOCAL_BASE_RESET + generated_window("smc_uart_wrap")[0]
U_CFG = cfg(read_allowed=1, write_allowed=1, entry_enabled=1, allow_ns=SYS_PROT_NS)
U_START, U_END = UART_ADDR, UART_ADDR + PAGE - 1

# smc_infilt_window_cfg_reexposure contract S8: GLOBAL_BASE moves to 0x5000_0000.
NEW_GLOBAL = 0x5000_0000
OLD_GLOBAL_LB = GLOBAL_BASE_RESET + LOCAL_BASE_OFF
NEW_GLOBAL_LB = NEW_GLOBAL + LOCAL_BASE_OFF
G_CFG_OFF = cfg(read_allowed=1, write_allowed=1, allow_ns=SYS_PROT_NS, allow_burst=1)
G_START = GLOBAL_BASE_RESET + BASE_CFG_OFF
G_END = NEW_GLOBAL + BASE_CFG_OFF + PAGE - 1

SCRATCH = tuple(smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", i) for i in range(8))
B_CFG0 = cfg(read_allowed=1, write_allowed=1, entry_enabled=1, allow_ns=SYS_PROT_NS)
B_CFG1 = B_CFG0 | AB
B_START, B_END = SCRATCH[0], SCRATCH[7] + BEAT - 1
GRAN_X = SCRATCH[2] + 4
OUT_4K = DMA_CTRL_CONFIG
F_CFG = E_CFG

REGION_SIZE_SHRINK = 0x1_0000
LOCAL_BASE_WRITE = 0x0000_0000_D000_0000

FENCE = (
    "ADMIT",
    "READS",
    "UNLOCKED",
    "LOWEST_HIT",
    "PRELOCK",
    "LOCKED",
    "SELF_DENY",
    "BASE_CONFIG",
    "ALLOW_BURST",
    "SHRINK",
)
FENCE_STEP = dict(zip(FENCE, ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10")))
# SYS_IN accesses each term issues at least (the GLOBAL_BASE poll adds reads).
PLANNED = {
    "ADMIT": 1,
    "READS": 11,
    "UNLOCKED": 4,
    "LOWEST_HIT": 13,
    "PRELOCK": 3,
    "LOCKED": 49,
    "SELF_DENY": 9,
    "BASE_CONFIG": 14,
    "ALLOW_BURST": 12,
    "SHRINK": 3,
}

PLANNED_CELLS = {
    "AXIFAB-FWIN-READ.S1": ("SYS_IN/entry-j",),
    "AXIFAB-FWIN-READ.S2": ("SYS_IN/entry-reset",),
    "AXIFAB-FWIN-READ.S3": ("SYS_IN/entry-locked",),
    "AXIFAB-FWIN-READ.S4": ("SYS_IN/base_config",),
    "AXIFAB-FWIN-READ.S5": ("SYS_IN/E-disabled", "SYS_IN/E-reenabled"),
    "AXIFAB-FWIN-WRUNLOCKED.S1": ("SYS_IN/entry-j",),
    "AXIFAB-FWIN-WRUNLOCKED.S2": ("SYS_IN/ro-and-reserved",),
    "AXIFAB-FWIN-WRUNLOCKED.S3": ("SYS_IN/deny-lower",),
    "AXIFAB-FWIN-WRUNLOCKED.S4": ("SYS_IN/deny-higher",),
    "AXIFAB-FWIN-WRLOCKED.S1": ("SYS_IN/locked/cg0", "SYS_IN/locked/cg1"),
    "AXIFAB-FWIN-WRLOCKED.S2": ("SYS_IN/clear-lock",),
    "AXIFAB-FWIN-WRLOCKED.S3": ("SYS_IN/burst-L",),
    "AXIFAB-FWIN-WRLOCKED.S4": ("SYS_IN/burst-L-and-next",),
    "AXIFAB-FWIN-WRLOCKED.S5": ("SEP_IN/locked",),
    "AXIFAB-FWIN-WRLOCKED.S6": ("SYS_IN/prelock", "SYS_IN/after-locked"),
    "AXIFAB-FWIN-SELFDENY.S1": ("SYS_IN/clear-write",),
    "AXIFAB-FWIN-SELFDENY.S2": ("SYS_IN/after-clear-write",),
    "AXIFAB-FWIN-SELFDENY.S3": ("SYS_IN/disable-E",),
    "AXIFAB-FWIN-SELFDENY.S4": ("SYS_IN/fallback-F",),
    "AXIFAB-FWIN-SELFDENY.S5": ("SEP_IN/restore",),
    "AXIFAB-FWIN-BASECFG.S1": ("SYS_IN/local_base",),
    "AXIFAB-FWIN-BASECFG.S2": ("SYS_IN/uart_cg",),
    "AXIFAB-FWIN-BASECFG.S3": ("SYS_IN/hangdet",),
    "AXIFAB-FWIN-BASECFG.S4": ("SYS_IN/global_base",),
    "AXIFAB-FWIN-BASECFG.S5": ("SYS_IN/shrink", "SEP_IN/shrink"),
    "AXIFAB-INFILT-BURST.S1": ("SYS_IN/len=0/allow_burst=0",),
    "AXIFAB-INFILT-BURST.S2": ("SYS_IN/len=3/allow_burst=0/rd", "SYS_IN/len=3/allow_burst=0/wr"),
    "AXIFAB-INFILT-BURST.S3": ("SYS_IN/len=3/allow_burst=1/rd", "SYS_IN/len=3/allow_burst=1/wr"),
    "AXIFAB-INFILT-BURST.S5": (
        "SYS_IN/granule8/in",
        "SYS_IN/granule8/out",
        "SYS_IN/granule4K/in",
        "SYS_IN/granule4K/out",
    ),
    "AXIFAB-INFILT-BURST.S6": ("SYS_IN/after-infilt",),
}

FAMILIES = ("SETUP", "READ", "WRUNLOCKED", "WRLOCKED", "SELFDENY", "BASECFG", "BURST")


def _rname(code: int | None) -> str:
    return _RESP.get(code, str(code))


def _hx(value: int | None) -> str:
    return "X" if value is None else f"0x{value:x}"


def _pack(words: list[int]) -> int:
    return sum((w & ALL64) << (64 * i) for i, w in enumerate(words))


@dataclass
class _Hs:
    chan: str
    ident: int | None
    addr: int | None
    length: int | None
    burst: int | None
    resp: int | None
    data: int | None
    last: int | None
    time_ps: int


class SmcPortHandshakeSampler:
    """Record every AR, AW, W, R and B handshake of SEP_IN and SYS_IN per clk_smc_i edge."""

    _CHANS = ("ar", "aw", "w", "r", "b")

    def __init__(self, dut) -> None:
        self.dut = dut
        self.stop = False
        self.events: dict[str, dict[str, list[_Hs]]] = {
            p: {c: [] for c in self._CHANS} for p in PORTS
        }
        self.last: dict[str, dict[str, _Hs | None]] = {
            p: {c: None for c in self._CHANS} for p in PORTS
        }
        self.unresolved: list[str] = []
        self.unresolved_count = 0
        names = (
            "arvalid",
            "arready",
            "araddr",
            "arid",
            "arlen",
            "arburst",
            "awvalid",
            "awready",
            "awaddr",
            "awid",
            "awlen",
            "awburst",
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
        self.handles = {
            p: {name: getattr(dut, f"{PREFIX[p]}_{name}") for name in names} for p in PORTS
        }

    @staticmethod
    def _int(sig) -> int | None:
        value = sig.value
        return int(value) if value.is_resolvable else None

    def _x(self, what: str) -> None:
        self.unresolved_count += 1
        if len(self.unresolved) < 8:
            self.unresolved.append(f"{what} X at {get_sim_time('ps')} ps")

    def _fire(self, port: str, h: dict, chan: str) -> bool:
        valid = self._int(h[f"{chan}valid"])
        if valid is None:
            self._x(f"{port} {chan}valid")
            return False
        if not valid:
            return False
        ready = self._int(h[f"{chan}ready"])
        if ready is None:
            self._x(f"{port} {chan}ready")
            return False
        return bool(ready)

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
                            self._int(h[f"{chan}burst"]),
                            None,
                            None,
                            None,
                            now,
                        )
                    elif chan == "w":
                        hs = _Hs(
                            "w", None, None, None, None, None, None, self._int(h["wlast"]), now
                        )
                    elif chan == "r":
                        hs = _Hs(
                            "r",
                            self._int(h["rid"]),
                            None,
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
                            None,
                            self._int(h["bresp"]),
                            None,
                            1,
                            now,
                        )
                    self.events[port][chan].append(hs)
                    self.last[port][chan] = hs

    def pending(self, port: str) -> dict[str, int]:
        return {c: len(v) for c, v in self.events[port].items() if v}

    def take(self, port: str) -> dict[str, list[_Hs]]:
        taken = self.events[port]
        self.events[port] = {c: [] for c in self._CHANS}
        return taken

    def describe(self, port: str) -> str:
        parts = []
        for chan in self._CHANS:
            hs = self.last[port][chan]
            if hs is None:
                parts.append(f"{chan}=none")
            elif chan in ("ar", "aw"):
                parts.append(
                    f"{chan}=addr {_hx(hs.addr)} id {hs.ident} len {hs.length} burst {hs.burst} "
                    f"t {hs.time_ps}ps"
                )
            elif chan == "w":
                parts.append(f"w=last {hs.last} t {hs.time_ps}ps")
            elif chan == "r":
                parts.append(
                    f"r=id {hs.ident} resp {_rname(hs.resp)} last {hs.last} t {hs.time_ps}ps"
                )
            else:
                parts.append(f"b=id {hs.ident} resp {_rname(hs.resp)} t {hs.time_ps}ps")
        return "; ".join(parts)


@dataclass
class Entry:
    idx: int
    fc: int
    sa: int
    ea: int


def decode(
    entries: list[Entry], addr: int, write: bool, beats: int
) -> tuple[int | None, int | None]:
    """Lowest-hit inbound decode (fabric.adoc inbound filtering, filter_ctrl.rdl) of one SYS_IN access.

    Returns (expected response of the filter, deciding entry or None for the default block);
    the response is None when an enabled entry carries a non-zero src_id the model cannot match.
    """
    for e in sorted(entries, key=lambda x: x.idx):
        if not e.fc & EN:
            continue
        if ((e.fc & NS) >> NS_BP) != SYS_PROT_NS:
            continue
        if (e.fc & SRC) >> SRC_BP:
            return None, e.idx
        burst_ok = bool(e.fc & AB)
        if beats > 1 and not burst_ok:
            continue
        granule = PAGE if burst_ok else 1 << ((e.fc & DBW) >> DBW_BP)
        lo = e.sa & ~(granule - 1)
        hi = e.ea | (granule - 1)
        if not lo <= addr <= hi:
            continue
        allowed = e.fc & (WA if write else RA)
        return (OKAY if allowed else DECERR), e.idx
    return DECERR, None


class smc_infilt_window_cfg_reexposure_test_seq(SmcCsrSeq):
    """Drive SYS_IN through inbound entries over the filter control and base-config registers."""

    def __init__(self, name: str = "smc_infilt_window_cfg_reexposure_test_seq") -> None:
        super().__init__(name)
        self.sampler: SmcPortHandshakeSampler | None = None
        self.dispatch_reset = None
        self.findings: dict[str, list[str]] = {f: [] for f in FAMILIES}
        self.graded: dict[str, int] = {f: 0 for f in FAMILIES}
        self.cells: dict[tuple[str, str], int] = {}
        self.fence: list[tuple[str, int, int, int]] = []
        self.sys_count = 0
        self.waits = 0
        self.expired = 0
        self.max_wait_ns = 0
        self.reset_waits: list[str] = []
        self.poll_waits: list[str] = []
        self.fuse_state = "not waited"
        self.last_access = "none"
        self.failed: list[str] = []
        self.locked_reads = 0
        self.locked_writes = 0
        self.lowest_hit_accesses = 0
        self.selfdeny_writes = 0
        self.model_snapshots = 0
        self.notes: dict[str, str] = {}

    # ------------------------------------------------------------------ access

    def _sequencer(self, port: str):
        return {"SEP_IN": self.env.sep_in_axi_agent, "SYS_IN": self.env.sys_in_axi_agent}[
            port
        ].sequencer

    async def _issue(
        self,
        port: str,
        label: str,
        addr: int,
        *,
        write: bool,
        beats: int = 1,
        length: int = BEAT,
        wdata: int = 0,
    ) -> tuple[SmcSysAxiItem, dict[str, list[_Hs]]]:
        """Issue one access on ``port`` under a bounded wait; return the item and its handshakes."""
        sampler = self.sampler
        assert sampler is not None
        assert addr % length == 0, f"bench-side: 0x{addr:x} not aligned to {length} bytes"
        assert (addr & (PAGE - 1)) + beats * length <= PAGE, (
            f"bench-side: {beats}x{length}B at 0x{addr:x} would cross a 4 KiB boundary"
        )
        stray = sampler.pending(port)
        if stray:
            self.findings["SETUP"].append(
                f"{port}: handshakes {stray} arrived with no access outstanding before {label}"
            )
            sampler.take(port)
        item = SmcSysAxiItem(f"{port.lower()}_{label}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.beats = beats
        item.burst = INCR
        item.wdata = wdata
        item.axi_id = AXI_ID[port]
        item.capture_resp_id = beats == 1
        item.timeout_ns = DRIVER_TIMEOUT_NS
        item.allow_error = True
        kind = "write" if write else "read"
        self.last_access = f"{port} {label} {kind} 0x{addr:x} beats={beats}"
        start = int(get_sim_time("ns"))
        task = cocotb.start_soon(
            _OneShot(item, f"{item.get_name()}_os").start(self._sequencer(port))
        )
        await First(task, Timer(ACCESS_BOUND_NS, unit="ns"))
        self.waits += 1
        if not task.done():
            self.expired += 1
            rst = cocotb.top.rst_primary_smc_clk_no.value
            level = int(rst) if rst.is_resolvable else "X"
            cocotb.log.info(
                "INFO-CLASSIFY: unanswered-transaction design-side port=%s %s bound=%d ns "
                "expired; last %s; rst_primary_smc_clk_no=%s",
                port,
                self.last_access,
                ACCESS_BOUND_NS,
                sampler.describe(port),
                level,
            )
            raise AssertionError(
                f"{self.last_access} unanswered after {ACCESS_BOUND_NS} ns "
                f"(last {sampler.describe(port)}, rst_primary_smc_clk_no={level})"
            )
        await task
        self.max_wait_ns = max(self.max_wait_ns, int(get_sim_time("ns")) - start)
        self.accesses += 1
        if port == "SYS_IN":
            self.sys_count += 1
        return item, sampler.take(port)

    def _check_addr(
        self, fam: str, ctx: str, hs: dict, chan: str, addr: int, beats: int, port: str
    ) -> None:
        got = hs[chan]
        if len(got) != 1:
            self.findings[fam].append(f"{ctx}: {len(got)} {chan.upper()} handshakes, want 1")
            return
        a = got[0]
        if (a.addr, a.ident, a.length, a.burst) != (addr, AXI_ID[port], beats - 1, INCR):
            self.findings[fam].append(
                f"{ctx}: bench-side {chan.upper()} addr/id/len/burst "
                f"{_hx(a.addr)}/{a.ident}/{a.length}/{a.burst}, want 0x{addr:x}/{AXI_ID[port]}/"
                f"{beats - 1}/{INCR}"
            )

    async def _read(
        self,
        fam: str,
        port: str,
        label: str,
        addr: int,
        *,
        code: int | None = OKAY,
        beats: int = 1,
        length: int = BEAT,
    ) -> list[_Hs]:
        """Read with protocol graded (beats, RID, RLAST, no EXOKAY, no X) and each beat's code when stated."""
        item, hs = await self._issue(port, label, addr, write=False, beats=beats, length=length)
        ctx = f"{port} {label} read 0x{addr:x}"
        self._check_addr(fam, ctx, hs, "ar", addr, beats, port)
        if hs["aw"] or hs["w"] or hs["b"]:
            self.findings[fam].append(f"{ctx}: write-channel handshakes during a read")
        r = hs["r"]
        if len(r) != beats:
            self.findings[fam].append(f"{ctx}: {len(r)} R beats, want {beats}")
        for i, beat in enumerate(r):
            if beat.ident != AXI_ID[port]:
                self.findings[fam].append(f"{ctx}: beat {i} RID {beat.ident}")
            if beat.last != (1 if i == beats - 1 else 0):
                self.findings[fam].append(f"{ctx}: beat {i} RLAST {beat.last}")
            if beat.resp is None or beat.resp == EXOKAY:
                self.findings[fam].append(f"{ctx}: beat {i} RRESP {_rname(beat.resp)}")
            elif code is not None and beat.resp != code:
                self.findings[fam].append(
                    f"{ctx}: beat {i} RRESP {_rname(beat.resp)}, want {_rname(code)}"
                )
            if beat.data is None:
                self.findings[fam].append(f"{ctx}: beat {i} RDATA X")
        self.graded[fam] += 1
        return r

    async def _write(
        self,
        fam: str,
        port: str,
        label: str,
        addr: int,
        data: int,
        *,
        code: int | None = OKAY,
        beats: int = 1,
    ) -> int | None:
        """Write with protocol graded (W beats, WLAST, one B, BID, no EXOKAY) and BRESP when stated."""
        item, hs = await self._issue(port, label, addr, write=True, beats=beats, wdata=data)
        ctx = f"{port} {label} write 0x{addr:x}"
        self._check_addr(fam, ctx, hs, "aw", addr, beats, port)
        if hs["ar"] or hs["r"]:
            self.findings[fam].append(f"{ctx}: read-channel handshakes during a write")
        w = hs["w"]
        if len(w) != beats:
            self.findings[fam].append(f"{ctx}: {len(w)} W beats accepted, want {beats}")
        for i, beat in enumerate(w):
            if beat.last != (1 if i == beats - 1 else 0):
                self.findings[fam].append(f"{ctx}: W beat {i} WLAST {beat.last}")
        b = hs["b"]
        self.graded[fam] += 1
        if len(b) != 1:
            self.findings[fam].append(f"{ctx}: {len(b)} B responses, want 1")
            return None
        if b[0].ident != AXI_ID[port]:
            self.findings[fam].append(f"{ctx}: BID {b[0].ident}")
        if b[0].resp is None or b[0].resp == EXOKAY:
            self.findings[fam].append(f"{ctx}: BRESP {_rname(b[0].resp)}")
        elif code is not None and b[0].resp != code:
            self.findings[fam].append(f"{ctx}: BRESP {_rname(b[0].resp)}, want {_rname(code)}")
        return b[0].resp

    async def _rd(self, fam: str, port: str, label: str, addr: int, **kw) -> int | None:
        """Single 64-bit read graded OKAY; returns its data."""
        r = await self._read(fam, port, label, addr, **kw)
        return r[0].data if r else None

    def _expect(self, fam: str, ctx: str, got: int | None, want: int, mask: int = ALL64) -> bool:
        if got is None or (got & mask) != (want & mask):
            self.findings[fam].append(f"{ctx}: {_hx(got)}, want 0x{want & mask:x}")
            return False
        return True

    def _cell(self, scen: str, cell: str) -> None:
        assert cell in PLANNED_CELLS[scen], f"{scen} {cell} is not a planned cell"
        self.cells[(scen, cell)] = self.cells.get((scen, cell), 0) + 1

    def _mark(self, term: str, start_sys: int) -> None:
        now = int(get_sim_time("ps"))
        n = self.sys_count - start_sys
        self.fence.append((term, now, n, PLANNED[term]))
        cocotb.log.info(
            "INFO-STEP %s %s done at %d ps: %d SYS_IN accesses against %d planned",
            FENCE_STEP[term],
            term,
            now,
            n,
            PLANNED[term],
        )

    def _obs(self, tag: str, **kv) -> None:
        for key, value in kv.items():
            if value is None or value == "X":
                self.findings["SETUP"].append(f"{tag}: {key} sampled X or missing")
        cocotb.log.info("%s: %s", tag, " ".join(f"{k}={v}" for k, v in kv.items()))

    # ------------------------------------------------------------ SEP_IN setup

    async def _sep_entry(self, fam: str, idx: int, fc: int, sa: int, ea: int, tag: str) -> None:
        """Program entry ``idx`` from SEP_IN and read it back.

        The entry is first written disabled with its final allow_burst, so the range write-back
        (filter_ctrl.rdl start_addr) uses the granule of the new configuration.
        """
        await self._write(fam, "SEP_IN", f"{tag}_E{idx}_FC_OFF", FC(idx), fc & ~(EN | LOCKED))
        await self._write(fam, "SEP_IN", f"{tag}_E{idx}_SA", SA(idx), sa)
        await self._write(fam, "SEP_IN", f"{tag}_E{idx}_EA", EA(idx), ea)
        await self._write(fam, "SEP_IN", f"{tag}_E{idx}_FC", FC(idx), fc)
        await self._check_entry(fam, "SEP_IN", idx, rb(fc), sa, ea, tag)

    async def _check_entry(
        self, fam: str, port: str, idx: int, fc: int, sa: int, ea: int, tag: str
    ) -> tuple[int | None, int | None, int | None]:
        got = []
        for reg, addr, want in (("FC", FC(idx), fc), ("SA", SA(idx), sa), ("EA", EA(idx), ea)):
            value = await self._rd(fam, port, f"{tag}_E{idx}_{reg}_RB", addr)
            self._expect(fam, f"{tag} {port} entry {idx} {reg}", value, want)
            got.append(value)
        return got[0], got[1], got[2]

    async def _read_entry(self, port: str, idx: int, tag: str) -> Entry | None:
        vals = []
        for reg, addr in (("FC", FC(idx)), ("SA", SA(idx)), ("EA", EA(idx))):
            vals.append(await self._rd("SETUP", port, f"{tag}_E{idx}_{reg}", addr))
        if any(v is None for v in vals):
            return None
        return Entry(idx, vals[0], vals[1], vals[2])

    async def _snapshot(self, tag: str) -> list[Entry]:
        """Every inbound entry read back from SEP_IN: the model input of a decode check."""
        entries = []
        for idx in range(NUM_ENTRIES):
            e = await self._read_entry("SEP_IN", idx, f"{tag}_SNAP")
            if e is None:
                self.findings["SETUP"].append(f"{tag}: entry {idx} readback X")
                continue
            entries.append(e)
        self.model_snapshots += 1
        enabled = [f"{e.idx}:{_hx(e.fc)}[{_hx(e.sa)}..{_hx(e.ea)}]" for e in entries if e.fc & EN]
        cocotb.log.info("INFO-MODEL %s: enabled entries %s", tag, " ".join(enabled) or "none")
        return entries

    def _model(
        self,
        fam: str,
        ctx: str,
        entries,
        addr: int,
        write: bool,
        beats: int = 1,
        *,
        by: int | None | str = "any",
    ) -> int:
        """Decode of one access; ``by`` names the entry (None: default block) that must decide."""
        code, idx = decode(entries, addr, write, beats)
        if code is None:
            self.findings[fam].append(f"{ctx}: entry {idx} carries a src_id the model cannot match")
            return DECERR
        if by != "any" and idx != by:
            self.findings[fam].append(
                f"KEY-FWIN-DECIDER {ctx}: 0x{addr:x} decided by "
                f"{'default block' if idx is None else f'entry {idx}'}, want "
                f"{'default block' if by is None else f'entry {by}'}"
            )
        cocotb.log.info(
            "INFO-MODEL %s: 0x%x %s decided by %s -> %s",
            ctx,
            addr,
            "write" if write else "read",
            "default block" if idx is None else f"entry {idx}",
            _rname(code),
        )
        return code

    def _landed(self, fam: str, ctx: str, entries: list[Entry], idx: int, want: tuple) -> None:
        """KEY-FWIN-LANDED: entry ``idx`` of a snapshot holds the programmed FC/SA/EA."""
        e = next((x for x in entries if x.idx == idx), None)
        got = (None, None, None) if e is None else (e.fc, e.sa, e.ea)
        ok = got == want
        if not ok:
            self.findings[fam].append(
                f"KEY-FWIN-LANDED {ctx}: entry {idx} FC/SA/EA "
                f"{'/'.join(_hx(v) for v in got)}, want {'/'.join(_hx(v) for v in want)}"
            )
        cocotb.log.info(
            "INFO-KEYSTEP %s: entry %d FC/SA/EA %s, programmed %s, %s",
            ctx,
            idx,
            "/".join(_hx(v) for v in got),
            "/".join(_hx(v) for v in want),
            "landed" if ok else "NOT landed",
        )

    async def _live(self, fam: str, tag: str) -> None:
        r = await self._read(fam, "SYS_IN", f"{tag}_LIVE", LOCAL_BASE_REG)
        if r:
            self._expect(fam, f"{tag} SYS_IN LOCAL_BASE liveness", r[0].data, LOCAL_BASE_RESET)

    # ------------------------------------------------------------------ phases

    async def _admit(self) -> None:
        s = self.sys_count
        await self._sep_entry("SETUP", E_IDX, E_CFG, E_START, E_END, "S1")
        await self._sep_entry("SETUP", J_IDX, J_CFG1, J_SA1, J_EA1, "S1")
        await self._sep_entry("SETUP", L_IDX, L_CFG0, L_SA0, L_EA0, "S1")
        await self._sep_entry("SETUP", U_IDX, U_CFG, U_START, U_END, "S1")
        await self._sep_entry("SETUP", G_IDX, G_CFG_OFF, G_START, G_END, "S1")
        await self._sep_entry("SETUP", B_IDX, B_CFG0, B_START, B_END, "S1")
        await self._check_entry(
            "SETUP", "SEP_IN", UNTOUCHED_IDX, FC_RESET, SA_RESET, EA_RESET, "S1"
        )
        r = await self._read("SETUP", "SYS_IN", "ADMIT", LOCAL_BASE_REG)
        ok = bool(r) and r[0].resp == OKAY and r[0].data == LOCAL_BASE_RESET
        assert ok and not self.findings["SETUP"], (
            f"CTRL-M6-ADMIT: SYS_IN read of LOCAL_BASE through entry {E_IDX} answered "
            f"{_rname(r[0].resp) if r else 'none'} {_hx(r[0].data) if r else ''}; "
            f"setup findings {self.findings['SETUP']}"
        )
        cocotb.log.info(
            "CTRL-M6-ADMIT: SYS_IN 64-bit read of LOCAL_BASE @ 0x%x through inbound entry %d "
            "[0x%x..0x%x] answered OKAY %s RID %d",
            LOCAL_BASE_REG,
            E_IDX,
            E_START,
            E_END,
            _hx(r[0].data),
            r[0].ident,
        )
        self._obs(
            "OBS-FWIN-READ",
            e_start=_hx(E_START),
            e_end=_hx(E_END),
            issued=_hx(LOCAL_BASE_REG),
            admit=_rname(r[0].resp),
        )
        self._mark("ADMIT", s)

    async def _reads(self) -> None:
        s = self.sys_count
        fam = "READ"
        await self._check_entry(fam, "SYS_IN", J_IDX, rb(J_CFG1), J_SA1, J_EA1, "S2")
        self._cell("AXIFAB-FWIN-READ.S1", "SYS_IN/entry-j")
        await self._check_entry(fam, "SYS_IN", UNTOUCHED_IDX, FC_RESET, SA_RESET, EA_RESET, "S2")
        self._cell("AXIFAB-FWIN-READ.S2", "SYS_IN/entry-reset")
        for name, addr, want in (
            ("GLOBAL_BASE", GLOBAL_BASE_REG, GLOBAL_BASE_RESET),
            ("LOCAL_BASE", LOCAL_BASE_REG, LOCAL_BASE_RESET),
            ("REGION_SIZE", REGION_SIZE_REG, REGION_SIZE_RESET),
        ):
            got = await self._rd(fam, "SYS_IN", f"S2_{name}", addr)
            self._expect(fam, f"S2 SYS_IN {name}", got, want)
        self._cell("AXIFAB-FWIN-READ.S4", "SYS_IN/base_config")
        await self._write("SETUP", "SEP_IN", "S2_E_DISABLE", FC(E_IDX), E_CFG & ~EN)
        got = await self._rd("SETUP", "SEP_IN", "S2_E_DISABLE_RB", FC(E_IDX))
        self._expect("SETUP", "S2 SEP_IN E disabled", got, rb(E_CFG & ~EN))
        await self._read(fam, "SYS_IN", "S2_E_DISABLED", LOCAL_BASE_REG, code=DECERR)
        self._cell("AXIFAB-FWIN-READ.S5", "SYS_IN/E-disabled")
        await self._write("SETUP", "SEP_IN", "S2_E_ENABLE", FC(E_IDX), E_CFG)
        got = await self._rd("SETUP", "SEP_IN", "S2_E_ENABLE_RB", FC(E_IDX))
        self._expect("SETUP", "S2 SEP_IN E re-enabled", got, rb(E_CFG))
        r = await self._read(fam, "SYS_IN", "S2_E_REENABLED", LOCAL_BASE_REG)
        if r:
            self._expect(fam, "S2 SYS_IN LOCAL_BASE with E re-enabled", r[0].data, LOCAL_BASE_RESET)
        self._cell("AXIFAB-FWIN-READ.S5", "SYS_IN/E-reenabled")
        self._mark("READS", s)

    async def _unlocked(self) -> None:
        s = self.sys_count
        fam = "WRUNLOCKED"
        for reg, addr, value in (
            ("SA", SA(J_IDX), J_SA2),
            ("EA", EA(J_IDX), J_EA2),
            ("FC", FC(J_IDX), J_CFG2),
        ):
            bresp = await self._write(fam, "SYS_IN", f"S3_J_{reg}", addr, value, code=None)
            back = await self._rd("SETUP", "SEP_IN", f"S3_J_{reg}_RB", addr)
            self._obs(
                "OBS-FWIN-WRUNLOCKED",
                reg=f"entry{J_IDX}.{reg}",
                wrote=_hx(value),
                bresp=_rname(bresp),
                readback=_hx(back),
            )
        self._cell("AXIFAB-FWIN-WRUNLOCKED.S1", "SYS_IN/entry-j")
        before = await self._rd("SETUP", "SEP_IN", "S3_J_FC_PRE_RO", FC(J_IDX))
        await self._write(fam, "SYS_IN", "S3_J_FC_RO_NONFIELD", FC(J_IDX), J_RO_WORD)
        after = await self._rd("SETUP", "SEP_IN", "S3_J_FC_POST_RO", FC(J_IDX))
        self._expect(
            fam,
            "S3 entry j data_bus_width and non-field bits after the SYS_IN write",
            after,
            DBW_RESET,
            DBW | FC_NONFIELD,
        )
        self._obs(
            "OBS-FWIN-WRUNLOCKED",
            reg=f"entry{J_IDX}.FC.rw_fields",
            wrote=_hx(J_RO_WORD),
            before=_hx(before),
            readback=_hx(after),
        )
        self._cell("AXIFAB-FWIN-WRUNLOCKED.S2", "SYS_IN/ro-and-reserved")
        self._mark("UNLOCKED", s)

    async def _lowest_hit_leg(self, idx: int, scen: str, cell: str, value: int, t_by: int) -> None:
        """Rewrite entry ``idx`` from SYS_IN as a deny entry over T and grade the decode.

        The fields are sw=rw and only a locked entry steers writes to DECERR
        (filter_ctrl.rdl:20-35, 80-84), so each SYS_IN write must read back from SEP_IN as
        programmed (KEY-FWIN-LANDED), and T must be decided by entry ``t_by``
        (KEY-FWIN-DECIDER) before the exposure is graded.
        """
        fam = "WRUNLOCKED"
        pre = await self._read_entry("SEP_IN", idx, f"S4_E{idx}_PRE")
        if pre is None:
            self.findings["SETUP"].append(f"S4 entry {idx} readback X before the deny writes")
            pre = Entry(idx, FC_RESET, SA_RESET, EA_RESET)
        fc_now, sa_now, ea_now = pre.fc, pre.sa, pre.ea
        for reg, addr, word in (
            ("SA", SA(idx), T_REG),
            ("EA", EA(idx), T_REG + BEAT - 1),
            ("FC", FC(idx), DENY_CFG),
        ):
            bresp = await self._write(fam, "SYS_IN", f"S4_E{idx}_{reg}_DENY", addr, word, code=None)
            if reg == "FC":
                fc_now = rb(word)
                want = (("FC", FC(idx), fc_now),)
            else:
                if reg == "SA":
                    sa_now, ea_now = range_rb(fc_now, word, ea_now)
                else:
                    sa_now, ea_now = range_rb(fc_now, sa_now, word)
                want = (("SA", SA(idx), sa_now), ("EA", EA(idx), ea_now))
            backs = []
            for rreg, raddr, rwant in want:
                back = await self._rd(fam, "SEP_IN", f"S4_E{idx}_{reg}_DENY_{rreg}_RB", raddr)
                self._expect(
                    fam,
                    f"KEY-FWIN-LANDED S4 entry {idx} {rreg} after the SYS_IN {reg} write",
                    back,
                    rwant,
                )
                backs.append(f"{rreg}={_hx(back)}")
            self._obs(
                "OBS-FWIN-WRUNLOCKED",
                reg=f"entry{idx}.{reg}",
                wrote=_hx(word),
                bresp=_rname(bresp),
                readback=",".join(backs),
            )
        entries = await self._snapshot(f"S4_E{idx}")
        self._landed(fam, f"S4 deny entry {idx}", entries, idx, (fc_now, sa_now, ea_now))
        t_ref = await self._rd("SETUP", "SEP_IN", f"S4_E{idx}_T_REF", T_REG)
        want_rd = self._model(fam, f"S4 deny entry {idx} T read", entries, T_REG, False, by=t_by)
        want_wr = self._model(fam, f"S4 deny entry {idx} T write", entries, T_REG, True, by=t_by)
        want_out = self._model(
            fam, f"S4 deny entry {idx} outside", entries, LOCAL_BASE_REG, False, by=E_IDX
        )
        r = await self._read(fam, "SYS_IN", f"S4_E{idx}_T_RD", T_REG, code=want_rd)
        if want_rd == OKAY and r and t_ref is not None:
            self._expect(fam, f"S4 deny entry {idx} T read data", r[0].data, t_ref, THR_MASK)
        await self._write(fam, "SYS_IN", f"S4_E{idx}_T_WR", T_REG, value, code=want_wr)
        r = await self._read(fam, "SYS_IN", f"S4_E{idx}_OUTSIDE", LOCAL_BASE_REG, code=want_out)
        if want_out == OKAY and r:
            self._expect(fam, f"S4 deny entry {idx} outside data", r[0].data, LOCAL_BASE_RESET)
        t_now = await self._rd("SETUP", "SEP_IN", f"S4_E{idx}_T_POST", T_REG)
        if t_ref is not None:
            want_t = value if want_wr == OKAY else t_ref
            self._expect(
                fam, f"S4 deny entry {idx} T after the SYS_IN write", t_now, want_t, THR_MASK
            )
        self.lowest_hit_accesses += 3
        self._cell(scen, cell)
        await self._write("SETUP", "SEP_IN", "S4_T_RESTORE", T_REG, THR_RESET)

    async def _lowest_hit(self) -> None:
        s = self.sys_count
        await self._lowest_hit_leg(
            J_IDX, "AXIFAB-FWIN-WRUNLOCKED.S3", "SYS_IN/deny-lower", 0x1_2345, J_IDX
        )
        await self._sep_entry("SETUP", J_IDX, J_CFG1, J_SA1, J_EA1, "S4_RESTORE")
        await self._lowest_hit_leg(
            H_IDX, "AXIFAB-FWIN-WRUNLOCKED.S4", "SYS_IN/deny-higher", 0x2_3456, E_IDX
        )
        await self._sep_entry("SETUP", H_IDX, FC_RESET, SA_RESET, EA_RESET, "S4_RESTORE")
        await self._live("WRUNLOCKED", "S4")
        self._mark("LOWEST_HIT", s)

    async def _prelock(self) -> None:
        s = self.sys_count
        fam = "WRLOCKED"
        await self._sep_entry(fam, L_IDX, L_CFG_A, L_SA_A, L_EA_A, "S5_CTRL")
        landed = []
        bresps = []
        for reg, addr, value in (
            ("SA", SA(L_IDX), L_SA_B),
            ("EA", EA(L_IDX), L_EA_B),
            ("FC", FC(L_IDX), L_CFG_B),
        ):
            bresps.append(
                await self._write(fam, "SYS_IN", f"S5_L_{reg}_SYS", addr, value, code=None)
            )
            back = await self._rd("SETUP", "SEP_IN", f"S5_L_{reg}_SYS_RB", addr)
            want = rb(value) if reg == "FC" else value
            landed.append("y" if back == want else "n")
        self.notes["prelock_sys_bresp"] = ",".join(_rname(b) for b in bresps)
        self.notes["prelock_landed"] = ",".join(landed)
        self._cell("AXIFAB-FWIN-WRLOCKED.S6", "SYS_IN/prelock")
        await self._sep_entry("SETUP", L_IDX, L_CFG_A, L_SA_A, L_EA_A, "S5_REARM")
        await self._write(fam, "SEP_IN", "S5_L_LOCK", FC(L_IDX), L_CFG_A | LOCKED)
        await self._check_entry(
            fam, "SEP_IN", L_IDX, rb(L_CFG_A | LOCKED), L_SA_A, L_EA_A, "S5_LOCKED"
        )
        self._mark("PRELOCK", s)

    async def _check_locked(self, tag: str) -> dict[str, int | None]:
        want = (rb(L_CFG_A | LOCKED), L_SA_A, L_EA_A)
        for port in ("SYS_IN", "SEP_IN"):
            await self._check_entry("WRLOCKED", port, L_IDX, *want, f"{tag}_{port[:3]}")
            self.locked_reads += 3
        n9 = {}
        for reg, addr in (("FC", FC(N9_IDX)), ("SA", SA(N9_IDX)), ("EA", EA(N9_IDX))):
            n9[reg] = await self._rd("SETUP", "SEP_IN", f"{tag}_E9_{reg}", addr)
        return n9

    async def _locked_write(
        self, port: str, tag: str, addr: int, data: int, beats: int = 1, code: int | None = DECERR
    ) -> tuple[int | None, dict[str, int | None]]:
        bresp = await self._write("WRLOCKED", port, tag, addr, data, code=code, beats=beats)
        self.locked_writes += 1
        n9 = await self._check_locked(tag)
        return bresp, n9

    async def _locked(self) -> None:
        s = self.sys_count
        fam = "WRLOCKED"
        await self._check_entry(
            "READ", "SYS_IN", L_IDX, rb(L_CFG_A | LOCKED), L_SA_A, L_EA_A, "S6_READ"
        )
        self._cell("AXIFAB-FWIN-READ.S3", "SYS_IN/entry-locked")
        n9_ref = {}
        for reg, addr, want in (
            ("FC", FC(N9_IDX), FC_RESET),
            ("SA", SA(N9_IDX), SA_RESET),
            ("EA", EA(N9_IDX), EA_RESET),
        ):
            n9_ref[reg] = await self._rd("SETUP", "SEP_IN", f"S6_E9_{reg}_REF", addr)
            self._expect("SETUP", f"S6 entry 9 {reg} before the locked writes", n9_ref[reg], want)
        triple = (("FC", FC(L_IDX), L_CFG_C), ("SA", SA(L_IDX), L_SA_C), ("EA", EA(L_IDX), L_EA_C))
        for cg, cell in ((0, "SYS_IN/locked/cg0"), (1, "SYS_IN/locked/cg1")):
            cgc = CLOCK_GATE_CONTROL_RESET | (FILTER_IB_REG_CG_EN if cg else 0)
            await self._write("SETUP", "SEP_IN", f"S6_CGC{cg}", CLOCK_GATE_CONTROL, cgc)
            got = await self._rd("SETUP", "SEP_IN", f"S6_CGC{cg}_RB", CLOCK_GATE_CONTROL)
            self._expect("SETUP", f"S6 CLOCK_GATE_CONTROL filter_ib_reg_cg_en={cg}", got, cgc)
            for reg, addr, value in triple:
                _b, n9 = await self._locked_write("SYS_IN", f"S6_CG{cg}_{reg}", addr, value)
                for k, v in n9.items():
                    self._expect(fam, f"S6 entry 9 {k} after the cg{cg} {reg} write", v, n9_ref[k])
            self._cell("AXIFAB-FWIN-WRLOCKED.S1", cell)
        await self._write(
            "SETUP", "SEP_IN", "S6_CGC_RESTORE", CLOCK_GATE_CONTROL, CLOCK_GATE_CONTROL_RESET
        )
        await self._locked_write("SYS_IN", "S6_CLEAR_LOCK", FC(L_IDX), L_CFG_A)
        self._cell("AXIFAB-FWIN-WRLOCKED.S2", "SYS_IN/clear-lock")
        await self._locked_write(
            "SYS_IN", "S6_BURST_L", FC(L_IDX), _pack([L_CFG_C, L_SA_C, L_EA_C]), beats=3
        )
        self._cell("AXIFAB-FWIN-WRLOCKED.S3", "SYS_IN/burst-L")
        span_bresp, n9 = await self._locked_write(
            "SYS_IN",
            "S6_BURST_SPAN",
            EA(L_IDX),
            _pack([L_EA_C, 0, N9_SPAN_CFG]),
            beats=3,
            code=None,
        )
        self.notes["span_bresp"] = _rname(span_bresp)
        self.notes["entry9"] = "/".join(_hx(n9[k]) for k in ("FC", "SA", "EA"))
        self._cell("AXIFAB-FWIN-WRLOCKED.S4", "SYS_IN/burst-L-and-next")
        for reg, addr, value in triple:
            await self._locked_write("SEP_IN", f"S6_SEP_{reg}", addr, value)
        self._cell("AXIFAB-FWIN-WRLOCKED.S5", "SEP_IN/locked")
        await self._live(fam, "S6_AFTER_LOCKED")
        self._cell("AXIFAB-FWIN-WRLOCKED.S6", "SYS_IN/after-locked")
        self._obs(
            "OBS-FWIN-WRLOCKED",
            span_bresp=self.notes["span_bresp"],
            entry9=self.notes["entry9"],
            prelock_sys_bresp=self.notes["prelock_sys_bresp"],
            prelock_landed=self.notes["prelock_landed"],
        )
        self._mark("LOCKED", s)

    async def _restore_e(self, tag: str) -> None:
        await self._write("SELFDENY", "SEP_IN", f"{tag}_E_RESTORE", FC(E_IDX), E_CFG)
        got = await self._rd("SELFDENY", "SEP_IN", f"{tag}_E_RESTORE_RB", FC(E_IDX))
        self._expect("SELFDENY", f"{tag} SEP_IN E restore readback", got, rb(E_CFG))

    @staticmethod
    def _e_want(fc: int) -> tuple[int, int, int]:
        """E after a SYS_IN FILTER_CONFIG write of ``fc``: the field readback, its range kept."""
        return rb(fc), E_START, E_END

    async def _self_deny(self) -> None:
        """Self-deny writes through E, each required to land (KEY-FWIN-LANDED) and to move the
        decision of the next accesses to the stated entry (KEY-FWIN-DECIDER) before they are
        graded; filter_ctrl.rdl:20-35 states the fields sw=rw.
        """
        s = self.sys_count
        fam = "SELFDENY"

        bresp = await self._write(fam, "SYS_IN", "S7_E_CLR_WA", FC(E_IDX), E_CFG & ~WA, code=None)
        self.selfdeny_writes += 1
        entries = await self._snapshot("S7_CLR_WA")
        self._landed(fam, "S7 E write_allowed cleared", entries, E_IDX, self._e_want(E_CFG & ~WA))
        e_fc = next((e.fc for e in entries if e.idx == E_IDX), None)
        self._obs(
            "OBS-FWIN-SELFDENY",
            field="write_allowed",
            bresp=_rname(bresp),
            readback=_hx(e_fc),
        )
        self._cell("AXIFAB-FWIN-SELFDENY.S1", "SYS_IN/clear-write")
        t_ref = await self._rd("SETUP", "SEP_IN", "S7_T_REF", T_REG)
        want_wr = self._model(
            fam, "S7 write_allowed cleared T write", entries, T_REG, True, by=E_IDX
        )
        want_rd = self._model(
            fam, "S7 write_allowed cleared T read", entries, T_REG, False, by=E_IDX
        )
        await self._write(fam, "SYS_IN", "S7_T_WR", T_REG, 0x3_4567, code=want_wr)
        r = await self._read(fam, "SYS_IN", "S7_T_RD", T_REG, code=want_rd)
        t_now = await self._rd("SETUP", "SEP_IN", "S7_T_POST", T_REG)
        if t_ref is not None:
            want_t = 0x3_4567 if want_wr == OKAY else t_ref
            self._expect(
                fam, "S7 T after the write with write_allowed cleared", t_now, want_t, THR_MASK
            )
            if want_rd == OKAY and r:
                self._expect(fam, "S7 T read data", r[0].data, want_t, THR_MASK)
        self._cell("AXIFAB-FWIN-SELFDENY.S2", "SYS_IN/after-clear-write")
        await self._restore_e("S7_A")
        await self._write("SETUP", "SEP_IN", "S7_T_RESTORE", T_REG, THR_RESET)

        bresp = await self._write(fam, "SYS_IN", "S7_E_DISABLE", FC(E_IDX), E_CFG & ~EN, code=None)
        self.selfdeny_writes += 1
        entries = await self._snapshot("S7_DISABLE")
        self._landed(fam, "S7 E disabled", entries, E_IDX, self._e_want(E_CFG & ~EN))
        e_fc = next((e.fc for e in entries if e.idx == E_IDX), None)
        self._obs(
            "OBS-FWIN-SELFDENY",
            field="entry_enabled",
            bresp=_rname(bresp),
            readback=_hx(e_fc),
        )
        want_rd = self._model(fam, "S7 E disabled T read", entries, T_REG, False, by=None)
        want_wr = self._model(fam, "S7 E disabled T write", entries, T_REG, True, by=None)
        await self._read(fam, "SYS_IN", "S7_DIS_T_RD", T_REG, code=want_rd)
        await self._write(fam, "SYS_IN", "S7_DIS_T_WR", T_REG, 0x4_5678, code=want_wr)
        t_now = await self._rd("SETUP", "SEP_IN", "S7_DIS_T_POST", T_REG)
        want_t = 0x4_5678 if want_wr == OKAY else THR_RESET
        self._expect(fam, "S7 T after the write with E disabled", t_now, want_t, THR_MASK)
        self._cell("AXIFAB-FWIN-SELFDENY.S3", "SYS_IN/disable-E")
        await self._restore_e("S7_B")
        await self._write("SETUP", "SEP_IN", "S7_DIS_T_RESTORE", T_REG, THR_RESET)

        await self._sep_entry(fam, F_IDX, F_CFG, E_START, E_END, "S7_F")
        bresp = await self._write(
            fam, "SYS_IN", "S7_HANDOVER_DISABLE_E", FC(E_IDX), E_CFG & ~EN, code=None
        )
        self.selfdeny_writes += 1
        entries = await self._snapshot("S7_HANDOVER")
        self._landed(fam, "S7 E disabled under F", entries, E_IDX, self._e_want(E_CFG & ~EN))
        e_fc = next((e.fc for e in entries if e.idx == E_IDX), None)
        self._obs(
            "OBS-FWIN-SELFDENY",
            field="entry_enabled_handover",
            bresp=_rname(bresp),
            readback=_hx(e_fc),
        )
        want_rd = self._model(fam, "S7 handover read", entries, LOCAL_BASE_REG, False, by=F_IDX)
        r = await self._read(fam, "SYS_IN", "S7_HANDOVER_RD", LOCAL_BASE_REG, code=want_rd)
        if want_rd == OKAY and r:
            self._expect(fam, "S7 handover LOCAL_BASE data", r[0].data, LOCAL_BASE_RESET)
        self._cell("AXIFAB-FWIN-SELFDENY.S4", "SYS_IN/fallback-F")
        await self._restore_e("S7_C")
        await self._sep_entry(fam, F_IDX, FC_RESET, SA_RESET, EA_RESET, "S7_F_OFF")
        self._cell("AXIFAB-FWIN-SELFDENY.S5", "SEP_IN/restore")
        await self._live(fam, "S7")
        self._mark("SELF_DENY", s)

    async def _base_config(self) -> None:
        s = self.sys_count
        fam = "BASECFG"
        await self._write(fam, "SYS_IN", "S8_LOCAL_BASE_WR", LOCAL_BASE_REG, LOCAL_BASE_WRITE)
        got = await self._rd(fam, "SYS_IN", "S8_LOCAL_BASE_RD", LOCAL_BASE_REG)
        self._expect(fam, "S8 LOCAL_BASE after the SYS_IN write", got, LOCAL_BASE_RESET)
        self._cell("AXIFAB-FWIN-BASECFG.S1", "SYS_IN/local_base")

        gated = CLOCK_GATE_CONTROL_RESET | UART_CG_EN
        await self._write(fam, "SYS_IN", "S8_CGC_UART_SET", CLOCK_GATE_CONTROL, gated)
        got = await self._rd("SETUP", "SEP_IN", "S8_CGC_UART_SET_RB", CLOCK_GATE_CONTROL)
        self._expect(fam, "S8 CLOCK_GATE_CONTROL uart_cg_en set", got, gated)
        r = await self._read(fam, "SYS_IN", "S8_UART_GATED", UART_ADDR, code=SLVERR, length=4)
        if r:
            self._expect(fam, "S8 gated UART RDATA[31:0]", r[0].data, 0xBADCAB1E, 0xFFFF_FFFF)
        await self._write(
            fam, "SYS_IN", "S8_CGC_UART_CLR", CLOCK_GATE_CONTROL, CLOCK_GATE_CONTROL_RESET
        )
        got = await self._rd("SETUP", "SEP_IN", "S8_CGC_UART_CLR_RB", CLOCK_GATE_CONTROL)
        self._expect(fam, "S8 CLOCK_GATE_CONTROL uart_cg_en cleared", got, CLOCK_GATE_CONTROL_RESET)
        await self._read(fam, "SYS_IN", "S8_UART_UNGATED", UART_ADDR, code=OKAY, length=4)
        self._cell("AXIFAB-FWIN-BASECFG.S2", "SYS_IN/uart_cg")

        thr = 0xA_5A5A
        await self._write(fam, "SYS_IN", "S8_THR_WR", T_REG, thr)
        got = await self._rd(fam, "SYS_IN", "S8_THR_RD", T_REG)
        self._expect(fam, "S8 SYS_IN threshold readback", got, thr, THR_MASK)
        got = await self._rd("SETUP", "SEP_IN", "S8_THR_SEP_RB", T_REG)
        self._expect(fam, "S8 SEP_IN threshold readback", got, thr, THR_MASK)
        await self._write("SETUP", "SEP_IN", "S8_THR_RESTORE", T_REG, THR_RESET)
        self._cell("AXIFAB-FWIN-BASECFG.S3", "SYS_IN/hangdet")

        await self._sep_entry("SETUP", G_IDX, G_CFG_OFF | EN, G_START, G_END, "S8_G_ON")
        r = await self._read(fam, "SYS_IN", "S8_OLD_GLOBAL_PRE", OLD_GLOBAL_LB)
        if r:
            self._expect(
                fam,
                "S8 LOCAL_BASE at the old global address before the move",
                r[0].data,
                LOCAL_BASE_RESET,
            )
        gb_bresp = await self._write(
            fam, "SYS_IN", "S8_GLOBAL_BASE_MOVE", GLOBAL_BASE_REG, NEW_GLOBAL, code=None
        )
        first = None
        for attempt in range(1, GB_POLL_BOUND + 1):
            r = await self._read(
                fam, "SYS_IN", f"S8_NEW_GLOBAL_POLL{attempt}", NEW_GLOBAL_LB, code=None
            )
            if r and r[0].resp == OKAY:
                first = attempt
                break
        self.poll_waits.append(
            f"GLOBAL_BASE window poll bound={GB_POLL_BOUND} reads, matched at "
            f"{first if first is not None else 'none'}"
        )
        if first is None:
            self.findings[fam].append(
                f"S8 the new global address 0x{NEW_GLOBAL_LB:x} never answered OKAY in "
                f"{GB_POLL_BOUND} reads after the GLOBAL_BASE write (bresp {_rname(gb_bresp)})"
            )
        await self._read(fam, "SYS_IN", "S8_OLD_GLOBAL_POST", OLD_GLOBAL_LB, code=DECERR)
        r = await self._read(fam, "SYS_IN", "S8_NEW_GLOBAL_POST", NEW_GLOBAL_LB, code=OKAY)
        if r:
            self._expect(
                fam, "S8 LOCAL_BASE at the new global address", r[0].data, LOCAL_BASE_RESET
            )
        await self._write(
            fam, "SEP_IN", "S8_GLOBAL_BASE_RESTORE", GLOBAL_BASE_REG, GLOBAL_BASE_RESET
        )
        got = await self._rd(fam, "SEP_IN", "S8_GLOBAL_BASE_RB", GLOBAL_BASE_REG)
        self._expect(fam, "S8 GLOBAL_BASE after the SEP_IN restore", got, GLOBAL_BASE_RESET)
        await self._sep_entry("SETUP", G_IDX, G_CFG_OFF, G_START, G_END, "S8_G_OFF")
        self.notes["gb_bresp"] = _rname(gb_bresp)
        self.notes["first_new_window_txn"] = str(first)
        self._cell("AXIFAB-FWIN-BASECFG.S4", "SYS_IN/global_base")
        await self._live(fam, "S8")
        self._mark("BASE_CONFIG", s)

    async def _scratch(self, tag: str) -> list[int | None]:
        return [
            await self._rd("SETUP", "SEP_IN", f"{tag}_SCRATCH{i}", a) for i, a in enumerate(SCRATCH)
        ]

    async def _allow_burst(self) -> None:
        s = self.sys_count
        fam = "BURST"
        seeds = [0x5C00_0000 | (i << 12) | (0x11 * (i + 1)) for i in range(len(SCRATCH))]
        for i, addr in enumerate(SCRATCH):
            await self._write("SETUP", "SEP_IN", f"S9_SEED{i}", addr, seeds[i])
        ref = await self._scratch("S9_SEED_RB")
        for i, got in enumerate(ref):
            self._expect("SETUP", f"S9 SCRATCH[{i}] seed readback", got, seeds[i], SCRATCH_MASK)

        r = await self._read(fam, "SYS_IN", "S9_SINGLE", SCRATCH[0])
        if r:
            self._expect(fam, "S9 single-beat read through B", r[0].data, seeds[0])
        self._cell("AXIFAB-INFILT-BURST.S1", "SYS_IN/len=0/allow_burst=0")

        for ab in (0, 1):
            if ab:
                await self._write("SETUP", "SEP_IN", "S9_B_AB1", FC(B_IDX), B_CFG1)
                got = await self._rd("SETUP", "SEP_IN", "S9_B_AB1_RB", FC(B_IDX))
                self._expect("SETUP", "S9 entry B allow_burst=1", got, rb(B_CFG1))
                sa = await self._rd("SETUP", "SEP_IN", "S9_B_AB1_SA", SA(B_IDX))
                ea = await self._rd("SETUP", "SEP_IN", "S9_B_AB1_EA", EA(B_IDX))
                cocotb.log.info(
                    "INFO-GRANULE: entry %d START %s END %s at allow_burst=1",
                    B_IDX,
                    _hx(sa),
                    _hx(ea),
                )
            scen = f"AXIFAB-INFILT-BURST.S{2 + ab}"
            before = await self._scratch(f"S9_AB{ab}_PRE")
            r = await self._read(fam, "SYS_IN", f"S9_AB{ab}_RBURST", SCRATCH[0], code=None, beats=4)
            rcodes = [_rname(b.resp) for b in r]
            if not ab and any(b.resp == OKAY for b in r):
                self.findings[fam].append(f"S9 allow_burst=0 read burst admitted: beats {rcodes}")
            if ab and any(b.resp == DECERR for b in r):
                self.findings[fam].append(f"S9 allow_burst=1 read burst refused: beats {rcodes}")
            self._cell(scen, f"SYS_IN/len=3/allow_burst={ab}/rd")
            words = [0xB0B0_0000 | (ab << 8) | i for i in range(4)]
            bresp = await self._write(
                fam,
                "SYS_IN",
                f"S9_AB{ab}_WBURST",
                SCRATCH[0],
                _pack(words),
                beats=4,
                code=DECERR if not ab else None,
            )
            if ab and bresp == DECERR:
                self.findings[fam].append("S9 allow_burst=1 write burst refused with DECERR")
            after = await self._scratch(f"S9_AB{ab}_POST")
            if not ab:
                for i, (b0, a0) in enumerate(zip(before, after)):
                    if b0 is None or a0 != b0:
                        self.findings[fam].append(
                            f"S9 SCRATCH[{i}] {_hx(b0)} -> {_hx(a0)} after the refused write burst"
                        )
            self._cell(scen, f"SYS_IN/len=3/allow_burst={ab}/wr")
            self._obs(
                "OBS-INFILT-BURST",
                allow_burst=ab,
                rresp=",".join(rcodes) or "none",
                rdata=",".join(_hx(b.data) for b in r) or "none",
                bresp=_rname(bresp),
                landing=",".join(_hx(v) for v in after[:4]),
            )

        for ab, cfg_word in ((0, B_CFG0), (1, B_CFG1)):
            await self._write("SETUP", "SEP_IN", f"S9_GRAN{ab}_FC_OFF", FC(B_IDX), cfg_word & ~EN)
            await self._write("SETUP", "SEP_IN", f"S9_GRAN{ab}_SA", SA(B_IDX), GRAN_X)
            await self._write("SETUP", "SEP_IN", f"S9_GRAN{ab}_EA", EA(B_IDX), GRAN_X)
            await self._write("SETUP", "SEP_IN", f"S9_GRAN{ab}_FC", FC(B_IDX), cfg_word)
            got = await self._rd("SETUP", "SEP_IN", f"S9_GRAN{ab}_FC_RB", FC(B_IDX))
            self._expect("SETUP", f"S9 granule entry allow_burst={ab}", got, rb(cfg_word))
            sa = await self._rd("SETUP", "SEP_IN", f"S9_GRAN{ab}_SA_RB", SA(B_IDX))
            ea = await self._rd("SETUP", "SEP_IN", f"S9_GRAN{ab}_EA_RB", EA(B_IDX))
            cocotb.log.info(
                "INFO-GRANULE: START=END=0x%x allow_burst=%d reads back START %s END %s",
                GRAN_X,
                ab,
                _hx(sa),
                _hx(ea),
            )
            vals = await self._scratch(f"S9_GRAN{ab}_REF")
            in8 = GRAN_X & ~(BEAT - 1)
            out8 = in8 + BEAT
            legs = (
                ("in8", in8, OKAY, vals[SCRATCH.index(in8)]),
                ("out8", out8, OKAY if ab else DECERR, vals[SCRATCH.index(out8)]),
                ("out4K", OUT_4K, DECERR, None),
            )
            for name, addr, code, want in legs:
                r = await self._read(fam, "SYS_IN", f"S9_GRAN{ab}_{name}", addr, code=code)
                if code == OKAY and r and want is not None:
                    self._expect(fam, f"S9 granule allow_burst={ab} {name} data", r[0].data, want)
            if ab:
                self._cell("AXIFAB-INFILT-BURST.S5", "SYS_IN/granule4K/in")
                self._cell("AXIFAB-INFILT-BURST.S5", "SYS_IN/granule4K/out")
            else:
                self._cell("AXIFAB-INFILT-BURST.S5", "SYS_IN/granule8/in")
                self._cell("AXIFAB-INFILT-BURST.S5", "SYS_IN/granule8/out")
        await self._sep_entry("SETUP", B_IDX, B_CFG0, B_START, B_END, "S9_B_RESTORE")
        await self._live(fam, "S9")
        self._cell("AXIFAB-INFILT-BURST.S6", "SYS_IN/after-infilt")
        self._mark("ALLOW_BURST", s)

    async def _reset_item(self, op: SmcResetOp, label: str, bound: int = 0, **expect: int):
        item = SmcResetItem(label)
        item.op = op
        if op is SmcResetOp.WAIT_STATE:
            item.timeout_ref_cycles = bound
            for name, value in expect.items():
                setattr(item, f"expect_{name}", value)
        await self.dispatch_reset(item)
        if op is SmcResetOp.WAIT_STATE:
            self.reset_waits.append(
                f"{label} bound={bound} clk_ref_i matched after {item.wait_ref_cycles} "
                f"timed_out={item.timed_out}"
            )
            assert not item.timed_out, (
                f"{label}: reset state {expect} not reached within {bound} clk_ref_i cycles "
                f"(last {item})"
            )
        return item

    async def _shrink(self) -> None:
        s = self.sys_count
        fam = "BASECFG"
        shrink_bresp = await self._write(
            fam, "SYS_IN", "S10_REGION_SIZE_SHRINK", REGION_SIZE_REG, REGION_SIZE_SHRINK, code=None
        )
        await self._read(fam, "SYS_IN", "S10_SYS_BASECFG_RD", LOCAL_BASE_REG, code=DECERR)
        self._cell("AXIFAB-FWIN-BASECFG.S5", "SYS_IN/shrink")
        await self._read(fam, "SEP_IN", "S10_SEP_BASECFG_RD", LOCAL_BASE_REG, code=DECERR)
        self._cell("AXIFAB-FWIN-BASECFG.S5", "SEP_IN/shrink")
        restore = await self._write(
            fam, "SEP_IN", "S10_REGION_SIZE_RESTORE", REGION_SIZE_REG, REGION_SIZE_RESET, code=None
        )
        self._obs(
            "OBS-FWIN-BASECFG",
            gb_bresp=self.notes["gb_bresp"],
            first_new_window_txn=self.notes["first_new_window_txn"],
            shrink_bresp=_rname(shrink_bresp),
            restore_bresp=_rname(restore),
        )
        for port in PORTS:
            assert not self.sampler.pending(port), f"{port} has a transaction outstanding"
        await self._reset_item(SmcResetOp.COOL_RST_LO, "cool_rst_lo")
        await self._reset_item(
            SmcResetOp.WAIT_STATE,
            "cool_primary_asserted",
            RESET_ASSERT_BOUND_REF_CYCLES,
            rst_primary_ref_clk_n=0,
            rst_primary_smc_clk_n=0,
        )
        await self._reset_item(SmcResetOp.COOL_RST_HI, "cool_rst_hi")
        await self._reset_item(
            SmcResetOp.WAIT_STATE,
            "cool_all_released",
            RESET_RELEASE_BOUND_REF_CYCLES,
            **{name: 1 for name in RESET_SAMPLE_FIELDS},
        )
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        self.sampler.take("SEP_IN")
        self.sampler.take("SYS_IN")
        rs = await self._rd(fam, "SEP_IN", "S10_REGION_SIZE_AFTER_RESET", REGION_SIZE_REG)
        self._expect(fam, "S10 REGION_SIZE after the primary reset", rs, REGION_SIZE_RESET)
        await self._sep_entry("SETUP", E_IDX, E_CFG, E_START, E_END, "S10_REARM")
        await self._live(fam, "S10")
        self._mark("SHRINK", s)

    # ------------------------------------------------------------------ body

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.env.axi_monitor.expected_decerr_addrs.update(
            {FC(L_IDX), SA(L_IDX), EA(L_IDX), LOCAL_BASE_REG, REGION_SIZE_REG}
        )
        self.sampler = SmcPortHandshakeSampler(dut)
        cocotb.start_soon(self.sampler.run())
        try:
            await self._admit()
            await self._reads()
            await self._unlocked()
            await self._lowest_hit()
            await self._prelock()
            await self._locked()
            await self._self_deny()
            await self._base_config()
            await self._allow_burst()
            await self._shrink()
        finally:
            self.sampler.stop = True
        for port in PORTS:
            stray = self.sampler.pending(port)
            if stray:
                self.findings["SETUP"].append(f"{port}: handshakes {stray} after the last access")
        if self.sampler.unresolved:
            self.findings["SETUP"].append(
                f"{self.sampler.unresolved_count} X samples on handshake lines, first "
                f"{self.sampler.unresolved}"
            )
        rst = dut.rst_primary_smc_clk_no.value
        for port in PORTS:
            cocotb.log.info(
                "INFO-CLASSIFY: port=%s unanswered=0; ocah_axi_sva fires are simulator records "
                "in this log; last %s; rst_primary_smc_clk_no=%s",
                port,
                self.sampler.describe(port),
                int(rst) if rst.is_resolvable else "X",
            )
        self._report()

    def _report(self) -> None:
        for scen, cells in PLANNED_CELLS.items():
            for cell in cells:
                n = self.cells.get((scen, cell), 0)
                cocotb.log.info("INFO-CELL: %s %s driven=%d", scen, cell, n)
                if not n:
                    self.findings["SETUP"].append(f"planned cell {scen} {cell} not driven")
        lines = {
            "READ": (
                "CHK-FWIN-READ",
                f"{self.graded['READ']} window reads OKAY with stated values (entry {J_IDX} "
                f"programmed fields with data_bus_width 0x3, entry {UNTOUCHED_IDX} "
                f"0x{FC_RESET:016x}/0x{SA_RESET:x}/0x{EA_RESET:x}, locked entry {L_IDX} with "
                f"locked=1 and its range, GLOBAL_BASE 0x{GLOBAL_BASE_RESET:x}, LOCAL_BASE "
                f"0x{LOCAL_BASE_RESET:x}, REGION_SIZE 0x{REGION_SIZE_RESET:x}), E disabled DECERR, "
                "re-enabled OKAY",
            ),
            "WRUNLOCKED": (
                "CHK-FWIN-WRUNLOCKED",
                f"RO field kept (data_bus_width 0x{DBW_RESET >> DBW_BP:x}, non-field bits 0), "
                f"deny entries {J_IDX} below and {H_IDX} above E={E_IDX} landed as programmed "
                f"(KEY-FWIN-LANDED), T decided by entry {J_IDX} then by E (KEY-FWIN-DECIDER), "
                f"lowest-hit decode matches the read-back configuration in "
                f"{self.lowest_hit_accesses} accesses (outside access OKAY)",
            ),
            "WRLOCKED": (
                "CHK-FWIN-WRLOCKED",
                f"pre-lock SEP_IN write OKAY, {self.locked_writes - 1} locked writes DECERR "
                f"(cg 0 and 1, lock clear, AxLEN=2 burst, SEP_IN) with every W beat and one B, "
                f"L unchanged in {self.locked_reads} reads, window read OKAY",
            ),
            "SELFDENY": (
                "CHK-FWIN-SELFDENY",
                f"{self.selfdeny_writes} self-deny writes landed in E (KEY-FWIN-LANDED), next "
                f"accesses decided by E, the default block, then F={F_IDX} (KEY-FWIN-DECIDER), "
                f"decode matches the read-back configuration ({self.model_snapshots} snapshots of "
                f"{NUM_ENTRIES} entries), restore OKAY",
            ),
            "BASECFG": (
                "CHK-FWIN-BASECFG",
                "LOCAL_BASE kept, UART gate SLVERR 0xBADCAB1E then OKAY, threshold readback, "
                f"global move decoded (old DECERR, new OKAY 0x{LOCAL_BASE_RESET:x}), shrink "
                f"DECERR on SYS_IN and SEP_IN, REGION_SIZE 0x{REGION_SIZE_RESET:x} after recovery",
            ),
            "BURST": (
                "CHK-INFILT-BURST",
                "single OKAY, allow_burst 0 bursts DECERR unchanged, allow_burst 1 bursts reach "
                "target, granules as stated (8 B and 4 KiB), liveness OKAY "
                f"0x{LOCAL_BASE_RESET:016x}",
            ),
        }
        failed = []
        setup = self.findings["SETUP"]
        for fam in FAMILIES:
            for finding in self.findings[fam]:
                cocotb.log.info("INFO-FINDING: %s %s", fam, finding)
        for fam, (chk, text) in lines.items():
            if self.findings[fam] or setup:
                failed.append(
                    f"{fam}: {len(self.findings[fam])} finding(s)"
                    + (f", first: {self.findings[fam][0]}" if self.findings[fam] else "")
                )
                continue
            cocotb.log.info("%s: %s (%d graded accesses)", chk, text, self.graded[fam])
        if setup:
            failed.append(f"SETUP: {len(setup)} finding(s), first: {setup[0]}")
        self.failed = failed

    def raise_findings(self) -> None:
        assert not self.failed, "inbound window findings: " + " | ".join(self.failed)

    def log_timeout_paths(self, prefix: str = "CHK-TIMEOUT-PATHS") -> None:
        cocotb.log.info(
            "%s: %d bounded waits, %d expired: wait_fuse_sense_done sub-waits (tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n) bounded %d clk_smc_i rises each, before the "
            "first access and after the primary reset, last %s; %d inbound accesses each bounded "
            "%d ns by First(task, Timer), the expiry path printing INFO-CLASSIFY (last AR/AW/W/R/B "
            "handshake of the port and rst_primary_smc_clk_no) and failing the leaf, longest answer "
            "%d ns, driver backup timeout %d ns; polls [%s] failing the leaf on expiry; reset waits "
            "[%s] each failing on expiry with the last sampled reset state; last access %s",
            prefix,
            self.waits + 6 + len(self.reset_waits) + len(self.poll_waits),
            self.expired,
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.waits,
            ACCESS_BOUND_NS,
            self.max_wait_ns,
            DRIVER_TIMEOUT_NS,
            "; ".join(self.poll_waits) or "none reached",
            "; ".join(self.reset_waits) or "none reached",
            self.last_access,
        )

    def nonvac_fence(self, check: bool = True) -> None:
        terms = tuple(t for t, _time, _n, _p in self.fence)
        times = [time for _t, time, _n, _p in self.fence]
        problems = []
        if terms != FENCE:
            problems.append(f"fence terms {terms}, want {FENCE}")
        if not all(b > a for a, b in zip(times, times[1:])):
            problems.append(f"fence times not increasing: {times}")
        for term, _time, n, planned in self.fence:
            if n <= 0 or n < planned:
                problems.append(f"{term}: {n} SYS_IN accesses against {planned} planned")
        detail = ", ".join(f"{t}@{time}ps={n}/{p}" for t, time, n, p in self.fence)
        if problems:
            cocotb.log.info("INFO-NONVAC: fence broken (%s): %s", detail, "; ".join(problems))
            if check:
                raise AssertionError("CHK-NONVAC fence broken: " + "; ".join(problems))
            return
        if not check:
            return
        cocotb.log.info("CHK-NONVAC: %s (time and count per term: %s)", " < ".join(FENCE), detail)
