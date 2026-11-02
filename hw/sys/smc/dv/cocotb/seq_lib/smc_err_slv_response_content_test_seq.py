# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Error-subordinate response content seen from SEP_IN, SYS_IN and JTAG_IN.

Spec sources: memmap.adoc Address Space Organization (gaps, outside both apertures,
REGION_SIZE, gated windows); fabric.adoc Traffic Subordinates; clk_rst.adoc peripheral
access gates; doc/trm memory_map.adoc Decode Response Codes; the generated SMC memory map
(apertures, decoded extents, sub-block placement); smc_base_config, reset_unit and
misc_wrap register descriptions; the AXI rules transcribed in the ocah_axi_sva header.

Every response is graded from a passive per-port sampler of the tb_top R, B, AR, AW and
W handshakes, because the bench item carries one merged response code. Values the
contract leaves open (second words, burst beats, narrow lanes, the straddling unit,
merged split-slot answers) are printed as OBS lines that name their finding and are
never compared.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import cocotb
from cocotb.triggers import First, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    AVS_CG_EN,
    CLOCK_GATE_CONTROL,
    CLOCK_GATE_CONTROL_RESET,
    GLOBAL_BASE_RESET,
    GPIO_INTF_NUM,
    GPIO_INTF_STRIDE,
    I2C_CG_EN,
    I3C_CG_EN,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    SPM_MEMORY_BASE,
    TELEMETRY_CG_EN,
    UART_CG_EN,
    generated_decoded_extent,
    generated_window,
    smc_addr,
    smc_indexed_addr,
)
from .smc_csr_seq_utils import SmcCsrSeq
from .smc_output_fabric_vip_utils import (
    INBOUND0_END,
    INBOUND0_FILTER_CONFIG,
    INBOUND0_START,
    PASS_ALL_CONFIG,
    output_responder_counts,
)

_SMC_REG_PY = Path(__file__).resolve().parents[3] / "regs" / "gen" / "py"
if str(_SMC_REG_PY) not in sys.path:
    sys.path.insert(0, str(_SMC_REG_PY))

from smc_memory_map import VIEWS as _MEMORY_MAP_VIEWS  # noqa: E402

OKAY, EXOKAY, SLVERR, DECERR = 0, 1, 2, 3
_RESP = {OKAY: "OKAY", EXOKAY: "EXOKAY", SLVERR: "SLVERR", DECERR: "DECERR", None: "X"}

# memmap.adoc:60-74, TRM Decode Response Codes: the word a 32-bit read of an error
# location returns in either half of the bus.
ERR_WORD = 0xBADCAB1E
WRITE_WORD = 0x5A5A_A5A5_A5A5_5A5A
SPLIT_WRITE_WORD = 0x5A
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
ACCESS_BOUND_NS = 100_000
DRIVER_TIMEOUT_NS = 2 * ACCESS_BOUND_NS
PAGE = 0x1000
BEAT = 8
READ_BURST_LENS = (1, 3, 15, 255)
WRITE_BURST_LENS = (1, 15, 255)
NARROW = tuple((0, off) for off in range(8)) + tuple((1, off) for off in (0, 2, 4, 6))

PORTS = ("SEP_IN", "SYS_IN", "JTAG_IN")
INBOUND_PORTS = ("SEP_IN", "SYS_IN")
PREFIX = {"SEP_IN": "s_axi", "SYS_IN": "sys_axi", "JTAG_IN": "jtag_axi"}
# JTAG_IN carries a 2-bit ID; SEP_IN and SYS_IN carry 6 bits.
AXI_ID = {"SEP_IN": 0x15, "SYS_IN": 0x2A, "JTAG_IN": 0x2}

LOCAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")

# AXIFAB-ERR-REGIONSIZE.S3: at REGION_SIZE 1 MiB the scratchpad RAM aperture
# (BASE+0x6_0000..0x15_FFFF) straddles BASE+REGION_SIZE.
REGION_SIZE_STRADDLE = 0x10_0000
STRADDLE_ADDR = SPM_MEMORY_BASE
STRADDLE_D0 = 0x0D0D_0D0D_5EED_0000
STRADDLE_D1 = {"SEP_IN": 0x0D1D_1D1D_5EED_0001, "SYS_IN": 0x0D1D_1D1D_5EED_0011}
STRADDLE_D2 = {"SEP_IN": 0x0D2D_2D2D_5EED_0002, "SYS_IN": 0x0D2D_2D2D_5EED_0012}

# Split 8-byte slots: +0 is the last live 32-bit register of the island, +4 is past
# its extent. Reset values: reset_unit.adoc:213-220, smc_base_config.adoc:149-157.
# NDMRESET_CLUSTER_COUNT is read-only and reports the connected clusters
# (misc_wrap.adoc:117), a value no pinned source states: None marks it OBS-only.
SPLIT_SLOTS = (
    (
        "reset_unit",
        smc_addr("SMC_TOP_SMC_RESET_UNIT_ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_BASE_ADDR"),
        0x0,
    ),
    (
        "misc_wrap",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_CLUSTER_COUNT_BASE_ADDR"),
        None,
    ),
    (
        "base_config",
        smc_addr("SMC_TOP_SMC_BASE_CONFIG_HANG_DET_DATA_ACCEL_TIMEOUT_THRESHOLD_BASE_ADDR"),
        0x1000,
    ),
)

# Total required cells per family in the feature list (sum over its scenarios).
PLANNED_CELLS = {
    "OUTSIDE": 56,
    "REGIONSIZE": 26,
    "GAP": 252,
    "DEBUGWIN": 108,
    "PASTEXT64": 294,
    "PASTEXT32": 84,
    "MISCHOLE": 144,
    "GPIOPAST": 84,
    "CLKGATE": 210,
    "SPLITSLOT": 39,
}

FENCE = (
    "ADMIT",
    "SINGLE_READS",
    "WORD_PAIRS",
    "SINGLE_WRITES",
    "READ_BURSTS",
    "WRITE_BURSTS",
    "NARROW",
    "LIVENESS",
    "STRADDLE",
    "GATE_REDIRECT",
    "SPLIT_SLOTS",
)
PHASE_STEP = dict(zip(FENCE, ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")))
PHASE_KIND = {
    "SINGLE_READS": "single",
    "WORD_PAIRS": "pair",
    "SINGLE_WRITES": "write",
    "READ_BURSTS": "rburst",
    "WRITE_BURSTS": "wburst",
    "NARROW": "narrow",
    "LIVENESS": "live",
}


def _rname(code: int | None) -> str:
    return _RESP.get(code, str(code))


def _hl(data: int | None) -> str:
    if data is None:
        return "X"
    return f"{(data >> 32) & 0xFFFF_FFFF:08x}_{data & 0xFFFF_FFFF:08x}"


def _rows() -> list[dict]:
    return list(_MEMORY_MAP_VIEWS["smc-components"]["rows"])


def _gap_range(offset: int) -> tuple[int, int]:
    """Offsets from LOCAL_BASE of the space between the two unit apertures around ``offset``."""
    addr = LOCAL_BASE_RESET + offset
    rows = _rows()
    assert not any(r["base"] <= addr <= r["end"] for r in rows), (
        f"BASE+0x{offset:x} lies inside a unit aperture of the generated map"
    )
    below = max(r["end"] for r in rows if r["end"] < addr)
    above = min(r["base"] for r in rows if r["base"] > addr)
    return below + 1 - LOCAL_BASE_RESET, above - 1 - LOCAL_BASE_RESET


def _past_extent(unit: str) -> tuple[int, int, int]:
    """(first full slot past the extent, last slot of the aperture, aperture end) offsets."""
    first, last = generated_window(unit)
    past = (first + generated_decoded_extent(unit) + BEAT - 1) & ~(BEAT - 1)
    return past, last & ~(BEAT - 1), last


def _misc_hole(addr: int) -> tuple[int, int]:
    """Absolute range of the misc-wrapper hole holding ``addr`` (between its sub-blocks)."""
    subs = sorted(
        (
            smc_addr(f"SMC_TOP_SMC_MISC_WRAP_{name}_BASE_ADDR"),
            smc_addr(f"SMC_TOP_SMC_MISC_WRAP_{name}_SIZE"),
        )
        for name in ("SCRATCH_COLD", "SCRATCH_COLD_WARM", "CHIP_CONFIG", "NDM_RESET")
    )
    for (b0, s0), (b1, _s1) in zip(subs, subs[1:]):
        if b0 + s0 <= addr < b1:
            return b0 + s0, b1 - 1
    raise AssertionError(f"0x{addr:x} is not between two misc-wrapper sub-blocks")


@dataclass(frozen=True)
class Target:
    tag: str
    addr: int
    lo: int
    hi: int


@dataclass(frozen=True)
class Location:
    cell: str
    targets: tuple[Target, ...]


@dataclass
class Family:
    key: str
    chk: str
    obs: str
    sfs: str
    ports: tuple[str, ...]
    code: int
    word_stated: bool
    locations: tuple[Location, ...]
    scen: dict[str, str]
    rburst_lens: tuple[int, ...] = READ_BURST_LENS
    wburst_lens: tuple[int, ...] = WRITE_BURST_LENS
    burst_cells: tuple[str, ...] | None = None
    narrow_cells: tuple[str, ...] | None = None
    gate_mask: int = 0
    cells: dict[str, int] = field(default_factory=dict)
    not_drivable: dict[str, str] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    graded: int = 0

    def locs(self, kind: str) -> tuple[Location, ...]:
        if kind in ("rburst", "wburst") and self.burst_cells is not None:
            return tuple(loc for loc in self.locations if loc.cell in self.burst_cells)
        if kind == "narrow" and self.narrow_cells is not None:
            return tuple(loc for loc in self.locations if loc.cell in self.narrow_cells)
        return self.locations


def _local(off: int, lo: int, hi: int, tag: str = "") -> Target:
    return Target(tag, LOCAL_BASE_RESET + off, LOCAL_BASE_RESET + lo, LOCAL_BASE_RESET + hi)


def _families() -> list[Family]:
    full = {"single": "S1", "pair": "S2", "write": "S3", "rburst": "S4", "wburst": "S5"}
    full7 = dict(full, narrow="S6", live="S7")
    full6 = dict(full, live="S6")

    above = GLOBAL_BASE_RESET + REGION_SIZE_RESET
    below = GLOBAL_BASE_RESET - PAGE
    for addr in (above, below):
        for base in (LOCAL_BASE_RESET, GLOBAL_BASE_RESET):
            assert not base <= addr < base + REGION_SIZE_RESET, f"0x{addr:x} is inside an aperture"
    assert above < LOCAL_BASE_RESET, "the above-global range is bounded by LOCAL_BASE"
    outside = Family(
        "OUTSIDE",
        "CHK-ERRC-OUTSIDE",
        "OBS-ERRC-OUTSIDE",
        "SF-002,SF-004,SF-005,SF-006,SF-027",
        INBOUND_PORTS,
        DECERR,
        False,
        (
            Location("above-global", (Target("", above, above, LOCAL_BASE_RESET - 1),)),
            Location("below-global", (Target("", below, 0, GLOBAL_BASE_RESET - 1),)),
        ),
        full7,
    )

    units = (
        ("plic", "smc_cluster_plic"),
        ("clint", "smc_cluster_clint"),
        ("beu0", "smc_cluster_core0_beu"),
    )
    rs_locs = []
    for cell, unit in units:
        first, last = generated_window(unit)
        assert first >= REGION_SIZE_RESET, f"{unit} lies below the reset REGION_SIZE"
        rs_locs.append(Location(cell, (_local(first, first, last),)))
    regionsize = Family(
        "REGIONSIZE",
        "CHK-ERRC-REGIONSIZE",
        "OBS-ERRC-REGIONSIZE",
        "SF-003,SF-004,SF-005,SF-006",
        INBOUND_PORTS,
        DECERR,
        False,
        tuple(rs_locs),
        {
            "single": "S1",
            "write": "S2",
            "rburst": "S4",
            "wburst": "S4",
            "narrow": "S5",
            "live": "S6",
        },
        rburst_lens=(3, 255),
        wburst_lens=(3, 255),
        burst_cells=("plic",),
        narrow_cells=("clint",),
    )

    gap_locs = []
    for off in (0x1868, 0xC000, 0x1_7000, 0x3_8300, 0x16_4000, 0x40_6548):
        lo, hi = _gap_range(off)
        targets = tuple(
            Target(name, base + off, base + lo, base + hi)
            for name, base in (("LOCAL", LOCAL_BASE_RESET), ("GLOBAL", GLOBAL_BASE_RESET))
        )
        gap_locs.append(Location(f"gap-0x{off:X}", targets))
    gap = Family(
        "GAP",
        "CHK-ERRC-GAP",
        "OBS-ERRC-GAP",
        "SF-004,SF-005,SF-006,SF-020",
        PORTS,
        DECERR,
        True,
        tuple(gap_locs),
        full7,
    )

    dbg_first, dbg_last = generated_window("debug_module")
    debugwin = Family(
        "DEBUGWIN",
        "CHK-ERRC-DEBUGWIN",
        "OBS-ERRC-DEBUGWIN",
        "SF-004,SF-005",
        PORTS,
        DECERR,
        True,
        tuple(
            Location(f"dbg-0x{off:X}", (_local(off, dbg_first, dbg_last),))
            for off in (dbg_first, dbg_first + 0x400, (dbg_last & ~(BEAT - 1)))
        ),
        full6,
    )

    def _past_family(key, units, sfs) -> Family:
        locs = []
        for cell, unit in units:
            past, last_slot, end = _past_extent(unit)
            locs.append(
                Location(
                    cell,
                    (_local(past, past, end, "FIRST"), _local(last_slot, past, end, "LAST")),
                )
            )
        return Family(
            key,
            f"CHK-ERRC-{key}",
            f"OBS-ERRC-{key}",
            sfs,
            PORTS,
            DECERR,
            True,
            tuple(locs),
            full7,
        )

    pastext64 = _past_family(
        "PASTEXT64",
        (
            ("cpu_ctrl", "smc_cpu_ctrl"),
            ("base_config", "smc_base_config"),
            ("alias_remap", "smc_alias_remap"),
            ("mmode_remap", "smc_mmode_remap"),
            ("xvisor_remap", "smc_xvisor_remap"),
            ("ib_filter", "smc_inbound_filter_ctrl"),
            ("ob_filter", "smc_outbound_filter_ctrl"),
        ),
        "SF-004,SF-005,SF-006",
    )
    pastext32 = _past_family(
        "PASTEXT32",
        (("reset_unit", "smc_reset_unit"), ("misc_wrap", "smc_misc_wrap")),
        "SF-004,SF-005,SF-006,SF-010",
    )

    misc_base = smc_addr("SMC_TOP_SMC_MISC_WRAP_BASE_ADDR")
    hole_locs = []
    for off in (0x20, 0xA0, 0x110, 0x1F8):
        lo, hi = _misc_hole(misc_base + off)
        hole_locs.append(Location(f"hole-0x{off:X}", (Target("", misc_base + off, lo, hi),)))
    mischole = Family(
        "MISCHOLE",
        "CHK-ERRC-MISCHOLE",
        "OBS-ERRC-MISCHOLE",
        "SF-004,SF-005,SF-010",
        PORTS,
        DECERR,
        True,
        tuple(hole_locs),
        full6,
    )

    gpio_first, gpio_last = generated_window("gpio_intf")
    gpio_past = gpio_first + GPIO_INTF_NUM * GPIO_INTF_STRIDE
    gpiopast = Family(
        "GPIOPAST",
        "CHK-ERRC-GPIOPAST",
        "OBS-ERRC-GPIOPAST",
        "SF-004,SF-005,SF-006",
        PORTS,
        DECERR,
        True,
        tuple(
            Location(f"gpio-0x{off - gpio_first:X}", (_local(off, gpio_past, gpio_last),))
            for off in (gpio_past, gpio_last & ~(BEAT - 1))
        ),
        full7,
    )

    gated = (
        ("avsbus", "smc_avsbus_controller", AVS_CG_EN),
        ("i2c", "smc_i2c_wrap", I2C_CG_EN),
        ("i3c", "oca_i3c_wrap", I3C_CG_EN),
        ("telemetry", "smc_telemetry_receiver_wrap", TELEMETRY_CG_EN),
        ("uart", "smc_uart_wrap", UART_CG_EN),
    )
    gate_locs = []
    gate_mask = 0
    for cell, unit, mask in gated:
        first, _last = generated_window(unit)
        gate_locs.append(
            Location(cell, (_local(first, first, first + generated_decoded_extent(unit) - 1),))
        )
        gate_mask |= mask
    clkgate = Family(
        "CLKGATE",
        "CHK-ERRC-CLKGATE",
        "OBS-ERRC-CLKGATE",
        "SF-004,SF-005,SF-006",
        PORTS,
        SLVERR,
        True,
        tuple(gate_locs),
        dict(full, narrow="S6"),
        gate_mask=gate_mask,
    )
    return [
        outside,
        regionsize,
        gap,
        debugwin,
        pastext64,
        pastext32,
        mischole,
        gpiopast,
        clkgate,
    ]


GATED_UNITS = (
    ("avsbus", AVS_CG_EN),
    ("i2c", I2C_CG_EN),
    ("i3c", I3C_CG_EN),
    ("telemetry", TELEMETRY_CG_EN),
    ("uart", UART_CG_EN),
)


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
    """Record every AR, AW, W, R and B handshake of the three inbound ports per clk_smc_i edge."""

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
        self.handles = {
            p: {
                name: getattr(dut, f"{PREFIX[p]}_{name}")
                for name in (
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
            }
            for p in PORTS
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
                addr = "X" if hs.addr is None else f"0x{hs.addr:x}"
                parts.append(
                    f"{chan}=addr {addr} id {hs.ident} len {hs.length} burst {hs.burst} "
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


class smc_err_slv_response_content_test_seq(SmcCsrSeq):
    """Drive every error location of the nine families from the inbound ports and grade the answers."""

    def __init__(self, name: str = "smc_err_slv_response_content_test_seq") -> None:
        super().__init__(name)
        self.families = _families()
        self.split = Family(
            "SPLITSLOT",
            "CHK-ERRC-SPLITSLOT",
            "OBS-ERRC-SPLITSLOT",
            "SF-004,SF-010",
            PORTS,
            DECERR,
            True,
            (),
            {"live": "S5"},
        )
        self.by_key = {f.key: f for f in self.families}
        self.by_key["SPLITSLOT"] = self.split
        self.sampler: SmcPortHandshakeSampler | None = None
        self.fence: list[tuple[str, int, int, int]] = []
        self.other_findings: list[str] = []
        self.bystanders: list[tuple[str, int, int, int]] = []
        self.responder_base: tuple[int, int] | None = None
        self.fuse_state = "not waited"
        self.waits = 0
        self.max_wait_ns = 0
        self.redirect_cells = 0
        self.failed: list[str] = []

    # ------------------------------------------------------------------ helpers

    def _sequencer(self, port: str):
        return {
            "SEP_IN": self.env.sep_in_axi_agent,
            "SYS_IN": self.env.sys_in_axi_agent,
            "JTAG_IN": self.env.jtag_axi_agent,
        }[port].sequencer

    def _mark(self, term: str, count: int, planned: int) -> None:
        now = int(get_sim_time("ps"))
        self.fence.append((term, now, count, planned))
        cocotb.log.info(
            "INFO-STEP %s %s done at %d ps: %d accesses against %d planned",
            PHASE_STEP[term],
            term,
            now,
            count,
            planned,
        )

    async def _issue(
        self,
        port: str,
        label: str,
        addr: int,
        *,
        write: bool,
        length: int = BEAT,
        beats: int = 1,
        wdata: int = 0,
    ) -> tuple[SmcSysAxiItem, dict[str, list[_Hs]]]:
        """Issue one access on ``port`` under a bounded wait; return the item and its handshakes."""
        sampler = self.sampler
        assert sampler is not None
        stray = sampler.pending(port)
        if stray:
            self.other_findings.append(
                f"{port}: handshakes {stray} arrived with no access outstanding before {label}"
            )
            sampler.take(port)
        item = SmcSysAxiItem(f"{port.lower()}_{label}")
        item.op = SmcSysAxiOp.WRITE if write else SmcSysAxiOp.READ
        item.addr = addr
        item.length = length
        item.beats = beats
        item.burst = 1
        item.wdata = wdata
        item.axi_id = AXI_ID[port]
        item.capture_resp_id = beats == 1
        item.timeout_ns = DRIVER_TIMEOUT_NS
        item.allow_error = True
        start = int(get_sim_time("ns"))
        task = cocotb.start_soon(
            _OneShot(item, f"{item.get_name()}_os").start(self._sequencer(port))
        )
        await First(task, Timer(ACCESS_BOUND_NS, unit="ns"))
        self.waits += 1
        if not task.done():
            rst = cocotb.top.rst_primary_smc_clk_no.value
            level = int(rst) if rst.is_resolvable else "X"
            cocotb.log.info(
                "INFO-CLASSIFY: unanswered-transaction design-side port=%s %s %s 0x%x beats=%d "
                "bound=%d ns expired; last %s; rst_primary_smc_clk_no=%s",
                port,
                label,
                "write" if write else "read",
                addr,
                beats,
                ACCESS_BOUND_NS,
                sampler.describe(port),
                level,
            )
            raise AssertionError(
                f"{port} {label} @ 0x{addr:x} unanswered after {ACCESS_BOUND_NS} ns "
                f"(last {sampler.describe(port)}, rst_primary_smc_clk_no={level})"
            )
        await task
        self.max_wait_ns = max(self.max_wait_ns, int(get_sim_time("ns")) - start)
        self.accesses += 1
        return item, sampler.take(port)

    def _check_addr_phase(
        self, fam: Family, ctx: str, hs: dict, chan: str, addr: int, beats: int, ident: int
    ) -> None:
        got = hs[chan]
        if len(got) != 1:
            fam.findings.append(f"{ctx}: {len(got)} {chan.upper()} handshakes, want 1")
            return
        a = got[0]
        if (a.addr, a.ident, a.length, a.burst) != (addr, ident, beats - 1, 1):
            fam.findings.append(
                f"{ctx}: {chan.upper()} addr/id/len/burst {a.addr}/{a.ident}/{a.length}/{a.burst}, "
                f"want 0x{addr:x}/{ident}/{beats - 1}/1"
            )

    def _check_read(
        self,
        fam: Family,
        ctx: str,
        port: str,
        item: SmcSysAxiItem,
        hs: dict,
        beats: int,
        code: int | None,
    ) -> list[_Hs]:
        ident = AXI_ID[port]
        self._check_addr_phase(fam, ctx, hs, "ar", item.addr, beats, ident)
        r = hs["r"]
        if hs["aw"] or hs["w"] or hs["b"]:
            fam.findings.append(f"{ctx}: write-channel handshakes during a read {sorted(hs)}")
        if len(r) != beats:
            fam.findings.append(f"{ctx}: {len(r)} R beats, want {beats}")
        for i, beat in enumerate(r):
            if beat.ident != ident:
                fam.findings.append(f"{ctx}: beat {i} RID {beat.ident}, want {ident}")
            if beat.last != (1 if i == beats - 1 else 0):
                fam.findings.append(f"{ctx}: beat {i} RLAST {beat.last}")
            if beat.resp is None or beat.resp == EXOKAY:
                fam.findings.append(f"{ctx}: beat {i} RRESP {_rname(beat.resp)}")
            elif code is not None and beat.resp != code:
                fam.findings.append(
                    f"{ctx}: beat {i} RRESP {_rname(beat.resp)}, want {_rname(code)}"
                )
        if beats == 1 and item.rid is not None and item.rid != ident:
            fam.findings.append(f"{ctx}: captured RID {item.rid}, want {ident}")
        fam.graded += 1
        return r

    def _check_write(
        self,
        fam: Family,
        ctx: str,
        port: str,
        item: SmcSysAxiItem,
        hs: dict,
        beats: int,
        code: int | None,
    ) -> int | None:
        ident = AXI_ID[port]
        self._check_addr_phase(fam, ctx, hs, "aw", item.addr, beats, ident)
        if hs["ar"] or hs["r"]:
            fam.findings.append(f"{ctx}: read-channel handshakes during a write")
        w = hs["w"]
        if len(w) != beats:
            fam.findings.append(f"{ctx}: {len(w)} W beats accepted, want {beats}")
        for i, beat in enumerate(w):
            if beat.last != (1 if i == beats - 1 else 0):
                fam.findings.append(f"{ctx}: W beat {i} WLAST {beat.last}")
        b = hs["b"]
        if len(b) != 1:
            fam.findings.append(f"{ctx}: {len(b)} B responses, want 1")
            return None
        if b[0].ident != ident:
            fam.findings.append(f"{ctx}: BID {b[0].ident}, want {ident}")
        if b[0].resp is None or b[0].resp == EXOKAY or (code is not None and b[0].resp != code):
            want = _rname(code) if code is not None else "not EXOKAY"
            fam.findings.append(f"{ctx}: BRESP {_rname(b[0].resp)}, want {want}")
        if item.bid is not None and item.bid != ident:
            fam.findings.append(f"{ctx}: captured BID {item.bid}, want {ident}")
        fam.graded += 1
        return b[0].resp

    def _obs_beats(self, fam: Family, cell: str, addr: int, r: list[_Hs]) -> None:
        """One OBS line per run of identical beats, so every beat's code and data is recorded."""
        i = 0
        while i < len(r):
            j = i
            while j + 1 < len(r) and (r[j + 1].resp, r[j + 1].data) == (r[i].resp, r[i].data):
                j += 1
            span = f"{i}" if i == j else f"{i}-{j}"
            cocotb.log.info(
                "%s: cell=%s addr=0x%x rresp=%s rdata=%s beat=%s sf=%s",
                fam.obs,
                cell,
                addr,
                _rname(r[i].resp),
                _hl(r[i].data),
                span,
                fam.sfs,
            )
            i = j + 1

    def _cell(self, fam: Family, kind: str, cell: str) -> None:
        name = f"{fam.scen[kind]} {cell}"
        fam.cells[name] = fam.cells.get(name, 0) + 1

    def _word(self, fam: Family, ctx: str, data: int | None, upper: bool) -> None:
        if not fam.word_stated:
            return
        if data is None:
            fam.findings.append(f"{ctx}: RDATA X")
            return
        word = (data >> 32) & 0xFFFF_FFFF if upper else data & 0xFFFF_FFFF
        if word != ERR_WORD:
            half = "63:32" if upper else "31:0"
            fam.findings.append(f"{ctx}: RDATA[{half}] 0x{word:08x}, want 0x{ERR_WORD:08x}")

    @staticmethod
    def _place(t: Target, beats: int) -> tuple[int | None, int]:
        """Start of an INCR burst holding ``t.addr`` inside its error range and its 4 KiB page."""
        total = beats * BEAT
        page_lo = t.addr & ~(PAGE - 1)
        lo = max(t.lo, page_lo)
        hi = min(t.hi, page_lo + PAGE - 1)
        start = min(t.addr, hi + 1 - total) & ~(BEAT - 1)
        if start < lo or start > t.addr or start + total - 1 > hi:
            return None, hi - lo + 1
        return start, hi - lo + 1

    def _plan_count(self, kind: str) -> int:
        n = 0
        for fam in self.families:
            if kind not in fam.scen:
                continue
            for _port in fam.ports:
                if kind == "live" and fam.key == "REGIONSIZE":
                    n += 1
                    continue
                for loc in fam.locs(kind):
                    if kind == "live":
                        n += 1
                        continue
                    for t in loc.targets:
                        if kind == "single" or kind == "write":
                            n += 1
                        elif kind == "pair":
                            n += 2
                        elif kind == "narrow":
                            n += len(NARROW)
                        else:
                            lens = fam.rburst_lens if kind == "rburst" else fam.wburst_lens
                            n += sum(1 for ln in lens if self._place(t, ln + 1)[0] is not None)
        return n

    def _consume_sep_csr(self, label: str, write: bool) -> None:
        """Take the SEP_IN handshakes of one CSR helper access off the sampler."""
        if self.sampler is None:
            return
        hs = self.sampler.take("SEP_IN")
        want = {"aw": 1, "w": 1, "b": 1} if write else {"ar": 1, "r": 1}
        got = {c: len(v) for c, v in hs.items() if v}
        if got != want:
            self.other_findings.append(f"SEP_IN CSR {label}: handshakes {got}, want {want}")

    async def csr_read(self, name, addr, expected=None, length=4, prot=0):
        value = await super().csr_read(name, addr, expected=expected, length=length, prot=prot)
        self._consume_sep_csr(name, write=False)
        return value

    async def csr_write(self, name, addr, data, length=4, prot=0):
        await super().csr_write(name, addr, data, length=length, prot=prot)
        self._consume_sep_csr(name, write=True)

    # ------------------------------------------------------------ bystanders

    async def _seed_bystanders(self) -> None:
        idx = 0

        async def written(name: str, addr: int, length: int, value: int) -> None:
            await self.csr_write(f"BYST_{name}", addr, value, length=length)
            await self.csr_read(f"BYST_{name}_RB", addr, expected=value, length=length)
            self.bystanders.append((name, addr, length, value))

        for i in range(smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_NUM")):
            idx += 1
            await written(
                f"SCRATCH_COLD{i}",
                smc_indexed_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_SCRATCH_BASE_ADDR", i),
                4,
                0xB75D_0000 | idx,
            )
        for i in range(4):
            idx += 1
            await written(
                f"CPU_CTRL_SCRATCH{i}",
                smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", i),
                4,
                0xB75D_0000 | idx,
            )
        warm_n = smc_addr("SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_NUM")
        idx += 1
        await written(
            f"SCRATCH_COLD_WARM{warm_n - 1}",
            smc_indexed_addr(
                "SMC_TOP_SMC_MISC_WRAP_SCRATCH_COLD_WARM_SCRATCH_BASE_ADDR", warm_n - 1
            ),
            4,
            0xB75D_0000 | idx,
        )
        for name, sym, value in (
            (
                "ALIAS_REMAP7_ATTRS",
                "SMC_TOP_SMC_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR",
                0x0000_00AB_C000_0000,
            ),
            (
                "MMODE_REMAP7_ATTRS",
                "SMC_TOP_SMC_MMODE_REMAP_REGION_REGION_ATTRS_BASE_ADDR",
                0x0000_00AB_C100_0000,
            ),
            (
                "XVISOR_REMAP7_ATTRS",
                "SMC_TOP_SMC_XVISOR_REMAP_REGION_REGION_ATTRS_BASE_ADDR",
                0x0000_00AB_C200_0000,
            ),
        ):
            await written(name, smc_indexed_addr(sym, 7), 8, value)
        for name, sym, value in (
            (
                "INBOUND15_END",
                "SMC_TOP_SMC_INBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR",
                0x0000_00AB_C300_0000,
            ),
            (
                "OUTBOUND15_END",
                "SMC_TOP_SMC_OUTBOUND_FILTER_CTRL_END_ADDR_BASE_ADDR",
                0x0000_00AB_C400_0000,
            ),
        ):
            await written(name, smc_indexed_addr(sym, 15), 8, value)
        await written("SPM_WORD", SPM_MEMORY_BASE + 0x100, 8, 0xB75D_5EED_0000_0100)
        # Read-only or access-filtered last registers: the reference is the value read here.
        for name, addr, length in (
            (
                "CPU_CTRL_DUMMY_ROM_NULL3",
                smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR", 3),
                8,
            ),
            (
                "CHIP_CONFIG_LC_STATE",
                smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_LC_STATE_BASE_ADDR"),
                4,
            ),
            (
                f"GPIO_INTF{GPIO_INTF_NUM - 1}_ACCESS_FILTER",
                smc_indexed_addr("SMC_TOP_GPIO_INTF_ACCESS_FILTER_BASE_ADDR", GPIO_INTF_NUM - 1),
                4,
            ),
        ):
            value = await self.csr_read(f"BYST_{name}_SNAP", addr, length=length)
            self.bystanders.append((name, addr, length, value))
        # S11 grades the split-slot +0 registers that have a stated reset value.
        for cell, addr, _reset in SPLIT_SLOTS:
            value = await self.csr_read(f"BYST_SPLIT_{cell}_SNAP", addr, length=4)
            self.bystanders.append((f"SPLIT_{cell}", addr, 4, value))

    async def _check_bystanders(self, fam: Family, when: str) -> None:
        for name, addr, length, value in self.bystanders:
            got = await self.csr_read(f"BYST_{name}_{fam.key}_{when}", addr, length=length)
            mask = (1 << (8 * length)) - 1
            if got & mask != value:
                fam.findings.append(
                    f"bystander {name} @ 0x{addr:x} = 0x{got & mask:x} after {fam.key} {when}, "
                    f"want 0x{value:x}"
                )
        counts = output_responder_counts(cocotb.top)
        if counts != self.responder_base:
            fam.findings.append(
                f"SYS_OUT responder counts {self.responder_base} -> {counts} after {fam.key} {when}"
            )

    # --------------------------------------------------------------- phases

    async def _gate(self, fam: Family, on: bool) -> None:
        if not fam.gate_mask:
            return
        value = CLOCK_GATE_CONTROL_RESET | fam.gate_mask if on else CLOCK_GATE_CONTROL_RESET
        await self.csr_write(f"CGC_{'SET' if on else 'CLEAR'}_ALL", CLOCK_GATE_CONTROL, value)
        await self.csr_read(
            f"CGC_{'SET' if on else 'CLEAR'}_ALL_RB", CLOCK_GATE_CONTROL, expected=value
        )

    async def _periph_handshakes(self) -> int | None:
        sig = getattr(cocotb.top, "axi_hs_periph", None)
        if sig is None:
            return None
        value = sig.value
        if isinstance(value, int):
            return value
        return int(value) if value.is_resolvable else None

    async def _run_kind(self, kind: str) -> int:
        count = 0
        for fam in self.families:
            if kind not in fam.scen:
                continue
            await self._gate(fam, True)
            for port in fam.ports:
                if kind == "live" and fam.key == "REGIONSIZE":
                    count += await self._live(fam, port, f"{port}/after-regionsize")
                    continue
                for loc in fam.locs(kind):
                    if kind == "live":
                        count += await self._live(fam, port, f"{port}/after-{loc.cell}")
                        continue
                    for t in loc.targets:
                        count += await self._one_kind(fam, kind, port, loc, t)
            await self._gate(fam, False)
            if kind in ("write", "wburst"):
                await self._check_bystanders(fam, kind)
        return count

    async def _one_kind(self, fam: Family, kind: str, port: str, loc: Location, t: Target) -> int:
        cell = f"{port}/{loc.cell}"
        where = f"{fam.key} {cell}{'@' + t.tag if t.tag else ''} 0x{t.addr:x}"
        n = 0
        if kind == "single":
            before = await self._periph_handshakes()
            item, hs = await self._issue(port, f"{fam.key}_SINGLE", t.addr, write=False)
            after = await self._periph_handshakes()
            r = self._check_read(fam, f"{where} 64-bit read", port, item, hs, 1, fam.code)
            if r:
                self._word(fam, f"{where} 64-bit read", r[0].data, upper=False)
            self._obs_beats(fam, cell, t.addr, r)
            if fam.key in ("GAP", "PASTEXT32"):
                delta = "n/a" if before is None or after is None else after - before
                cocotb.log.info(
                    "INFO-PATH: %s periph AXI-Lite link AW/AR handshakes during the read: %s (%s)",
                    where,
                    delta,
                    "SF-020" if fam.key == "GAP" else "SF-010",
                )
            self._cell(fam, kind, cell)
            return 1
        if kind == "pair":
            for half in (0, 4):
                item, hs = await self._issue(
                    port, f"{fam.key}_PAIR{half}", t.addr + half, write=False, length=4
                )
                ctx = f"{where} 32-bit read +{half}"
                r = self._check_read(fam, ctx, port, item, hs, 1, fam.code)
                if r:
                    self._word(fam, ctx, r[0].data, upper=bool(half))
                self._obs_beats(fam, f"{cell}/+{half}", t.addr + half, r)
                self._cell(fam, kind, f"{cell}/+{half}")
                n += 1
            return n
        if kind == "write":
            item, hs = await self._issue(
                port, f"{fam.key}_WRITE", t.addr, write=True, wdata=WRITE_WORD
            )
            self._check_write(fam, f"{where} 64-bit write", port, item, hs, 1, fam.code)
            self._cell(fam, kind, cell)
            return 1
        if kind in ("rburst", "wburst"):
            lens = fam.rburst_lens if kind == "rburst" else fam.wburst_lens
            for ln in lens:
                bcell = f"{cell}/len={ln}"
                start, avail = self._place(t, ln + 1)
                if start is None:
                    cocotb.log.info(
                        "INFO-CELL-NOT-DRIVABLE %s %s@0x%x range=%d",
                        fam.scen[kind],
                        bcell,
                        t.addr,
                        avail,
                    )
                    fam.not_drivable[f"{fam.scen[kind]} {bcell}"] = f"range={avail}"
                    continue
                ctx = f"{where} INCR len={ln} start 0x{start:x}"
                if kind == "rburst":
                    item, hs = await self._issue(
                        port, f"{fam.key}_RBURST{ln}", start, write=False, beats=ln + 1
                    )
                    r = self._check_read(fam, ctx, port, item, hs, ln + 1, None)
                    self._obs_beats(fam, bcell, start, r)
                else:
                    wdata = int.from_bytes(WRITE_WORD.to_bytes(BEAT, "little") * (ln + 1), "little")
                    item, hs = await self._issue(
                        port, f"{fam.key}_WBURST{ln}", start, write=True, beats=ln + 1, wdata=wdata
                    )
                    self._check_write(fam, ctx, port, item, hs, ln + 1, fam.code)
                self._cell(fam, kind, bcell)
                n += 1
            return n
        if kind == "narrow":
            for size, off in NARROW:
                length = 1 << size
                addr = t.addr + off
                item, hs = await self._issue(
                    port, f"{fam.key}_NARROW{size}_{off}", addr, write=False, length=length
                )
                r = self._check_read(
                    fam, f"{where} size={size} +{off}", port, item, hs, 1, fam.code
                )
                lanes = None
                if r and r[0].data is not None:
                    lanes = (r[0].data >> (8 * off)) & ((1 << (8 * length)) - 1)
                cocotb.log.info(
                    "%s: cell=%s/size=%d addr=0x%x rresp=%s lanes=%s bus=%s sf=%s",
                    fam.obs,
                    cell,
                    size,
                    addr,
                    _rname(r[0].resp) if r else "none",
                    "X" if lanes is None else f"0x{lanes:0{2 * length}x}",
                    _hl(r[0].data) if r else "none",
                    fam.sfs,
                )
                n += 1
            self._cell(fam, kind, f"{cell}/size=0")
            self._cell(fam, kind, f"{cell}/size=1")
            return n
        raise ValueError(kind)

    async def _live(self, fam: Family, port: str, cell: str) -> int:
        item, hs = await self._issue(port, f"{fam.key}_LIVE", LOCAL_BASE_REG, write=False)
        ctx = f"{fam.key} {cell} LOCAL_BASE read"
        r = self._check_read(fam, ctx, port, item, hs, 1, OKAY)
        if r and r[0].data != LOCAL_BASE_RESET:
            fam.findings.append(f"{ctx}: RDATA {_hl(r[0].data)}, want 0x{LOCAL_BASE_RESET:016x}")
        fam.cells[f"{fam.scen['live']} {cell}"] = fam.cells.get(f"{fam.scen['live']} {cell}", 0) + 1
        return 1

    async def _straddle(self) -> int:
        fam = self.by_key["REGIONSIZE"]
        n = 0
        await self.csr_write("STRADDLE_D0", STRADDLE_ADDR, STRADDLE_D0, length=8)
        await self.csr_read("STRADDLE_D0_RB", STRADDLE_ADDR, expected=STRADDLE_D0, length=8)
        await self.csr_write("REGION_SIZE_1M", REGION_SIZE_REG, REGION_SIZE_STRADDLE)
        await self.csr_read("REGION_SIZE_1M_RB", REGION_SIZE_REG, expected=REGION_SIZE_STRADDLE)
        for port in ("SYS_IN", "SEP_IN"):
            cell = f"{port}/spm/rs1M"
            item, hs = await self._issue(port, "STRADDLE_RD", STRADDLE_ADDR, write=False)
            r = self._check_read(fam, f"{cell} 64-bit read", port, item, hs, 1, DECERR)
            cocotb.log.info(
                "OBS-ERRC-REGIONSIZE-STRADDLE: port=%s rdata=%s sf=SF-003",
                port,
                _hl(r[0].data) if r else "none",
            )
            item, hs = await self._issue(
                port, "STRADDLE_WR", STRADDLE_ADDR, write=True, wdata=STRADDLE_D1[port]
            )
            self._check_write(fam, f"{cell} 64-bit write", port, item, hs, 1, DECERR)
            fam.cells[f"S3 {cell}"] = 1
            n += 2
        await self.csr_write("REGION_SIZE_RESTORE", REGION_SIZE_REG, REGION_SIZE_RESET)
        await self.csr_read("REGION_SIZE_RESTORE_RB", REGION_SIZE_REG, expected=REGION_SIZE_RESET)
        for port in ("SYS_IN", "SEP_IN"):
            cell = f"{port}/spm/rs16M"
            item, hs = await self._issue(port, "STRADDLE_D0_RE", STRADDLE_ADDR, write=False)
            r = self._check_read(fam, f"{cell} re-read", port, item, hs, 1, OKAY)
            if r and r[0].data != STRADDLE_D0:
                fam.findings.append(
                    f"{cell}: re-read {_hl(r[0].data)}, want D0 0x{STRADDLE_D0:016x}"
                )
            n += 1
        for port in ("SYS_IN", "SEP_IN"):
            cell = f"{port}/spm/rs16M"
            d2 = STRADDLE_D2[port]
            item, hs = await self._issue(port, "STRADDLE_D2", STRADDLE_ADDR, write=True, wdata=d2)
            self._check_write(fam, f"{cell} write D2", port, item, hs, 1, OKAY)
            item, hs = await self._issue(port, "STRADDLE_D2_RB", STRADDLE_ADDR, write=False)
            r = self._check_read(fam, f"{cell} read D2", port, item, hs, 1, OKAY)
            if r and r[0].data != d2:
                fam.findings.append(f"{cell}: read {_hl(r[0].data)}, want D2 0x{d2:016x}")
            fam.cells[f"S3 {cell}"] = 1
            n += 2
            await self._live(fam, port, f"{port}/after-regionsize-restore")
            n += 1
        return n

    async def _gate_redirect(self) -> int:
        fam = self.by_key["CLKGATE"]
        loc_of = {loc.cell: loc for loc in fam.locations}
        n = 0
        for cell, mask in GATED_UNITS:
            addr = loc_of[cell].targets[0].addr
            for port in PORTS:
                ctx = f"CLKGATE {port}/{cell}/set-clear 0x{addr:x}"
                set_value = CLOCK_GATE_CONTROL_RESET | mask
                await self.csr_write(f"CGC_SET_{cell}", CLOCK_GATE_CONTROL, set_value)
                item, hs = await self._issue(
                    port, f"REDIRECT_SET_{cell}", addr, write=False, length=4
                )
                r = self._check_read(fam, f"{ctx} after enabling B", port, item, hs, 1, SLVERR)
                if r:
                    self._word(fam, f"{ctx} after enabling B", r[0].data, upper=False)
                await self.csr_write(
                    f"CGC_CLEAR_{cell}", CLOCK_GATE_CONTROL, CLOCK_GATE_CONTROL_RESET
                )
                item, hs = await self._issue(
                    port, f"REDIRECT_CLEAR_{cell}", addr, write=False, length=4
                )
                r = self._check_read(fam, f"{ctx} after clearing B", port, item, hs, 1, OKAY)
                cocotb.log.info(
                    "INFO-REDIRECT: %s set=%s cleared=%s data_after_clear=%s",
                    ctx,
                    "SLVERR-graded",
                    _rname(r[0].resp) if r else "none",
                    _hl(r[0].data) if r else "none",
                )
                fam.cells[f"S7 {port}/{cell}/set-clear"] = 1
                self.redirect_cells += 1
                n += 2
        await self.csr_read(
            "CGC_RESTORED_RB", CLOCK_GATE_CONTROL, expected=CLOCK_GATE_CONTROL_RESET
        )
        return n

    async def _split_slots(self) -> int:
        fam = self.split
        n = 0
        for port in PORTS:
            for cell, addr, reset in SPLIT_SLOTS:
                base = f"{port}/{cell}"
                ctx = f"SPLITSLOT {base} 0x{addr:x}"
                item, hs = await self._issue(port, f"SPLIT_{cell}_P0", addr, write=False, length=4)
                r = self._check_read(fam, f"{ctx} +0", port, item, hs, 1, OKAY)
                if reset is None:
                    cocotb.log.info(
                        "OBS-ERRC-SPLITSLOT-NDMCOUNT: cell=%s addr=0x%x rresp=%s word=%s "
                        "field=NDMRESET_CLUSTER_COUNT",
                        base,
                        addr,
                        _rname(r[0].resp) if r else "none",
                        f"0x{r[0].data & 0xFFFF_FFFF:08x}" if r and r[0].data is not None else "X",
                    )
                elif r and (r[0].data is None or r[0].data & 0xFFFF_FFFF != reset):
                    fam.findings.append(f"{ctx} +0: {_hl(r[0].data)}, want reset 0x{reset:x}")
                fam.cells[f"S1 {base}/+0"] = 1
                item, hs = await self._issue(
                    port, f"SPLIT_{cell}_P4", addr + 4, write=False, length=4
                )
                r = self._check_read(fam, f"{ctx} +4", port, item, hs, 1, DECERR)
                if r:
                    self._word(fam, f"{ctx} +4", r[0].data, upper=True)
                fam.cells[f"S2 {base}/+4"] = 1
                item, hs = await self._issue(port, f"SPLIT_{cell}_R64", addr, write=False)
                r = self._check_read(fam, f"{ctx} 64-bit read", port, item, hs, 1, None)
                fam.cells[f"S3 {base}/64"] = 1
                item, hs = await self._issue(
                    port, f"SPLIT_{cell}_W64", addr, write=True, wdata=SPLIT_WRITE_WORD
                )
                bresp = self._check_write(fam, f"{ctx} 64-bit write", port, item, hs, 1, None)
                after_item, after_hs = await self._issue(
                    port, f"SPLIT_{cell}_P0_AFTER", addr, write=False, length=4
                )
                after = self._check_read(
                    fam, f"{ctx} +0 after write", port, after_item, after_hs, 1, OKAY
                )
                fam.cells[f"S4 {base}/wr"] = 1
                cocotb.log.info(
                    "OBS-ERRC-SPLITSLOT: cell=%s rresp=%s rdata=%s bresp=%s plus0_after=%s sf=%s",
                    base,
                    _rname(r[0].resp) if r else "none",
                    _hl(r[0].data) if r else "none",
                    _rname(bresp),
                    f"0x{after[0].data & 0xFFFF_FFFF:08x}"
                    if after and after[0].data is not None
                    else "X",
                    fam.sfs,
                )
                n += 5
                if reset is None:
                    cocotb.log.info("INFO-SPLIT-RESTORE: %s +0 is read-only, not written", base)
                    continue
                _item, rhs = await self._issue(
                    "SEP_IN", f"SPLIT_{cell}_RESTORE", addr, write=True, length=4, wdata=reset
                )
                restored = await self.csr_read(f"SPLIT_{cell}_RESTORE_RB", addr)
                cocotb.log.info(
                    "INFO-SPLIT-RESTORE: %s +0 written 0x%x from SEP_IN, bresp %s, reads 0x%x",
                    base,
                    reset,
                    _rname(rhs["b"][0].resp) if rhs["b"] else "none",
                    restored & 0xFFFF_FFFF,
                )
            await self._live(fam, port, f"{port}/after-splitslot")
            n += 1
        return n

    # ------------------------------------------------------------------ body

    def _decerr_addrs(self) -> set[int]:
        addrs: set[int] = set()
        for fam in self.families:
            for loc in fam.locations:
                for t in loc.targets:
                    addrs.update(t.addr + off for off in range(8))
                    for lens in (fam.rburst_lens, fam.wburst_lens):
                        for ln in lens:
                            start, _ = self._place(t, ln + 1)
                            if start is not None:
                                addrs.add(start)
        addrs.add(STRADDLE_ADDR)
        for _cell, addr, _reset in SPLIT_SLOTS:
            addrs.update((addr, addr + 4))
        return addrs

    async def body(self) -> None:
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        dut = cocotb.top
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.sampler = SmcPortHandshakeSampler(dut)
        cocotb.start_soon(self.sampler.run())

        # S1 SETUP
        start_accesses = self.accesses
        self.env.axi_monitor.expected_decerr_addrs.update(self._decerr_addrs())
        await self.csr_write("INBOUND0_CONFIG_PASS_ALL", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG, 8)
        await self.csr_write("INBOUND0_START_PASS_ALL", INBOUND0_START, 0, length=8)
        await self.csr_write("INBOUND0_END_PASS_ALL", INBOUND0_END, PASS_ALL_END, length=8)
        for name, addr, value in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("START", INBOUND0_START, 0),
            ("END", INBOUND0_END, PASS_ALL_END),
        ):
            await self.csr_read(f"INBOUND0_{name}_RB", addr, expected=value, length=8)
        item, hs = await self._issue("SYS_IN", "ADMIT", LOCAL_BASE_REG, write=False)
        admit = Family("ADMIT", "", "", "", ("SYS_IN",), OKAY, False, (), {})
        r = self._check_read(admit, "CTRL-M9-ADMIT", "SYS_IN", item, hs, 1, OKAY)
        assert not admit.findings and r and r[0].data == LOCAL_BASE_RESET, (
            f"SYS_IN read of LOCAL_BASE through inbound entry 0 answered "
            f"{_rname(r[0].resp) if r else 'none'} {_hl(r[0].data) if r else ''}: "
            f"{admit.findings}"
        )
        cocotb.log.info(
            "CTRL-M9-ADMIT: SYS_IN 64-bit read of LOCAL_BASE @ 0x%x through pass-all inbound "
            "entry 0 answered OKAY %s RID %d",
            LOCAL_BASE_REG,
            _hl(r[0].data),
            r[0].ident,
        )
        await self._seed_bystanders()
        self.responder_base = output_responder_counts(dut)
        cocotb.log.info(
            "INFO-BYSTANDERS: %d registers seeded or snapshotted; SYS_OUT responder counts %s",
            len(self.bystanders),
            self.responder_base,
        )
        self._mark("ADMIT", self.accesses - start_accesses, self.accesses - start_accesses)

        for term in (
            "SINGLE_READS",
            "WORD_PAIRS",
            "SINGLE_WRITES",
            "READ_BURSTS",
            "WRITE_BURSTS",
            "NARROW",
            "LIVENESS",
        ):
            kind = PHASE_KIND[term]
            planned = self._plan_count(kind)
            count = await self._run_kind(kind)
            self._mark(term, count, planned)

        straddle = await self._straddle()
        self._mark("STRADDLE", straddle, 2 * 2 + 2 * 4)
        redirect = await self._gate_redirect()
        self._mark("GATE_REDIRECT", redirect, 2 * len(GATED_UNITS) * len(PORTS))
        split = await self._split_slots()
        self._mark("SPLIT_SLOTS", split, len(PORTS) * (5 * len(SPLIT_SLOTS) + 1))

        self.sampler.stop = True
        for port in PORTS:
            stray = self.sampler.pending(port)
            if stray:
                self.other_findings.append(f"{port}: handshakes {stray} after the last access")
        if self.sampler.unresolved:
            self.other_findings.append(
                f"{self.sampler.unresolved_count} X samples on handshake lines, first "
                f"{self.sampler.unresolved}"
            )
        rst = dut.rst_primary_smc_clk_no.value
        for port in PORTS:
            cocotb.log.info(
                "INFO-CLASSIFY: port=%s unanswered=0 checker fires are simulator records in this "
                "log; last %s; rst_primary_smc_clk_no=%s",
                port,
                self.sampler.describe(port),
                int(rst) if rst.is_resolvable else "X",
            )
        self._report()

    def _report(self) -> None:
        failed: list[str] = []
        for fam in [*self.families, self.split]:
            cells = sorted(fam.cells)
            for name in cells:
                cocotb.log.info("INFO-CELL: %s %s driven=%d", fam.key, name, fam.cells[name])
            planned = PLANNED_CELLS[fam.key]
            seen = {c for c in fam.cells if "regionsize-restore" not in c} | set(fam.not_drivable)
            if len(seen) != planned:
                fam.findings.append(
                    f"{len(seen)} cells driven or reported not drivable, planned {planned}"
                )
            for finding in fam.findings:
                cocotb.log.info("INFO-FINDING: %s %s", fam.key, finding)
            if fam.findings:
                failed.append(
                    f"{fam.key}: {len(fam.findings)} finding(s), first: {fam.findings[0]}"
                )
                continue
            driven = len(seen) - len(fam.not_drivable)
            if fam.key == "SPLITSLOT":
                stated = ", ".join(
                    f"{cell} 0x{reset:x}" for cell, _addr, reset in SPLIT_SLOTS if reset is not None
                )
                cocotb.log.info(
                    "%s: %d cells, +0 OKAY with the reset value (%s; misc_wrap +0 OKAY, word on "
                    "OBS-ERRC-SPLITSLOT-NDMCOUNT), +4 DECERR 0x%08X, one beat, one B, "
                    "liveness OKAY (%d graded accesses)",
                    fam.chk,
                    driven,
                    stated,
                    ERR_WORD,
                    fam.graded,
                )
                continue
            extra = ""
            if fam.key == "REGIONSIZE":
                extra = (
                    f"; REGION_SIZE 0x{REGION_SIZE_STRADDLE:X}: SYS_IN and SEP_IN read and write at "
                    f"0x{STRADDLE_ADDR:x} DECERR, D0 kept, D2 written and read OKAY at "
                    f"0x{REGION_SIZE_RESET:X}"
                )
            if fam.key == "CLKGATE":
                extra = (
                    f"; redirect {self.redirect_cells} periph/port cells: SLVERR 0x{ERR_WORD:08X} "
                    "after the enabling B, OKAY after the clearing B"
                )
            word = f" 0x{ERR_WORD:08X}" if fam.word_stated else ""
            live = ", liveness OKAY" if "live" in fam.scen else ""
            cocotb.log.info(
                "%s: %d cells (%d not drivable of %d planned), codes %s%s/beats/words as stated, "
                "bystanders unchanged%s (%d graded accesses)%s",
                fam.chk,
                driven,
                len(fam.not_drivable),
                planned,
                _rname(fam.code),
                word,
                live,
                fam.graded,
                extra,
            )
        self.failed = failed + self.other_findings

    def raise_findings(self) -> None:
        assert not self.failed, "error-subordinate response findings: " + " | ".join(self.failed)

    def log_timeout_paths(self) -> None:
        cocotb.log.info(
            "CHK-TIMEOUT-PATHS: %d bounded waits, 0 expired: wait_fuse_sense_done sub-waits "
            "(tb_fuse_sense_done, tb_fuse_reset_n, tb_rst_warm_smc_clk_n) each bounded %d "
            "clk_smc_i rises, last %s; %d inbound accesses each bounded %d ns by First(task, "
            "Timer) with the expiry path printing INFO-CLASSIFY (last AR/AW/W/R/B handshake and "
            "rst_primary_smc_clk_no) and failing the leaf, longest answer %d ns; driver backup "
            "timeout %d ns; SEP_IN CSR accesses bounded by the driver timeout",
            self.waits + 3,
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.waits,
            ACCESS_BOUND_NS,
            self.max_wait_ns,
            DRIVER_TIMEOUT_NS,
        )

    def nonvac_fence(self) -> None:
        terms = tuple(t for t, _time, _n, _p in self.fence)
        assert terms == FENCE, f"fence terms {terms}, want {FENCE}"
        times = [time for _t, time, _n, _p in self.fence]
        assert all(b > a for a, b in zip(times, times[1:])), f"fence times not increasing: {times}"
        for term, _time, n, planned in self.fence:
            assert n > 0 and n >= planned, f"{term}: {n} accesses against {planned} planned"
        cocotb.log.info(
            "CHK-NONVAC: %s (time and count per term: %s)",
            " < ".join(FENCE),
            ", ".join(f"{t}@{time}ps={n}/{p}" for t, time, n, p in self.fence),
        )
