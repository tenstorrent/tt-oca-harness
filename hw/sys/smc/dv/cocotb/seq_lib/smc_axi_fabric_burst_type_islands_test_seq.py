# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""FIXED, WRAP and INCR bursts from SEP_IN, SYS_IN and JTAG_IN at the SMC register islands.

Spec sources: memmap.adoc (register islands, 64-bit and 32-bit access, REGION_SIZE window);
fabric.adoc (AXI-to-AXI-Lite conversion, 64-to-32-bit downsizer); cpu.adoc (scratchpad RAM,
boot ROM write refusal); the generated SMC memory map and register descriptions
(smc_base_config, alias_remap, cpu_ctrl, misc_wrap, reset_unit); filter_ctrl.rdl allow_burst;
the AXI rules transcribed in the ocah_axi_sva header.

Every burst is graded from a passive per-port sampler of the tb_top AR, AW, W, R and B
handshakes, because the bench item carries one merged response code. Registers outside a
burst footprint (IHI 0022: FIXED AxADDR only, WRAP the aligned window, INCR the incrementing
range) are compared with reference values the leaf wrote or read before the burst. An INCR
write that answers OKAY must land each beat on the registers of its footprint. Response
codes and in-footprint landings the pinned sources leave open are OBS lines naming their SF or issue.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cocotb
from cocotb.triggers import First, ReadOnly, RisingEdge, Timer
from cocotb.utils import get_sim_time
from env.smc_reset_item import RESET_SAMPLE_FIELDS, SmcResetItem, SmcResetOp
from env.smc_sys_axi_agent import SmcSysAxiItem, SmcSysAxiOp

from ._one_shot import _OneShot
from .smc_addr_map import (
    _REPO,
    _SMC_ADDR_H,
    CLOCK_GATE_CONTROL,
    GLOBAL_BASE_RESET,
    LOCAL_BASE_RESET,
    REGION_SIZE_RESET,
    SPM_MEMORY_BASE,
    _field_mask,
    _parse_indexed_bases,
    generated_window,
    reg_reset_word,
    smc_addr,
    smc_addr_symbols,
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
FIXED, INCR, WRAP = 0, 1, 2
_BURST = {FIXED: "FIXED", INCR: "INCR", WRAP: "WRAP"}

BEAT = 8
PAGE = 0x1000
PASS_ALL_END = 0x00FF_FFFF_FFFF_FFFF
PROT_PRIVILEGED = 0b001
FUSE_WAIT_BOUND_SMC_CYCLES = 200_000
ACCESS_BOUND_NS = 100_000
DRIVER_TIMEOUT_NS = 2 * ACCESS_BOUND_NS
RESET_ASSERT_BOUND_REF_CYCLES = 400
RESET_RELEASE_BOUND_REF_CYCLES = 2000
REGION_SIZE_1K = 0x400
WINDOW_1K_OFFSET = 0x3F0

PORTS = ("SEP_IN", "SYS_IN", "JTAG_IN")
PREFIX = {"SEP_IN": "s_axi", "SYS_IN": "sys_axi", "JTAG_IN": "jtag_axi"}
# JTAG_IN carries a 2-bit ID; SEP_IN and SYS_IN carry 6 bits.
AXI_ID = {"SEP_IN": 0x15, "SYS_IN": 0x2A, "JTAG_IN": 0x2}

_BLOCKS_H = _REPO / "hw" / "sys" / "smc" / "regs" / "gen" / "c" / "blocks"
_BASE_CFG_H = _BLOCKS_H / "smc_base_config.h"
_CPU_CTRL_H = _BLOCKS_H / "cpu_ctrl.h"
_SCRATCH_H = _BLOCKS_H / "scratch.h"
_RESET_UNIT_H = _BLOCKS_H / "reset_unit.h"
_ALIAS_H = _REPO / "hw" / "ip" / "axi_alias_remap" / "regs" / "gen" / "c" / "alias_remap.h"
_GPIO_INTF_H = _REPO / "hw" / "ip" / "gpio" / "regs" / "gen" / "c" / "gpio_intf.h"
_FILTER_H = _REPO / "hw" / "ip" / "axi_filter" / "regs" / "gen" / "c" / "filter_ctrl.h"

HANG_CTRL_SEED = _field_mask(_BASE_CFG_H, "SMC_BASE_CONFIG__HANG_DET_CTRL__IRQ_EN_bm")
HANG_CTRL_UNSAFE = _field_mask(_BASE_CFG_H, "SMC_BASE_CONFIG__HANG_DET_CTRL__ENABLE_bm") | (
    _field_mask(_BASE_CFG_H, "SMC_BASE_CONFIG__HANG_DET_CTRL__IRQ_TEST_bm")
)
CG_HYSTERESIS = _field_mask(_BASE_CFG_H, "SMC_BASE_CONFIG__CLOCK_GATE_CONTROL__CG_HYSTERESIS_bm")
HANG_THRESHOLD_MASK = _field_mask(
    _BASE_CFG_H, "SMC_BASE_CONFIG__HANG_DET_TIMEOUT_THRESHOLD__VALUE_bm"
)
ALIAS_ADDR_MASK = _field_mask(_ALIAS_H, "ALIAS_REMAP__REMAP_REGION__REGION_START__START_ADDR_bm")
ALIAS_END_MASK = _field_mask(_ALIAS_H, "ALIAS_REMAP__REMAP_REGION__REGION_END__END_ADDR_bm")
ALIAS_VALID = _field_mask(_ALIAS_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__VALID_bm")
ALIAS_ATTRS_SEED = _field_mask(
    _ALIAS_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bm"
) | _field_mask(_ALIAS_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__CACHEABLE_bm")
CPU_SCRATCH_MASK = _field_mask(_CPU_CTRL_H, "CPU_CTRL__SCRATCH__DATA_bm")
MISC_SCRATCH_MASK = _field_mask(_SCRATCH_H, "SCRATCH__SCRATCH__DATA_bm")
FLR_COUNTER_MASK = _field_mask(
    _RESET_UNIT_H,
    "RESET_UNIT__ISOLATE_REQ_FLR_COUNTER_VALUE__ISOLATE_REQ_FLR_COUNTER_VALUE_bm",
)
# Reg.seed_mask marker: NDMRESET_PROCESS is seeded only in the bits at or above
# NDMRESET_CLUSTER_COUNT, which are not driven on the process output.
NDM_ABOVE_COUNT = -2
SMCEN_MASK = _field_mask(
    _RESET_UNIT_H, "RESET_UNIT__ISOLATE_REQ_SMCEN_REG__ISOLATE_REQ_SMCEN_REG_bm"
)
DUMMY_NULL_MASK = _field_mask(_CPU_CTRL_H, "CPU_CTRL__DUMMY_ROM_NULL__DUMMY_ROM_NULL_bm")
# Entry 15 keeps entry_enabled and locked 0, so the filter configuration in force is unchanged.
FILTER_ID_SEED = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm") | _field_mask(
    _FILTER_H, "FILTER_CTRL__FILTER_CONFIG__GROUP_ID_bm"
)
FILTER_START_SEED = _field_mask(_FILTER_H, "FILTER_CTRL__START_ADDR__START_ADDR_bm") & ~0xFFF
FLR_RESET_MASK = _field_mask(
    _RESET_UNIT_H,
    "RESET_UNIT__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE__ISOLATE_REQ_FLR_RESET_COUNTER_VALUE_bm",
)
GPIO_CORE2PAD = _field_mask(_GPIO_INTF_H, "GPIO_INTF__DATA_CTRL__CORE2PAD_bm")
GPIO_INTERRUPT_TYPE = _field_mask(_GPIO_INTF_H, "GPIO_INTF__DATA_CTRL__INTERRUPT_TYPE_bm")
GPIO_USE_REG_CORE2PAD = _field_mask(
    _GPIO_INTF_H, "GPIO_INTF__DATA_CTRL_ENABLE__USE_REG_CORE2PAD_bm"
)
GPIO_USE_REG_TX = _field_mask(_GPIO_INTF_H, "GPIO_INTF__DATA_CTRL_ENABLE__USE_REG_TX_bm")
GPIO_USE_REG_RX = _field_mask(_GPIO_INTF_H, "GPIO_INTF__DATA_CTRL_ENABLE__USE_REG_RX_bm")
GPIO_AWPROT_REQ = _field_mask(_GPIO_INTF_H, "GPIO_INTF__ACCESS_FILTER__AWPROT_REQUIREMENT_bm")
GPIO_ARPROT_REQ = _field_mask(_GPIO_INTF_H, "GPIO_INTF__ACCESS_FILTER__ARPROT_REQUIREMENT_bm")
GPIO_DATA_CTRL_SEED = GPIO_CORE2PAD | GPIO_INTERRUPT_TYPE
# Read-only DATA_CTRL fields the pad and LSIO hardware drive; no write can change them.
GPIO_DATA_CTRL_HW = _field_mask(_GPIO_INTF_H, "GPIO_INTF__DATA_CTRL__PAD2CORE_bm") | _field_mask(
    _GPIO_INTF_H, "GPIO_INTF__DATA_CTRL__LSIO_ENABLE_bm"
)
GPIO_ENABLE_SEED = GPIO_USE_REG_CORE2PAD | GPIO_USE_REG_TX | GPIO_USE_REG_RX
GPIO_ACCESS_SEED = GPIO_AWPROT_REQ | GPIO_ARPROT_REQ
ISOLATE_REQ_VIS_RESET = reg_reset_word(_RESET_UNIT_H, "RESET_UNIT", "ISOLATE_REQ_VIS")
ALL64 = (1 << 64) - 1
BEAT_TAG = 0x0EE0

LOCAL_BASE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_LOCAL_BASE_BASE_ADDR")
REGION_SIZE_REG = smc_addr("SMC_TOP_SMC_BASE_CONFIG_REGION_SIZE_BASE_ADDR")
SPM_SIZE = smc_addr("SMC_TOP_SPM_MEMORY_SIZE")
SPM_ROM_BASE = smc_addr("SMC_TOP_SPM_ROM_MEMORY_BASE_ADDR")
CLA_BASE = smc_addr("SMC_TOP_SMC_CLA_BASE_ADDR")
GPIO_K = 20
# _gpio_seeds index for slots k-1..k+3: no seeded field equals a half of any beat a GPIO
# burst carries, so every out-of-footprint compare can fail.
GPIO_SEED_J = (0, 3, 1, 2, 4)
ALIAS_ISLAND_SLOT = 2
ALIAS_EDGE_K = 4
ALIAS_LAST_SLOT = smc_addr("SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_NUM") - 1
FILTER_LAST = smc_addr("SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_NUM") - 1
GPIO_LAST = smc_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_NUM") - 1
CPU_STRB_SCRATCH = 12

WDT_REGS = tuple(
    (name, smc_addr(f"SMC_TOP_SMC_CLUSTER_CORE0_WDT_{name}_BASE_ADDR"))
    for name in ("CTRL", "COUNT", "SCALED_COUNT", "FEED", "KEY", "CMP")
)
WDT_KEY_REG = smc_addr("SMC_TOP_SMC_CLUSTER_CORE0_WDT_KEY_BASE_ADDR")
WDT_KEY = 0x51F15E  # wdt.rdl: the magic key that unlocks the next write to any other register

FENCE = (
    "ADMIT",
    "ISLAND64",
    "ISLAND32",
    "STROBES",
    "GPIO",
    "SPM",
    "SLOT_EDGE",
    "EXTENT_EDGE",
    "RULE_ENDS",
    "LIVENESS",
    "WINDOW_1K",
)
FENCE_STEP = dict(zip(FENCE, ("S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9", "S10", "S11")))

SHAPES = (
    ("incr-wr", INCR, True, "S1"),
    ("incr-rd", INCR, False, "S2"),
    ("fixed-wr", FIXED, True, "S3"),
    ("fixed-rd", FIXED, False, "S4"),
    ("wrap-wr", WRAP, True, "S5"),
    ("wrap-rd", WRAP, False, "S6"),
)
SPM_INCR_LENS = (0, 7, 255)
SPM_WRAP_LENS = (1, 3, 7, 15)


def _rname(code: int | None) -> str:
    return _RESP.get(code, str(code))


def _hl(data: int | None) -> str:
    if data is None:
        return "X"
    return f"{(data >> 32) & 0xFFFF_FFFF:08x}_{data & 0xFFFF_FFFF:08x}"


def _pack(words: list[int]) -> int:
    return sum((w & ALL64) << (64 * i) for i, w in enumerate(words))


def footprint(addr: int, beats: int, burst: int) -> tuple[int, ...]:
    """8-byte words an IHI 0022 burst of full-width beats addresses, in beat order."""
    if burst == FIXED:
        return (addr,) * beats
    if burst == INCR:
        return tuple(addr + BEAT * i for i in range(beats))
    size = beats * BEAT
    lo = addr & ~(size - 1)
    return tuple(lo + ((addr - lo + BEAT * i) % size) for i in range(beats))


def _unit_register_addrs(prefix: str = "SMC_TOP_") -> set[int]:
    """Every register address the generated SMC map gives the symbols that start ``prefix``."""
    addrs = {smc_addr(sym) for sym in smc_addr_symbols(rf"{prefix}\w*_BASE_ADDR")}
    for sym, (base, stride) in _parse_indexed_bases(_SMC_ADDR_H).items():
        if not (sym.startswith(prefix) and sym.endswith("_BASE_ADDR")):
            continue
        num_sym = sym[: -len("_BASE_ADDR")] + "_NUM"
        num = smc_addr(num_sym) if smc_addr_symbols(num_sym) else 1
        addrs.update(base + i * stride for i in range(num))
    return addrs


@dataclass(frozen=True)
class Reg:
    name: str
    addr: int
    width: int
    seed_mask: int = 0
    stated: int | None = None
    ro: bool = False
    hw_bits: int = 0

    @property
    def word(self) -> int:
        return self.addr & ~(BEAT - 1)

    def same(self, value: int | None, ref: int | None) -> bool:
        """Equal outside the read-only fields that hardware drives."""
        if value is None or ref is None:
            return value == ref
        return not (value ^ ref) & ~self.hw_bits


def can_fail(mask: int, ref: int, beats: list[int], width: int) -> bool:
    """True when every value a beat could write into the register differs from ``ref`` in ``mask``.

    ``mask`` is the seeded writable fields; a 32-bit register is compared with both halves of
    every beat, since a stray beat may land on either lane.
    """
    if not mask:
        return False
    values = list(beats)
    if width == 4:
        values = [h for b in beats for h in (b & 0xFFFF_FFFF, (b >> 32) & 0xFFFF_FFFF)]
    return all((ref ^ v) & mask for v in values)


@dataclass
class Island:
    key: str
    unit_prefix: str
    base: int
    span: int
    regs: tuple[Reg, ...]
    neighbours: tuple[Reg, ...]
    data_mask: int
    fixed_off: int
    downsized: bool = False


@dataclass
class Fam:
    key: str
    chk: str
    obs: str
    sfs: str
    planned: tuple[tuple[str, str], ...]
    cells: dict[tuple[str, str], int] = field(default_factory=dict)
    findings: list[str] = field(default_factory=list)
    graded: int = 0
    compares: int = 0
    failable: int = 0
    data_compares: int = 0
    bursts: int = 0
    per_island: dict[str, list] = field(default_factory=dict)

    def tally(self, island: str, reg: Reg, failable: bool | None) -> None:
        """Count one unchanged compare (True/False: can or cannot fail) or a protocol-only cell."""
        row = self.per_island.setdefault(island, [0, 0, set()])
        if failable is None:
            row[2].add(reg.name)
            return
        self.compares += 1
        if failable:
            self.failable += 1
            row[0] += 1
        else:
            row[1] += 1


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
    """Record every AR, AW, W, R and B handshake of the three inbound ports per clk_smc_i edge.

    Sampling pauses while rst_primary_smc_clk_no is low: a handshake line held in reset is not a
    protocol event.
    """

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
        self.reset_cycles = 0
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
        self.handles = {p: {n: getattr(dut, f"{PREFIX[p]}_{n}") for n in names} for p in PORTS}

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
        rst = self.dut.rst_primary_smc_clk_no
        while not self.stop:
            await RisingEdge(clk)
            await ReadOnly()
            if self._int(rst) != 1:
                self.reset_cycles += 1
                continue
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


def _r64(name: str, addr: int, mask: int = 0) -> Reg:
    return Reg(name, addr, 8, mask)


def _r32(name: str, addr: int, mask: int = 0, stated: int | None = None, ro: bool = False) -> Reg:
    return Reg(name, addr, 4, mask, stated, ro)


def _alias_regs(slot: int) -> tuple[Reg, Reg, Reg]:
    sym = "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_{}_BASE_ADDR"
    return (
        _r64(f"ALIAS{slot}.START", smc_indexed_addr(sym.format("START"), slot), ALIAS_ADDR_MASK),
        _r64(f"ALIAS{slot}.END", smc_indexed_addr(sym.format("END"), slot), ALIAS_END_MASK),
        _r64(f"ALIAS{slot}.ATTRS", smc_indexed_addr(sym.format("ATTRS"), slot), ALIAS_ATTRS_SEED),
    )


def _base_cfg(name: str) -> int:
    return smc_addr(f"SMC_TOP_SMC_BASE_CONFIG_{name}_BASE_ADDR")


def _islands64() -> tuple[Island, ...]:
    alias = _alias_regs(ALIAS_ISLAND_SLOT)
    hang = (
        _r32("HANG_DET_SYS_AXI_CTRL", _base_cfg("HANG_DET_SYS_AXI_CTRL"), HANG_CTRL_SEED),
        _r32(
            "HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD",
            _base_cfg("HANG_DET_SYS_AXI_TIMEOUT_THRESHOLD"),
            HANG_THRESHOLD_MASK,
        ),
        _r32("HANG_DET_SEP_AXI_CTRL", _base_cfg("HANG_DET_SEP_AXI_CTRL"), HANG_CTRL_SEED),
        _r32(
            "HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD",
            _base_cfg("HANG_DET_SEP_AXI_TIMEOUT_THRESHOLD"),
            HANG_THRESHOLD_MASK,
        ),
    )
    scratch = "SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR"
    cpu = tuple(
        _r64(f"CPU_CTRL.SCRATCH[{i}]", smc_indexed_addr(scratch, i), CPU_SCRATCH_MASK)
        for i in range(4, 8)
    )
    return (
        Island(
            "alias_remap-slot2",
            "SMC_TOP_SMC_ALIAS_REMAP_WRAP_",
            alias[0].addr,
            0x20,
            alias,
            (_alias_regs(ALIAS_ISLAND_SLOT - 1)[2], _alias_regs(ALIAS_ISLAND_SLOT + 1)[0]),
            ALL64 & ~ALIAS_VALID,
            0x8,
        ),
        Island(
            "base_config-hangdet",
            "SMC_TOP_SMC_BASE_CONFIG_",
            hang[0].addr,
            0x20,
            hang,
            (
                _r64("CLOCK_GATE_CONTROL", CLOCK_GATE_CONTROL, CG_HYSTERESIS),
                _r32(
                    "HANG_DET_DATA_ACCEL_CTRL",
                    _base_cfg("HANG_DET_DATA_ACCEL_CTRL"),
                    HANG_CTRL_SEED,
                ),
            ),
            ALL64 & ~(HANG_CTRL_UNSAFE | (HANG_CTRL_UNSAFE << 32)),
            0x8,
        ),
        Island(
            "cpu_ctrl-scratch",
            "SMC_TOP_SMC_CPU_CTRL_",
            cpu[0].addr,
            0x20,
            cpu,
            (
                _r64("CPU_CTRL.SCRATCH[3]", smc_indexed_addr(scratch, 3), CPU_SCRATCH_MASK),
                _r64("CPU_CTRL.SCRATCH[8]", smc_indexed_addr(scratch, 8), CPU_SCRATCH_MASK),
            ),
            ALL64,
            0x8,
        ),
    )


def _islands32() -> tuple[Island, ...]:
    def scratch(kind: str, label: str) -> tuple[Reg, ...]:
        sym = f"SMC_TOP_SMC_MISC_WRAP_{kind}_SCRATCH_BASE_ADDR"
        return tuple(
            _r32(f"{label}[{i}]", smc_indexed_addr(sym, i), MISC_SCRATCH_MASK) for i in range(8)
        )

    cold = scratch("SCRATCH_COLD", "SCRATCH_COLD")
    warm = scratch("SCRATCH_COLD_WARM", "SCRATCH_COLD_WARM")
    ru = "SMC_TOP_SMC_RESET_UNIT_{}_BASE_ADDR"
    flr = (
        _r32(
            "ISOLATE_REQ_VIS",
            smc_addr(ru.format("ISOLATE_REQ_VIS")),
            stated=ISOLATE_REQ_VIS_RESET,
            ro=True,
        ),
        _r32(
            "ISOLATE_REQ_FLR_COUNTER_VALUE",
            smc_addr(ru.format("ISOLATE_REQ_FLR_COUNTER_VALUE")),
            FLR_COUNTER_MASK,
        ),
        _r32(
            "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE",
            smc_addr(ru.format("ISOLATE_REQ_FLR_RESET_COUNTER_VALUE")),
            FLR_RESET_MASK,
        ),
    )
    version_lo = _r32(
        "CHIP_CONFIG.VERSION_LO",
        smc_addr("SMC_TOP_SMC_MISC_WRAP_CHIP_CONFIG_VERSION_LO_BASE_ADDR"),
        ro=True,
    )
    smcen = _r32("ISOLATE_REQ_SMCEN_REG", smc_addr(ru.format("ISOLATE_REQ_SMCEN_REG")), SMCEN_MASK)
    return (
        Island(
            "misc-scratch_cold",
            "SMC_TOP_SMC_MISC_WRAP_",
            cold[0].addr,
            0x20,
            cold,
            (flr[2], warm[0]),
            ALL64,
            0x8,
            downsized=True,
        ),
        Island(
            "misc-scratch_cold_warm",
            "SMC_TOP_SMC_MISC_WRAP_",
            warm[0].addr,
            0x20,
            warm,
            (cold[7], version_lo),
            ALL64,
            0x8,
            downsized=True,
        ),
        Island(
            "reset_unit-flr",
            "SMC_TOP_SMC_RESET_UNIT_",
            flr[0].addr,
            0x20,
            flr,
            (smcen, cold[0]),
            ALL64,
            0x0,
            downsized=True,
        ),
    )


def _slot_edge_island() -> Island:
    """Alias slots k and k+1; every register of slots k-1 and k+2 is a seeded neighbour."""
    regs = _alias_regs(ALIAS_EDGE_K) + _alias_regs(ALIAS_EDGE_K + 1)
    return Island(
        "alias-slot-pair",
        "SMC_TOP_SMC_ALIAS_REMAP_WRAP_",
        regs[0].addr,
        2 * smc_addr("SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_STRIDE"),
        regs,
        _alias_regs(ALIAS_EDGE_K - 1) + _alias_regs(ALIAS_EDGE_K + 2),
        ALL64 & ~ALIAS_VALID,
        0,
    )


def _gpio_regs(slot: int) -> tuple[Reg, Reg, Reg]:
    sym = "SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_{}_BASE_ADDR"
    return (
        Reg(
            f"GPIO{slot}.DATA_CTRL",
            smc_indexed_addr(sym.format("DATA_CTRL"), slot),
            4,
            GPIO_DATA_CTRL_SEED,
            hw_bits=GPIO_DATA_CTRL_HW,
        ),
        _r32(
            f"GPIO{slot}.DATA_CTRL_ENABLE",
            smc_indexed_addr(sym.format("DATA_CTRL_ENABLE"), slot),
            GPIO_ENABLE_SEED,
        ),
        _r32(
            f"GPIO{slot}.ACCESS_FILTER",
            smc_indexed_addr(sym.format("ACCESS_FILTER"), slot),
            GPIO_ACCESS_SEED,
        ),
    )


def _gpio_island() -> Island:
    """GPIO burst slots k..k+2; slots k-1 and k+3 are the seeded neighbours."""
    return Island(
        "gpio-slots",
        "SMC_TOP_GPIO_INTF_WRAP_",
        smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_BASE_ADDR", GPIO_K),
        3 * smc_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_STRIDE"),
        tuple(reg for s in range(GPIO_K, GPIO_K + 3) for reg in _gpio_regs(s)),
        _gpio_regs(GPIO_K - 1) + _gpio_regs(GPIO_K + 3),
        ALL64,
        0,
    )


def _fv(mask: int, value: int) -> int:
    return (value * (mask & -mask)) & mask


def _gpio_seeds(j: int) -> tuple[int, int, int]:
    """Distinct per-slot values that leave interface_enable, enable_rx_tx and both filter enables
    clear; every DATA_CTRL_ENABLE value that sets use_reg_core2pad also sets use_reg_tx, so the
    pad output enable is taken from enable_rx_tx[0] = 0."""
    v = j + 1
    data_ctrl = _fv(GPIO_CORE2PAD, v & 1) | _fv(GPIO_INTERRUPT_TYPE, v >> 1)
    enable = (
        GPIO_USE_REG_TX,
        GPIO_USE_REG_RX,
        GPIO_USE_REG_TX | GPIO_USE_REG_RX,
        GPIO_USE_REG_TX | GPIO_USE_REG_CORE2PAD,
        GPIO_USE_REG_TX | GPIO_USE_REG_RX | GPIO_USE_REG_CORE2PAD,
    )[j]
    access = _fv(GPIO_AWPROT_REQ, j + 2) | _fv(GPIO_ARPROT_REQ, j + 3)
    return data_ctrl, enable, access


def _gpio_landing() -> dict[str, int]:
    """Values the slot-cross INCR write carries for the registers of its footprint. Each differs
    from that register's seed and no field equals a seeded field outside the footprint, so both
    the landing and the unchanged compares can fail; the enables keep the _gpio_seeds pad rule."""
    k = GPIO_K
    return {
        f"GPIO{k}.ACCESS_FILTER": _fv(GPIO_AWPROT_REQ, 2) | _fv(GPIO_ARPROT_REQ, 7),
        f"GPIO{k + 1}.DATA_CTRL": 0,
        f"GPIO{k + 1}.DATA_CTRL_ENABLE": 0,
        f"GPIO{k + 1}.ACCESS_FILTER": _fv(GPIO_AWPROT_REQ, 6) | _fv(GPIO_ARPROT_REQ, 3),
        f"GPIO{k + 2}.DATA_CTRL": _fv(GPIO_INTERRUPT_TYPE, 1),
        f"GPIO{k + 2}.DATA_CTRL_ENABLE": GPIO_USE_REG_RX,
    }


def _fams() -> dict[str, Fam]:
    i64 = ("alias_remap-slot2", "base_config-hangdet", "cpu_ctrl-scratch")
    i32 = ("misc-scratch_cold", "misc-scratch_cold_warm", "reset_unit-flr")

    def island_cells(keys: tuple[str, ...]) -> list[tuple[str, str]]:
        out = []
        for port in PORTS:
            for key in keys:
                out += [(scen, f"{port}/{key}/{shape}") for shape, _b, _w, scen in SHAPES]
                out.append(("S7", f"{port}/after-{key}"))
        return out

    gpio = []
    spm = []
    slot = []
    ext = []
    rule = []
    region = []
    strb = []
    ext_keys = (
        "cpu_ctrl-0x2B8",
        "alias_remap-slot7",
        "ib_filter-entry15",
        "misc_wrap-0x208",
        "reset_unit-0xC8",
        "gpio-slot64",
    )
    for port in PORTS:
        gpio += [
            ("S1", f"{port}/slot-cross/wr"),
            ("S2", f"{port}/slot-cross/rd"),
            ("S3", f"{port}/fixed/wr"),
            ("S3", f"{port}/fixed/rd"),
            ("S4", f"{port}/wrap/wr"),
            ("S4", f"{port}/wrap/rd"),
            ("S5", f"{port}/after-gpio"),
        ]
        spm += [("S1", f"{port}/incr/len={n}") for n in SPM_INCR_LENS]
        spm += [("S2", f"{port}/wrap/len={n}") for n in SPM_WRAP_LENS]
        spm += [("S3", f"{port}/fixed")]
        spm += [("S4", f"{port}/{c}") for c in ("size=0", "size=1", "size=2", "strb-partial")]
        spm += [("S5", f"{port}/rom-wr"), ("S6", f"{port}/after-spm")]
        slot += [
            ("S1", f"{port}/incr/wr"),
            ("S2", f"{port}/incr/rd"),
            ("S3", f"{port}/wrap64/wr"),
            ("S3", f"{port}/wrap64/rd"),
            ("S4", f"{port}/wrap32/wr"),
            ("S5", f"{port}/after-slotedge"),
        ]
        ext += [("S1", f"{port}/{k}/rd") for k in ext_keys]
        ext += [("S2", f"{port}/{k}/wr") for k in ext_keys]
        ext += [("S3", f"{port}/after-extentedge")]
        rule += [("S1", f"{port}/spm-end"), ("S2", f"{port}/cpu_ctrl-end")]
        region += [
            ("S1", f"{port}/rs16M-end/rd"),
            ("S1", f"{port}/rs16M-end/wr"),
            ("S2", f"{port}/rs1K-cross/rd"),
            ("S2", f"{port}/rs1K-cross/wr"),
            ("S4", f"{port}/after-regionedge"),
        ]
        strb += [
            ("S1", f"{port}/misc-cold"),
            ("S1", f"{port}/misc-cold_warm"),
            ("S1", f"{port}/reset_unit-0xC0"),
            ("S2", f"{port}/misc-cold"),
            ("S2", f"{port}/misc-cold_warm"),
            ("S3", f"{port}/misc-cold-0x30"),
            ("S4", f"{port}/cpu_ctrl-scratch"),
            ("S5", f"{port}/misc-cold"),
            ("S5", f"{port}/misc-cold_warm"),
        ]
    fams = (
        Fam("ISLAND64", "CHK-BT-ISLAND64", "OBS-BT-ISLAND64", "SF-007", tuple(island_cells(i64))),
        Fam(
            "ISLAND32",
            "CHK-BT-ISLAND32",
            "OBS-BT-ISLAND32",
            "SF-007,SF-010",
            tuple(island_cells(i32)),
        ),
        Fam("STRB", "CHK-BT-STRB-UPPER", "OBS-BT-STRB-UPPER", "SF-010,SF-011", tuple(strb)),
        Fam("GPIO", "CHK-BT-GPIO", "OBS-BT-GPIO", "SF-007,SF-024", tuple(gpio)),
        Fam("SPM", "CHK-BT-SPM", "OBS-BT-SPM", "SF-022", tuple(spm)),
        Fam("SLOTEDGE", "CHK-BT-SLOTEDGE", "OBS-BT-SLOTEDGE", "SF-007,SF-008", tuple(slot)),
        Fam("EXTENTEDGE", "CHK-BT-EXTENTEDGE", "OBS-BT-EXTENTEDGE", "SF-005,SF-008", tuple(ext)),
        Fam("RULEEDGE", "CHK-BT-RULEEDGE", "OBS-BT-RULEEDGE", "SF-005", tuple(rule)),
        Fam(
            "REGIONEDGE",
            "CHK-BT-REGIONEDGE",
            "OBS-BT-REGIONEDGE",
            "SF-005,SF-008,SF-025",
            tuple(region),
        ),
        Fam("SETUP", "", "", "", ()),
    )
    return {f.key: f for f in fams}


class smc_axi_fabric_burst_type_islands_test_seq(SmcCsrSeq):
    """Drive FIXED, WRAP and INCR bursts at every island and edge the plan names and grade them."""

    def __init__(self, name: str = "smc_axi_fabric_burst_type_islands_test_seq") -> None:
        super().__init__(name)
        self.fams = _fams()
        self.i64 = _islands64()
        self.i32 = _islands32()
        self.edge = _slot_edge_island()
        self.gpio_isl = _gpio_island()
        self.ext = self._extent_targets()
        self.ext_orig: dict[Reg, int | None] = {}
        self.ndm_mask = 0
        self.dirty: set[Reg] = set()
        self.map_addrs = _unit_register_addrs()
        self.sampler: SmcPortHandshakeSampler | None = None
        self.dispatch_reset = None
        self.fence: list[tuple[str, int, int, int]] = []
        self.other_findings: list[str] = []
        self.failed: list[str] = []
        self.waits = 0
        self.reset_waits: list[str] = []
        self.max_wait_ns = 0
        self.fuse_state = "not waited"
        self.serial = 0
        self.ref: dict[Reg, int] = {}
        self.live_reads = 0
        self.rs_1k: tuple[int | None, int | None] = (None, None)
        self.setup_compares = 0
        self.last_access = "none"
        self.expired = 0

    # ------------------------------------------------------------------ access

    def _sequencer(self, port: str):
        return {
            "SEP_IN": self.env.sep_in_axi_agent,
            "SYS_IN": self.env.sys_in_axi_agent,
            "JTAG_IN": self.env.jtag_axi_agent,
        }[port].sequencer

    @staticmethod
    def _legal(addr: int, beats: int, burst: int, length: int, wstrb: int | None) -> None:
        """Refuse a request outside IHI 0022 or the contract's legal-AXI rule (bench-side)."""
        assert addr % length == 0, f"bench-side: 0x{addr:x} not aligned to {length} bytes"
        assert (addr & (PAGE - 1)) + beats * length <= PAGE, (
            f"bench-side: {beats}x{length}B at 0x{addr:x} would cross a 4 KiB boundary"
        )
        if burst in (FIXED, WRAP):
            assert beats in (2, 4, 8, 16), f"bench-side: {_BURST[burst]} length {beats} beats"
            assert length == BEAT and wstrb is None, (
                f"bench-side: {_BURST[burst]} beats must be full width with WSTRB=0xFF"
            )
        if wstrb is not None:
            assert beats == 1 and 0 < wstrb < (1 << length), f"bench-side: WSTRB 0x{wstrb:x}"

    async def _issue(
        self,
        port: str,
        label: str,
        addr: int,
        *,
        write: bool,
        burst: int = INCR,
        beats: int = 1,
        length: int = BEAT,
        wdata: int = 0,
        wstrb: int | None = None,
        prot: int = 0,
    ) -> tuple[SmcSysAxiItem, dict[str, list[_Hs]]]:
        """Issue one access on ``port`` under a bounded wait; return the item and its handshakes."""
        sampler = self.sampler
        assert sampler is not None
        self._legal(addr, beats, burst, length, wstrb)
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
        item.burst = burst
        item.wdata = wdata
        item.wstrb = wstrb
        item.prot = prot
        item.axi_id = AXI_ID[port]
        item.timeout_ns = DRIVER_TIMEOUT_NS
        item.allow_error = True
        start = int(get_sim_time("ns"))
        kind = "write" if write else "read"
        self.last_access = f"{port} {label} {_BURST[burst]} {kind} 0x{addr:x} beats={beats}"
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
        return item, sampler.take(port)

    def _check_addr_phase(
        self, fam: Fam, ctx: str, hs: dict, chan: str, addr: int, beats: int, burst: int, ident
    ) -> None:
        got = hs[chan]
        if len(got) != 1:
            fam.findings.append(f"{ctx}: {len(got)} {chan.upper()} handshakes, want 1")
            return
        a = got[0]
        if (a.addr, a.ident, a.length, a.burst) != (addr, ident, beats - 1, burst):
            fam.findings.append(
                f"{ctx}: bench-side {chan.upper()} addr/id/len/burst "
                f"{a.addr}/{a.ident}/{a.length}/{a.burst}, want 0x{addr:x}/{ident}/{beats - 1}/"
                f"{burst}"
            )

    def _check_read(
        self,
        fam: Fam,
        ctx: str,
        port: str,
        item: SmcSysAxiItem,
        hs: dict,
        code: int | None = None,
    ) -> list[_Hs]:
        ident = AXI_ID[port]
        beats = item.beats
        self._check_addr_phase(fam, ctx, hs, "ar", item.addr, beats, item.burst, ident)
        if hs["aw"] or hs["w"] or hs["b"]:
            fam.findings.append(f"{ctx}: write-channel handshakes during a read")
        r = hs["r"]
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
            if beat.data is None:
                fam.findings.append(f"{ctx}: beat {i} RDATA X")
        fam.graded += 1
        return r

    def _check_write(
        self,
        fam: Fam,
        ctx: str,
        port: str,
        item: SmcSysAxiItem,
        hs: dict,
        code: int | None = None,
    ) -> int | None:
        ident = AXI_ID[port]
        beats = item.beats
        self._check_addr_phase(fam, ctx, hs, "aw", item.addr, beats, item.burst, ident)
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
        fam.graded += 1
        return b[0].resp

    async def _rd(
        self, fam: Fam, port: str, label: str, addr: int, width: int = BEAT, prot: int = 0
    ) -> int | None:
        """Single read of a live location; graded OKAY; returns the addressed bytes."""
        item, hs = await self._issue(port, label, addr, write=False, length=width, prot=prot)
        r = self._check_read(fam, f"{fam.key} {port} {label} 0x{addr:x}", port, item, hs, OKAY)
        if not r or r[0].data is None:
            return None
        return (r[0].data >> (8 * (addr % BEAT))) & ((1 << (8 * width)) - 1)

    async def _wr(
        self,
        fam: Fam,
        port: str,
        label: str,
        addr: int,
        data: int,
        width: int = BEAT,
        prot: int = 0,
        code: int | None = OKAY,
    ) -> int | None:
        item, hs = await self._issue(
            port, label, addr, write=True, length=width, wdata=data, prot=prot
        )
        return self._check_write(fam, f"{fam.key} {port} {label} 0x{addr:x}", port, item, hs, code)

    async def _live(self, fam: Fam, port: str, scen: str | None, cell: str) -> None:
        item, hs = await self._issue(port, "LIVE_LOCAL_BASE", LOCAL_BASE_REG, write=False)
        ctx = f"{fam.key} {cell} LOCAL_BASE read"
        r = self._check_read(fam, ctx, port, item, hs, OKAY)
        if r and r[0].data != LOCAL_BASE_RESET:
            fam.findings.append(f"{ctx}: RDATA {_hl(r[0].data)}, want 0x{LOCAL_BASE_RESET:016x}")
        self.live_reads += 1
        if scen is not None:
            self._cell(fam, scen, cell)

    def _cell(self, fam: Fam, scen: str, cell: str) -> None:
        key = (scen, cell)
        if key not in fam.planned:
            fam.findings.append(f"driven cell {scen} {cell} is not in the planned list")
        fam.cells[key] = fam.cells.get(key, 0) + 1

    def _mark(self, term: str, count: int, planned: int) -> None:
        now = int(get_sim_time("ps"))
        self.fence.append((term, now, count, planned))
        cocotb.log.info(
            "INFO-STEP %s %s done at %d ps: %d against %d planned",
            FENCE_STEP[term],
            term,
            now,
            count,
            planned,
        )

    def _mask(self, reg: Reg) -> int:
        return self.ndm_mask if reg.seed_mask == NDM_ABOVE_COUNT else reg.seed_mask

    def _seed_value(self, reg: Reg) -> int:
        self.serial += 1
        s = self.serial
        mask = self._mask(reg)
        if mask == HANG_CTRL_SEED:
            value = HANG_CTRL_SEED & ~BEAT_TAG
            assert value, "every island beat sets HANG_DET_CTRL.irq_en"
            return value
        if mask == CG_HYSTERESIS:
            return _fv(CG_HYSTERESIS, 0x20 | (s & 0x1F))
        if mask in (GPIO_DATA_CTRL_SEED, GPIO_ENABLE_SEED, GPIO_ACCESS_SEED):
            fields = (GPIO_DATA_CTRL_SEED, GPIO_ENABLE_SEED, GPIO_ACCESS_SEED)
            return _gpio_seeds(1 + s % 3)[fields.index(mask)]
        if mask == FILTER_ID_SEED:
            src = _fv(_field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__SRC_ID_bm"), 1 + s % 15)
            grp = _field_mask(_FILTER_H, "FILTER_CTRL__FILTER_CONFIG__GROUP_ID_bm")
            return src | _fv(grp, 15 - s % 15)
        raw = (0x5A << 56) | ((s & 0xFFFFF) << 32) | (0x5E << 24) | ((s & 0xFFF) << 12) | 0x5ED
        value = raw & mask
        assert value, f"seed of {reg.name} is zero under mask 0x{reg.seed_mask:x}"
        return value

    @staticmethod
    def _stated_fields(stated: int | None) -> dict[str, str]:
        """OBS fields of a write whose response is graded, or left open under #3598."""
        if stated is None:
            return {"stated_bresp": "open", "issue": "#3598"}
        return {"stated_bresp": _rname(stated)}

    def _obs(self, fam: Fam, **kv: str) -> None:
        cocotb.log.info(
            "%s: %s sf=%s", fam.obs, " ".join(f"{k}={v}" for k, v in kv.items()), fam.sfs
        )

    @staticmethod
    def _codes(r: list[_Hs]) -> str:
        return ",".join(_rname(b.resp) for b in r) or "none"

    @staticmethod
    def _datas(r: list[_Hs]) -> str:
        return ",".join(_hl(b.data) for b in r) or "none"

    # ---------------------------------------------------------------- islands

    def _check_window(self, isl: Island) -> None:
        """Fail at setup unless the window holds the named registers and no other register of
        the generated map (reserved space is allowed)."""
        lo, hi = isl.base, isl.base + isl.span
        named = {reg.addr for reg in isl.regs}
        unit = _unit_register_addrs(isl.unit_prefix)
        missing = sorted(a for a in named if a not in unit)
        outside = sorted(r.name for r in isl.regs if not (lo <= r.addr and r.addr + r.width <= hi))
        foreign = sorted(a for a in self.map_addrs if lo <= a < hi and a not in named)
        assert not missing and not outside and not foreign, (
            f"island {isl.key} window 0x{lo:x}-0x{hi - 1:x}: named registers not in the map "
            f"{[hex(a) for a in missing]}, outside the window {outside}, other registers "
            f"{[hex(a) for a in foreign]}"
        )
        covered = sum(r.width for r in isl.regs)
        cocotb.log.info(
            "INFO-ISLAND: %s window 0x%x-0x%x holds %d named registers (%d bytes) and no other "
            "register of the generated map; %d bytes are not registers",
            isl.key,
            lo,
            hi - 1,
            len(isl.regs),
            covered,
            isl.span - covered,
        )
        cocotb.log.info(
            "INFO-ISLAND-NEIGHBOURS: %s %s; writable ones seeded, read-only ones protocol-only",
            isl.key,
            ", ".join(
                f"{r.name}@0x{r.addr:x}{' read-only' if r.ro else ''}" for r in isl.neighbours
            ),
        )

    def _protocol_only(self, ctx: str, reg: Reg, value: int | None) -> None:
        cocotb.log.info(
            "INFO-PROTOCOL-ONLY: %s %s @ 0x%x is read-only in the RDL, reads %s; protocol graded, "
            "no unchanged claim",
            ctx,
            reg.name,
            reg.addr,
            _hx(value),
        )

    async def _seed(self, fam: Fam, reg: Reg, tag: str, prot: int = 0) -> None:
        """Write a seed and take the read-back as the reference once its seeded fields match."""
        mask = self._mask(reg)
        assert mask, f"writable {reg.name} has no seed mask"
        value = self._seed_value(reg)
        await self._wr(fam, "SEP_IN", f"{tag}_{reg.name}", reg.addr, value, reg.width, prot)
        got = await self._rd(fam, "SEP_IN", f"{tag}_RB_{reg.name}", reg.addr, reg.width, prot)
        self.setup_compares += 1
        if got is None or got & mask != value:
            fam.findings.append(
                f"{tag} {reg.name} @ 0x{reg.addr:x} reads {_hx(got)}, seeded fields want "
                f"0x{value:x} under 0x{mask:x}"
            )
        self.ref[reg] = value if got is None else got
        self.dirty.discard(reg)

    async def _seed_island(self, isl: Island, fam: Fam) -> None:
        for reg in isl.regs + isl.neighbours:
            if not reg.ro and reg not in self.ref:
                await self._seed(fam, reg, "SEED")
        back = await self._readback(isl, fam, "SETUP")
        for reg, value in back.items():
            if reg.ro:
                self._protocol_only(f"SETUP {isl.key}", reg, value)
                continue
            self.setup_compares += 1
            if not reg.same(value, self.ref[reg]):
                fam.findings.append(
                    f"setup {isl.key} {reg.name} @ 0x{reg.addr:x} reads {_hx(value)}, "
                    f"want 0x{self.ref[reg]:x}"
                )

    async def _reseed(self, isl: Island, fam: Fam) -> None:
        for reg in isl.regs + isl.neighbours:
            if reg in self.dirty:
                await self._seed(fam, reg, "RESEED")

    def _unchanged(
        self, fam: Fam, island: str, ctx: str, reg: Reg, value, ref: int, beats: list[int]
    ) -> None:
        """Compare an out-of-footprint register with its reference and count whether it can fail."""
        failable = can_fail(self._mask(reg), ref, beats, reg.width)
        fam.tally(island, reg, failable)
        if not failable:
            fam.findings.append(f"{ctx}: seeded {reg.name} reference 0x{ref:x} equals a beat")
        if not reg.same(value, ref):
            fam.findings.append(
                f"{ctx}: out-of-footprint {reg.name} @ 0x{reg.addr:x} reads {_hx(value)}, "
                f"want 0x{ref:x}"
            )

    async def _readback(self, isl: Island, fam: Fam, tag: str) -> dict[Reg, int | None]:
        out = {}
        for reg in isl.regs + isl.neighbours:
            out[reg] = await self._rd(fam, "SEP_IN", f"RB_{tag}_{reg.name}", reg.addr, reg.width)
        return out

    def _beat_word(self, pidx: int, iidx: int, sidx: int, beat: int) -> int:
        tag = (pidx << 24) | (iidx << 20) | (sidx << 16) | (beat << 12) | BEAT_TAG
        return ((0x5000_0000 | tag) << 32) | (0x4000_0000 | tag)

    @staticmethod
    def _stated_bresp(isl: Island, start: int, beats: int, burst: int) -> int | None:
        """OKAY where memmap.adoc:63-67 states the response of an island write burst, else None.

        memmap.adoc:63-67 gives a write burst that a register unit splits into single-beat writes
        the response of those writes, and a write to a register answers OKAY. Whether a
        multi-beat FIXED or WRAP burst reaches that split behind the 64-to-32-bit downsizer is
        not stated (issue #3598), so such a burst into a 32-bit island gets ``None``. A beat that
        touches a byte no named register holds has a code SF-007 and SF-010 leave open, so that
        burst gets ``None`` too.
        """
        if isl.downsized and burst != INCR and beats > 1:
            return None
        live = {a for reg in isl.regs for a in range(reg.addr, reg.addr + reg.width)}
        words = footprint(start, beats, burst)
        if all(a in live for word in words for a in range(word, word + BEAT)):
            return OKAY
        return None

    @staticmethod
    def _lane(reg: Reg, beat: int) -> int:
        return (beat >> (8 * (reg.addr % BEAT))) & ((1 << (8 * reg.width)) - 1)

    def _landing(self, reg: Reg, value: int | None, data: list[int]) -> str:
        """Which beat's lane a written register holds in its seeded fields: ``b<i>`` (several
        joined by ``/``), ``seed``, ``ambiguous`` (a beat lane and the seed agree there) or
        ``other``."""
        if value is None:
            return "X"
        mask = self._mask(reg)
        hits = [i for i, d in enumerate(data) if not (value ^ self._lane(reg, d)) & mask]
        seed = not (value ^ self.ref[reg]) & mask
        if hits and seed:
            return "ambiguous"
        if hits:
            return "/".join(f"b{i}" for i in hits)
        return "seed" if seed else "other"

    @staticmethod
    def _landed(labels: list[str]) -> str:
        if not labels:
            return "n/a"
        if all(lab.startswith("b") for lab in labels):
            return "all"
        return "none" if all(lab == "seed" for lab in labels) else "some"

    def _shape_start(self, isl: Island, burst: int) -> int:
        if burst == FIXED:
            return isl.base + isl.fixed_off
        if burst == WRAP:
            return isl.base + 0x10
        return isl.base

    async def _island(self, fam: Fam, isl: Island, port: str, pidx: int, iidx: int) -> None:
        for sidx, (shape, burst, write, scen) in enumerate(SHAPES):
            start = self._shape_start(isl, burst)
            beats = 4
            cell = f"{port}/{isl.key}/{shape}"
            ctx = f"{fam.key} {cell} {_BURST[burst]} 0x{start:x}"
            if write:
                await self._reseed(isl, fam)
                data = [self._beat_word(pidx, iidx, sidx, b) & isl.data_mask for b in range(beats)]
                item, hs = await self._issue(
                    port,
                    f"{isl.key}_{shape}",
                    start,
                    write=True,
                    burst=burst,
                    beats=beats,
                    wdata=_pack(data),
                )
                stated = self._stated_bresp(isl, start, beats, burst)
                bresp = self._check_write(fam, ctx, port, item, hs, stated)
                after = await self._readback(isl, fam, shape)
                order = footprint(start, beats, burst)
                words = set(order)
                inside = []
                landing = []
                for reg in isl.regs + isl.neighbours:
                    value = after[reg]
                    if reg.ro:
                        fam.tally(isl.key, reg, None)
                        self._protocol_only(ctx, reg, value)
                        continue
                    if reg.word in words:
                        inside.append(f"{reg.name}:{_hx(value)}")
                        landing.append((reg, self._landing(reg, value, data)))
                        self.dirty.add(reg)
                        if stated == OKAY and burst == INCR:
                            want = self._lane(reg, data[order.index(reg.word)])
                            mask = self._mask(reg)
                            fam.data_compares += 1
                            if value is None or (value ^ want) & mask:
                                fam.findings.append(
                                    f"{ctx}: {reg.name} @ 0x{reg.addr:x} reads {_hx(value)}, "
                                    f"its INCR beat wrote 0x{want:x} under 0x{mask:x}"
                                )
                        continue
                    self._unchanged(fam, isl.key, ctx, reg, value, self.ref[reg], data)
                self._obs(
                    fam,
                    port=port,
                    island=isl.key,
                    shape=shape,
                    bresp=_rname(bresp),
                    **self._stated_fields(stated),
                    landed=self._landed([lab for _r, lab in landing]),
                    rresp="-",
                    wdata=",".join(_hl(d) for d in data),
                    footprint=";".join(inside) or "none",
                )
                if burst == WRAP and not isl.downsized:
                    last = f"b{beats - 1}"
                    at_start = all(
                        lab == (last if reg.word == start else "seed") for reg, lab in landing
                    )
                    cocotb.log.info(
                        "OBS-BT-WRAP-LANDING: port=%s island=%s start=0x%x beat_addrs=%s "
                        "landing=%s all_at_start=%s sf=%s issue=#3598",
                        port,
                        isl.key,
                        start,
                        ",".join(hex(w) for w in order),
                        ";".join(f"{reg.name}:{lab}" for reg, lab in landing),
                        "y" if at_start else "n",
                        fam.sfs,
                    )
            else:
                item, hs = await self._issue(
                    port, f"{isl.key}_{shape}", start, write=False, burst=burst, beats=beats
                )
                r = self._check_read(fam, ctx, port, item, hs)
                order = ",".join(hex(w) for w in footprint(start, beats, burst))
                self._obs(
                    fam,
                    port=port,
                    island=isl.key,
                    shape=shape,
                    bresp="-",
                    rresp=self._codes(r),
                    rdata=self._datas(r),
                    beat_addrs=order,
                )
            fam.bursts += 1
            self._cell(fam, scen, cell)
        await self._live(fam, port, "S7", f"{port}/after-{isl.key}")

    # ----------------------------------------------------------------- strobes

    async def _strobes(self, port: str, pidx: int) -> int:
        fam = self.fams["STRB"]
        n = 0
        cold, warm, flr = self.i32
        pairs = (
            ("misc-cold", cold.regs[0], cold.regs[1]),
            ("misc-cold_warm", warm.regs[0], warm.regs[1]),
            ("reset_unit-0xC0", flr.regs[0], flr.regs[1]),
        )

        async def seed_pair(lo: Reg, hi: Reg) -> tuple[int | None, int | None]:
            for reg in (lo, hi):
                if reg.seed_mask:
                    await self._wr(
                        fam, "SEP_IN", f"STRB_SEED_{reg.name}", reg.addr, self._seed_value(reg), 4
                    )
            pre_lo = await self._rd(fam, "SEP_IN", f"STRB_PRE_{lo.name}", lo.addr, 4)
            pre_hi = await self._rd(fam, "SEP_IN", f"STRB_PRE_{hi.name}", hi.addr, 4)
            return pre_lo, pre_hi

        async def strobed(label: str, addr: int, data: int, wstrb: int) -> int | None:
            item, hs = await self._issue(
                port, label, addr, write=True, wdata=data, wstrb=wstrb, length=BEAT
            )
            return self._check_write(
                fam, f"STRB {port} {label} wstrb=0x{wstrb:02x} 0x{addr:x}", port, item, hs, OKAY
            )

        def expect(ctx: str, got: int | None, want: int | None) -> None:
            fam.compares += 1
            if got is None or want is None or got != want:
                fam.findings.append(f"{ctx}: read {got if got is None else hex(got)}, want {want}")

        for pi, (key, lo, hi) in enumerate(pairs):
            data = ((0xD0 + pidx) << 56) | (pi << 52) | 0x0A5A_5A5A_5A5A_5A00 | (0x10 + pi)
            data &= ALL64
            pre_lo, pre_hi = await seed_pair(lo, hi)
            if lo.stated is not None:
                expect(f"STRB S1 {port}/{key} {lo.name} pre-write", pre_lo, lo.stated)
            await strobed(f"S1_{key}", lo.addr, data, 0xF0)
            post_lo = await self._rd(fam, "SEP_IN", f"STRB_S1_{lo.name}", lo.addr, 4)
            post_hi = await self._rd(fam, "SEP_IN", f"STRB_S1_{hi.name}", hi.addr, 4)
            expect(f"STRB S1 {port}/{key} +4 {hi.name}", post_hi, data >> 32)
            expect(
                f"STRB S1 {port}/{key} +0 {lo.name}",
                post_lo,
                lo.stated if lo.stated is not None else pre_lo,
            )
            self._obs(
                fam, port=port, pair=key, strobe="0xF0", plus0=_hx(post_lo), plus4=_hx(post_hi)
            )
            self._cell(fam, "S1", f"{port}/{key}")
            fam.bursts += 1
            n += 1
        for pi, (key, lo, hi) in enumerate(pairs[:2]):
            data = ((0xE0 + pidx) << 56) | (pi << 52) | 0x0C3C_3C3C_3C3C_3C00 | (0x20 + pi)
            pre_lo, pre_hi = await seed_pair(lo, hi)
            await strobed(f"S2_{key}", lo.addr, data, 0x0F)
            post_lo = await self._rd(fam, "SEP_IN", f"STRB_S2_{lo.name}", lo.addr, 4)
            post_hi = await self._rd(fam, "SEP_IN", f"STRB_S2_{hi.name}", hi.addr, 4)
            expect(f"STRB S2 {port}/{key} +0 {lo.name}", post_lo, data & 0xFFFF_FFFF)
            expect(f"STRB S2 {port}/{key} +4 {hi.name}", post_hi, pre_hi)
            self._cell(fam, "S2", f"{port}/{key}")
            fam.bursts += 1
            n += 1
        key, lo, hi = pairs[0]
        data = ((0xF0 + pidx) << 56) | 0x0096_9696_9696_9600 | 0x30
        pre_lo, pre_hi = await seed_pair(lo, hi)
        await strobed("S3_misc-cold", lo.addr, data, 0x30)
        post_lo = await self._rd(fam, "SEP_IN", f"STRB_S3_{lo.name}", lo.addr, 4)
        post_hi = await self._rd(fam, "SEP_IN", f"STRB_S3_{hi.name}", hi.addr, 4)
        expect(f"STRB S3 {port}/{key} +0 {lo.name}", post_lo, pre_lo)
        self._obs(
            fam,
            port=port,
            pair=key,
            strobe="0x30",
            plus0=_hx(post_lo),
            plus4=_hx(post_hi),
            plus4_pre=_hx(pre_hi),
        )
        self._cell(fam, "S3", f"{port}/misc-cold-0x30")
        fam.bursts += 1
        n += 1
        scratch = _r64(
            f"CPU_CTRL.SCRATCH[{CPU_STRB_SCRATCH}]",
            smc_indexed_addr("SMC_TOP_SMC_CPU_CTRL_SCRATCH_BASE_ADDR", CPU_STRB_SCRATCH),
            CPU_SCRATCH_MASK,
        )
        ref = self._seed_value(scratch)
        await self._wr(fam, "SEP_IN", "STRB_S4_SEED", scratch.addr, ref, 8)
        pre = await self._rd(fam, "SEP_IN", "STRB_S4_PRE", scratch.addr, 8)
        expect(f"STRB S4 {port} {scratch.name} pre-write", pre, ref)
        await strobed("S4_cpu_ctrl-scratch", scratch.addr, ALL64, 0xF0)
        post = await self._rd(fam, port, "STRB_S4_READ", scratch.addr, 8)
        expect(f"STRB S4 {port} {scratch.name} 64-bit read", post, ref)
        self._cell(fam, "S4", f"{port}/cpu_ctrl-scratch")
        fam.bursts += 1
        n += 1
        for key, lo, hi in pairs[:2]:
            w_lo = await self._rd(fam, "SEP_IN", f"STRB_S5_{lo.name}", lo.addr, 4)
            w_hi = await self._rd(fam, "SEP_IN", f"STRB_S5_{hi.name}", hi.addr, 4)
            pair = await self._rd(fam, port, f"STRB_S5_{key}_64", lo.addr, 8)
            want = None if w_lo is None or w_hi is None else (w_hi << 32) | w_lo
            expect(f"STRB S5 {port}/{key} 64-bit pair read", pair, want)
            self._cell(fam, "S5", f"{port}/{key}")
            fam.bursts += 1
            n += 1
        return n

    # -------------------------------------------------------------------- GPIO

    async def _gpio(self, port: str, pidx: int) -> int:
        fam = self.fams["GPIO"]
        isl = self.gpio_isl
        regs = [*isl.neighbours[:3], *isl.regs, *isl.neighbours[3:]]
        by_addr = {reg.addr: reg for reg in regs}
        landing = {reg.addr: v for reg in regs if (v := _gpio_landing().get(reg.name)) is not None}

        async def read_all(tag: str) -> dict[int, int | None]:
            return {
                reg.addr: await self._rd(
                    fam, "SEP_IN", f"GPIO_{tag}_{reg.name}", reg.addr, 4, PROT_PRIVILEGED
                )
                for reg in regs
            }

        def word(values: dict[int, int | None], addr: int) -> int:
            lo = values.get(addr) or 0
            hi = values.get(addr + 4) if addr + 4 in by_addr else 0
            return ((hi or 0) << 32) | lo

        slot_k = smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_BASE_ADDR", GPIO_K)
        slot_k1 = smc_indexed_addr("SMC_TOP_GPIO_INTF_WRAP_GPIO_INTF_BASE_ADDR", GPIO_K + 1)
        shapes = (
            ("slot-cross/wr", "S1", INCR, True, slot_k + 0x8, 4),
            ("slot-cross/rd", "S2", INCR, False, slot_k + 0x8, 4),
            ("fixed/wr", "S3", FIXED, True, slot_k1, 4),
            ("fixed/rd", "S3", FIXED, False, slot_k1, 4),
            ("wrap/wr", "S4", WRAP, True, slot_k1 + 0x8, 2),
            ("wrap/rd", "S4", WRAP, False, slot_k1 + 0x8, 2),
        )
        orig = await read_all("ORIG")
        seeds = {}
        for j, slot in zip(GPIO_SEED_J, range(0, len(regs), 3)):
            for reg, value in zip(regs[slot : slot + 3], _gpio_seeds(j)):
                await self._wr(
                    fam, "SEP_IN", f"GPIO_SEED_{reg.name}", reg.addr, value, 4, PROT_PRIVILEGED
                )
                seeds[reg.addr] = value
        before = await read_all("PRE")
        seed_ref = {}
        for addr, value in seeds.items():
            got = before[addr]
            seed_ref[addr] = value if got is None else got
            if got is None or got & by_addr[addr].seed_mask != value:
                fam.findings.append(
                    f"GPIO {port} seed {by_addr[addr].name} reads {_hx(got)}, "
                    f"seeded fields want 0x{value:x}"
                )
        n = 0
        for shape, scen, burst, write, start, beats in shapes:
            ctx = f"GPIO {port}/{shape} {_BURST[burst]} 0x{start:x}"
            words = footprint(start, beats, burst)
            if write:
                data = [word({**before, **landing} if burst == INCR else before, w) for w in words]
                item, hs = await self._issue(
                    port,
                    f"GPIO_{shape}",
                    start,
                    write=True,
                    burst=burst,
                    beats=beats,
                    wdata=_pack(data),
                    prot=PROT_PRIVILEGED,
                )
                bresp = self._check_write(fam, ctx, port, item, hs)
                after = await read_all(shape.replace("/", "_"))
                inside = []
                for reg in regs:
                    value = after[reg.addr]
                    if reg.word in set(words):
                        inside.append(f"{reg.name}:{_hx(value)}")
                        if burst == INCR and bresp == OKAY:
                            want, mask = landing[reg.addr], reg.seed_mask
                            fam.data_compares += 1
                            if not (want ^ seed_ref[reg.addr]) & mask:
                                fam.findings.append(f"{ctx}: {reg.name} already holds 0x{want:x}")
                            if value is None or (value ^ want) & mask:
                                fam.findings.append(
                                    f"{ctx}: {reg.name} @ 0x{reg.addr:x} reads {_hx(value)}, "
                                    f"its INCR beat wrote 0x{want:x} under 0x{mask:x}"
                                )
                        if value is not None:
                            seed_ref[reg.addr] = value
                        continue
                    self._unchanged(fam, isl.key, ctx, reg, value, seed_ref[reg.addr], data)
                self._obs(
                    fam,
                    port=port,
                    shape=shape,
                    bresp=_rname(bresp),
                    **({} if burst == INCR else self._stated_fields(None)),
                    rresp="-",
                    slots=";".join(inside),
                )
                before = after
            else:
                item, hs = await self._issue(
                    port,
                    f"GPIO_{shape}",
                    start,
                    write=False,
                    burst=burst,
                    beats=beats,
                    prot=PROT_PRIVILEGED,
                )
                r = self._check_read(fam, ctx, port, item, hs)
                self._obs(
                    fam,
                    port=port,
                    shape=shape,
                    bresp="-",
                    rresp=self._codes(r),
                    slots=self._datas(r),
                    beat_addrs=",".join(hex(w) for w in words),
                )
            fam.bursts += 1
            self._cell(fam, scen, f"{port}/{shape}")
            n += 1
        for reg in regs:
            if orig[reg.addr] is not None:
                await self._wr(
                    fam,
                    "SEP_IN",
                    f"GPIO_RESTORE_{reg.name}",
                    reg.addr,
                    orig[reg.addr],
                    4,
                    PROT_PRIVILEGED,
                )
        await self._live(fam, port, "S5", f"{port}/after-gpio")
        return n

    # --------------------------------------------------------------------- SPM

    async def _spm_guard(self, fam: Fam, port: str, tag: str, addrs: tuple[int, ...]) -> dict:
        guards = {}
        for a in addrs:
            self.serial += 1
            value = (0x6A << 56) | (self.serial << 32) | 0x6EAD_0000 | (a & 0xFFFF)
            await self._wr(fam, "SEP_IN", f"SPM_GUARD_{tag}", a, value)
            guards[a] = value
        return guards

    async def _spm_guard_check(self, fam: Fam, ctx: str, guards: dict) -> None:
        for a, value in guards.items():
            got = await self._rd(fam, "SEP_IN", "SPM_GUARD_RB", a)
            fam.compares += 1
            if got != value:
                fam.findings.append(
                    f"{ctx}: byte range outside the footprint @ 0x{a:x} reads {_hx(got)}, "
                    f"want 0x{value:x}"
                )

    async def _spm(self, port: str, pidx: int) -> int:
        fam = self.fams["SPM"]
        region = SPM_MEMORY_BASE + 0x2_0000 + pidx * 0x1_0000
        n = 0
        for j, ln in enumerate(SPM_INCR_LENS):
            beats = ln + 1
            start = region + j * PAGE + 0x38
            ctx = f"SPM {port}/incr/len={ln} 0x{start:x}"
            guards = await self._spm_guard(
                fam, port, f"INCR{ln}", (start - BEAT, start + beats * BEAT)
            )
            data = [
                ((0x70 + pidx) << 56) | (ln << 40) | (i << 24) | 0x00C0_DE00 | (i & 0xFF)
                for i in range(beats)
            ]
            item, hs = await self._issue(
                port, f"SPM_INCR{ln}_WR", start, write=True, beats=beats, wdata=_pack(data)
            )
            self._check_write(fam, ctx, port, item, hs, OKAY)
            await self._spm_guard_check(fam, ctx, guards)
            item, hs = await self._issue(port, f"SPM_INCR{ln}_RD", start, write=False, beats=beats)
            r = self._check_read(fam, ctx, port, item, hs, OKAY)
            fam.compares += 1
            got = [b.data for b in r]
            if got != data:
                bad = [i for i, (g, d) in enumerate(zip(got, data)) if g != d]
                fam.findings.append(
                    f"{ctx}: read beats differ from the written data at {bad[:4]} "
                    f"(beats {len(got)}/{beats})"
                )
            self._cell(fam, "S1", f"{port}/incr/len={ln}")
            fam.bursts += 2
            n += 2
        for j, ln in enumerate(SPM_WRAP_LENS):
            beats = ln + 1
            size = beats * BEAT
            wbase = region + (3 + j) * PAGE + 0x100
            start = wbase + size // 2
            ctx = f"SPM {port}/wrap/len={ln} 0x{start:x}"
            guards = await self._spm_guard(fam, port, f"WRAP{ln}", (wbase - BEAT, wbase + size))
            data = [
                ((0x80 + pidx) << 56) | (ln << 40) | (i << 24) | 0x00A9_0000 | i
                for i in range(beats)
            ]
            item, hs = await self._issue(
                port,
                f"SPM_WRAP{ln}_WR",
                start,
                write=True,
                burst=WRAP,
                beats=beats,
                wdata=_pack(data),
            )
            bresp = self._check_write(fam, ctx, port, item, hs)
            await self._spm_guard_check(fam, ctx, guards)
            item, hs = await self._issue(
                port, f"SPM_WRAP{ln}_RD", start, write=False, burst=WRAP, beats=beats
            )
            r = self._check_read(fam, ctx, port, item, hs)
            landing = []
            for a in range(wbase, wbase + size, BEAT):
                landing.append(
                    f"0x{a - wbase:x}:{_hx(await self._rd(fam, 'SEP_IN', 'SPM_LAND', a))}"
                )
            self._obs(
                fam,
                port=port,
                shape="WRAP",
                len=str(ln),
                bresp=_rname(bresp),
                rresp=self._codes(r),
                rdata=self._datas(r),
                landing=";".join(landing),
                wdata_order=",".join(hex(w - wbase) for w in footprint(start, beats, WRAP)),
            )
            self._cell(fam, "S2", f"{port}/wrap/len={ln}")
            fam.bursts += 2
            n += 2
        fixed_at = region + 7 * PAGE + 0x200
        ctx = f"SPM {port}/fixed 0x{fixed_at:x}"
        guards = await self._spm_guard(fam, port, "FIXED", (fixed_at - BEAT, fixed_at + BEAT))
        data = [((0x90 + pidx) << 56) | (i << 24) | 0x00F1_0000 | i for i in range(4)]
        item, hs = await self._issue(
            port, "SPM_FIXED_WR", fixed_at, write=True, burst=FIXED, beats=4, wdata=_pack(data)
        )
        bresp = self._check_write(fam, ctx, port, item, hs)
        await self._spm_guard_check(fam, ctx, guards)
        item, hs = await self._issue(
            port, "SPM_FIXED_RD", fixed_at, write=False, burst=FIXED, beats=4
        )
        r = self._check_read(fam, ctx, port, item, hs)
        final = await self._rd(fam, "SEP_IN", "SPM_FIXED_FINAL", fixed_at)
        self._obs(
            fam,
            port=port,
            shape="FIXED",
            len="3",
            bresp=_rname(bresp),
            rresp=self._codes(r),
            rdata=self._datas(r),
            landing=f"0x0:{_hx(final)}",
        )
        self._cell(fam, "S3", f"{port}/fixed")
        fam.bursts += 2
        n += 2
        narrow_at = region + 8 * PAGE + 0x300
        guards = await self._spm_guard(fam, port, "NARROW", (narrow_at - BEAT, narrow_at + BEAT))
        model = ((0xA0 + pidx) << 56) | 0x0011_2233_4455_6677
        await self._wr(fam, port, "SPM_NARROW_SEED", narrow_at, model)
        steps = (
            ("size=0", narrow_at + 3, 1, 0xA1, None),
            ("size=1", narrow_at + 6, 2, 0xB2C3, None),
            ("size=2", narrow_at, 4, 0xD4E5_F607, None),
            ("strb-partial", narrow_at, 8, 0x1828_3848_5868_7888 | (pidx << 4), 0x5A),
        )
        for cell, addr, width, value, wstrb in steps:
            ctx = f"SPM {port}/{cell} 0x{addr:x}"
            item, hs = await self._issue(
                port, f"SPM_{cell}", addr, write=True, length=width, wdata=value, wstrb=wstrb
            )
            self._check_write(fam, ctx, port, item, hs, OKAY)
            off = addr - narrow_at
            lanes = ((1 << width) - 1) if wstrb is None else wstrb
            for k in range(width):
                if lanes >> k & 1:
                    byte = (value >> (8 * k)) & 0xFF
                    shift = 8 * (off + k)
                    model = (model & ~(0xFF << shift)) | (byte << shift)
            got = await self._rd(fam, port, f"SPM_{cell}_RB", narrow_at)
            fam.compares += 1
            if got != model:
                fam.findings.append(f"{ctx}: 64-bit read {_hx(got)}, want {_hl(model)}")
            self._cell(fam, "S4", f"{port}/{cell}")
            fam.bursts += 1
            n += 1
        await self._spm_guard_check(fam, f"SPM {port}/narrow", guards)
        rom = SPM_ROM_BASE + 0x100 + pidx * 0x40
        ctx = f"SPM {port}/rom-wr 0x{rom:x}"
        rom_before = [await self._rd(fam, "SEP_IN", "ROM_PRE", rom + BEAT * i) for i in range(4)]
        payload = _pack([((0xB0 + pidx) << 56) | 0x0BAD_0000_0000 | i for i in range(4)])
        item, hs = await self._issue(port, "SPM_ROM_WR", rom, write=True, beats=4, wdata=payload)
        self._check_write(fam, ctx, port, item, hs, SLVERR)
        rom_after = [await self._rd(fam, "SEP_IN", "ROM_POST", rom + BEAT * i) for i in range(4)]
        fam.compares += 1
        if rom_after != rom_before or None in rom_before:
            fam.findings.append(
                f"{ctx}: ROM words {[_hx(v) for v in rom_before]} -> {[_hx(v) for v in rom_after]}"
            )
        self._cell(fam, "S5", f"{port}/rom-wr")
        fam.bursts += 1
        n += 1
        await self._live(fam, port, "S6", f"{port}/after-spm")
        return n

    # --------------------------------------------------------------- slot edge

    async def _slot_edge(self, port: str, pidx: int) -> int:
        fam = self.fams["SLOTEDGE"]
        isl = self.edge
        stride = smc_addr("SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_STRIDE")
        slot_k = smc_indexed_addr(
            "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_BASE_ADDR", ALIAS_EDGE_K
        )
        slot_k1 = slot_k + stride
        shapes = (
            ("incr/wr", "S1", INCR, True, slot_k + 0x10, 4),
            ("incr/rd", "S2", INCR, False, slot_k + 0x10, 4),
            ("wrap64/wr", "S3", WRAP, True, slot_k1 + 0x10, 8),
            ("wrap64/rd", "S3", WRAP, False, slot_k1 + 0x10, 8),
            ("wrap32/wr", "S4", WRAP, True, slot_k + 0x10, 4),
        )
        n = 0
        for sidx, (shape, scen, burst, write, start, beats) in enumerate(shapes):
            ctx = f"SLOTEDGE {port}/{shape} {_BURST[burst]} 0x{start:x}"
            order = footprint(start, beats, burst)
            words = set(order)
            if write:
                await self._reseed(isl, fam)
                data = [self._beat_word(pidx, 7, sidx, b) & isl.data_mask for b in range(beats)]
                item, hs = await self._issue(
                    port,
                    f"SLOT_{shape}",
                    start,
                    write=True,
                    burst=burst,
                    beats=beats,
                    wdata=_pack(data),
                )
                stated = self._stated_bresp(isl, start, beats, burst)
                bresp = self._check_write(fam, ctx, port, item, hs, stated)
                after = await self._readback(isl, fam, shape.replace("/", "_"))
                k1 = []
                for reg in isl.regs + isl.neighbours:
                    value = after[reg]
                    if reg.addr in (slot_k1, slot_k1 + 0x8):
                        k1.append(f"{reg.name}:{_hx(value)}")
                    if reg.word in words:
                        self.dirty.add(reg)
                        mask = self._mask(reg)
                        if burst == INCR and bresp == OKAY and mask and not reg.ro:
                            want = self._lane(reg, data[order.index(reg.word)])
                            fam.data_compares += 1
                            if value is None or (value ^ want) & mask:
                                fam.findings.append(
                                    f"{ctx}: {reg.name} @ 0x{reg.addr:x} reads {_hx(value)}, "
                                    f"its INCR beat wrote 0x{want:x} under 0x{mask:x}"
                                )
                        continue
                    self._unchanged(fam, isl.key, ctx, reg, value, self.ref[reg], data)
                self._obs(
                    fam,
                    port=port,
                    shape=shape,
                    bresp=_rname(bresp),
                    **self._stated_fields(stated),
                    rresp="-",
                    slot_k1=";".join(k1),
                    footprint=";".join(
                        f"{reg.name}:{_hx(after[reg])}" for reg in isl.regs if reg.word in words
                    ),
                )
            else:
                item, hs = await self._issue(
                    port, f"SLOT_{shape}", start, write=False, burst=burst, beats=beats
                )
                r = self._check_read(fam, ctx, port, item, hs)
                self._obs(
                    fam,
                    port=port,
                    shape=shape,
                    bresp="-",
                    rresp=self._codes(r),
                    slot_k1=self._datas(r),
                    beat_addrs=",".join(hex(w) for w in footprint(start, beats, burst)),
                )
            fam.bursts += 1
            self._cell(fam, scen, f"{port}/{shape}")
            n += 1
        await self._live(fam, port, "S5", f"{port}/after-slotedge")
        return n

    # ------------------------------------------------------------- extent edge

    def _extent_targets(self) -> tuple:
        ib = "SMC_TOP_SMC_INBOUND_FILTER_CTRL_WRAP_FILTER_CTRL_{}_BASE_ADDR"
        ru = "SMC_TOP_SMC_RESET_UNIT_{}_BASE_ADDR"
        nd = "SMC_TOP_SMC_MISC_WRAP_NDM_RESET_NDMRESET_{}_BASE_ADDR"
        null = "SMC_TOP_SMC_CPU_CTRL_DUMMY_ROM_NULL_BASE_ADDR"
        a7 = _alias_regs(ALIAS_LAST_SLOT)
        g64 = _gpio_regs(GPIO_LAST)
        g63 = _gpio_regs(GPIO_LAST - 1)
        cpu_first, _cpu_last = generated_window("smc_cpu_ctrl")
        cpu_extent = smc_addr("SMC_TOP_SMC_CPU_CTRL_SIZE")
        cpu_last = smc_indexed_addr(null, 3)
        assert cpu_last + 8 == LOCAL_BASE_RESET + cpu_first + cpu_extent, (
            "DUMMY_ROM_NULL[3] is not the last CPU-control register"
        )
        # (key, live register, width, prot, registers below, distinct live value, beats 1..3)
        return (
            (
                "cpu_ctrl-0x2B8",
                _r64("DUMMY_ROM_NULL[3]", cpu_last),
                8,
                0,
                (
                    _r64("DUMMY_ROM_NULL[2]", smc_indexed_addr(null, 2), DUMMY_NULL_MASK),
                    _r64("DUMMY_ROM_NULL[1]", smc_indexed_addr(null, 1), DUMMY_NULL_MASK),
                ),
                False,
                (0, 0, 0),
            ),
            ("alias_remap-slot7", a7[2], 8, 0, (a7[0], a7[1]), True, (0, 0, 0)),
            (
                "ib_filter-entry15",
                _r64("INBOUND15.END_ADDR", smc_indexed_addr(ib.format("END_ADDR"), FILTER_LAST)),
                8,
                0,
                (
                    _r64(
                        "INBOUND15.FILTER_CONFIG",
                        smc_indexed_addr(ib.format("FILTER_CONFIG"), FILTER_LAST),
                        FILTER_ID_SEED,
                    ),
                    _r64(
                        "INBOUND15.START_ADDR",
                        smc_indexed_addr(ib.format("START_ADDR"), FILTER_LAST),
                        FILTER_START_SEED,
                    ),
                ),
                False,
                (None, PASS_ALL_CONFIG, 0),
            ),
            (
                "misc_wrap-0x208",
                _r32("NDMRESET_CLUSTER_COUNT", smc_addr(nd.format("CLUSTER_COUNT"))),
                4,
                0,
                (
                    _r32("NDMRESET_PROCESS", smc_addr(nd.format("PROCESS")), NDM_ABOVE_COUNT),
                    _r32("NDMRESET_REQUEST", smc_addr(nd.format("REQUEST")), ro=True),
                ),
                False,
                (0, 0, 0),
            ),
            (
                "reset_unit-0xC8",
                _r32(
                    "ISOLATE_REQ_FLR_RESET_COUNTER_VALUE",
                    smc_addr(ru.format("ISOLATE_REQ_FLR_RESET_COUNTER_VALUE")),
                    FLR_RESET_MASK,
                ),
                4,
                0,
                (
                    _r32(
                        "ISOLATE_REQ_FLR_COUNTER_VALUE",
                        smc_addr(ru.format("ISOLATE_REQ_FLR_COUNTER_VALUE")),
                        FLR_COUNTER_MASK,
                    ),
                    _r32("ISOLATE_REQ_VIS", smc_addr(ru.format("ISOLATE_REQ_VIS")), ro=True),
                ),
                True,
                (0, 0, 0),
            ),
            (
                "gpio-slot64",
                g64[2],
                4,
                PROT_PRIVILEGED,
                (g64[0], g64[1], g63[2]),
                False,
                (0, 0, 0),
            ),
        )

    async def _seed_extent(self, fam: Fam) -> None:
        """S1 seeds of the writable registers below each extent-edge burst start."""
        count = None
        for key, live, _width, prot, below, *_rest in self.ext:
            if key == "misc_wrap-0x208":
                count = await self._rd(fam, "SEP_IN", f"EXT_SNAP_{live.name}", live.addr, 4)
                assert count is not None and count < 32, f"{live.name} reads {_hx(count)}"
                self.ndm_mask = 0xFFFF_FFFF & ~((1 << count) - 1)
            for reg in below:
                if reg.ro:
                    continue
                self.ext_orig[reg] = await self._rd(
                    fam, "SEP_IN", f"EXT_SNAP_{reg.name}", reg.addr, reg.width, prot
                )
                await self._seed(fam, reg, "EXT_SEED", prot)

    async def _reseed_extent(self, fam: Fam) -> None:
        """Re-seed the extent-edge lower registers that an island or strobe step also writes."""
        earlier = {r for isl in self.i64 + self.i32 for r in isl.regs + isl.neighbours}
        for key, _live, _width, prot, below, *_rest in self.ext:
            for reg in below:
                if reg in earlier and not reg.ro:
                    cocotb.log.info(
                        "INFO-RESEED: %s %s is also an island register (S3, S4 write it); "
                        "seeded again before the extent-edge bursts",
                        key,
                        reg.name,
                    )
                    await self._seed(fam, reg, "EXT_RESEED", prot)

    async def _extent_edge(self, port: str, pidx: int) -> int:
        fam = self.fams["EXTENTEDGE"]
        n = 0
        for key, live, width, prot, below, distinct, tail in self.ext:
            start = live.addr
            ctx = f"EXTENTEDGE {port}/{key} 0x{start:x}"
            for reg in below:
                pre = await self._rd(
                    fam, "SEP_IN", f"EXT_PRE_{reg.name}", reg.addr, reg.width, prot
                )
                if not reg.ro and not reg.same(pre, self.ref[reg]):
                    fam.findings.append(
                        f"{ctx}: {reg.name} reads {_hx(pre)} before the burst, seeded "
                        f"0x{self.ref[reg]:x}"
                    )
            pre_live = await self._rd(
                fam, "SEP_IN", f"EXT_LIVE_PRE_{live.name}", start, width, prot
            )
            item, hs = await self._issue(
                port, f"EXT_{key}_RD", start, write=False, beats=4, prot=prot
            )
            r = self._check_read(fam, ctx + " read", port, item, hs)
            self._cell(fam, "S1", f"{port}/{key}/rd")
            if pre_live is None:
                live_value = 0
            elif distinct:
                live_value = self._seed_value(
                    Reg(live.name, live.addr, width, live.seed_mask or ALL64)
                )
            else:
                live_value = pre_live
            if key == "alias_remap-slot7":
                assert not (pre_live or 0) & ALIAS_VALID, "alias slot 7 REGION_ATTRS.valid is set"
                live_value &= ~ALIAS_VALID
            wbeats = [live_value] + [live_value if t is None else t for t in tail]
            item, hs = await self._issue(
                port, f"EXT_{key}_WR", start, write=True, beats=4, wdata=_pack(wbeats), prot=prot
            )
            bresp = self._check_write(fam, ctx + " write", port, item, hs)
            self._cell(fam, "S2", f"{port}/{key}/wr")
            for reg in below:
                got = await self._rd(
                    fam, "SEP_IN", f"EXT_POST_{reg.name}", reg.addr, reg.width, prot
                )
                if reg.ro:
                    fam.tally(key, reg, None)
                    self._protocol_only(ctx, reg, got)
                    continue
                self._unchanged(fam, key, ctx, reg, got, self.ref[reg], wbeats)
            post_live = await self._rd(
                fam, "SEP_IN", f"EXT_LIVE_POST_{live.name}", start, width, prot
            )
            if distinct:
                taken = "y" if post_live == live_value else "n"
            else:
                taken = "same-value"
            self._obs(
                fam,
                port=port,
                island=key,
                rresp=self._codes(r),
                rdata=self._datas(r),
                bresp=_rname(bresp),
                live_taken=taken,
                live_before=_hx(pre_live),
                live_after=_hx(post_live),
            )
            fam.bursts += 2
            n += 2
            if distinct and pre_live is not None:
                await self._wr(
                    fam, "SEP_IN", f"EXT_RESTORE_{live.name}", start, pre_live, width, prot
                )
        await self._live(fam, port, "S3", f"{port}/after-extentedge")
        return n

    async def _extent_restore(self, fam: Fam) -> None:
        for _key, _live, _width, prot, below, *_rest in self.ext:
            for reg in below:
                value = self.ext_orig.get(reg)
                if value is not None:
                    await self._wr(
                        fam, "SEP_IN", f"EXT_RESTORE_{reg.name}", reg.addr, value, reg.width, prot
                    )

    # --------------------------------------------------------------- rule ends

    async def _rule_ends(self, port: str, pidx: int) -> int:
        rule = self.fams["RULEEDGE"]
        region = self.fams["REGIONEDGE"]
        n = 0
        spm_last = SPM_MEMORY_BASE + SPM_SIZE - BEAT
        start = spm_last - 7 * BEAT
        ctx = f"RULEEDGE {port}/spm-end 0x{start:x}"
        cla_pre = await self._rd(rule, port, "CLA_PRE", CLA_BASE, 4)
        data = [((0xC0 + pidx) << 56) | (i << 24) | 0x00E7_D000 | i for i in range(8)]
        item, hs = await self._issue(
            port, "SPM_END_WR", start, write=True, beats=8, wdata=_pack(data)
        )
        self._check_write(rule, ctx, port, item, hs, OKAY)
        item, hs = await self._issue(port, "SPM_END_RD", start, write=False, beats=8)
        r = self._check_read(rule, ctx, port, item, hs, OKAY)
        rule.compares += 1
        if [b.data for b in r] != data:
            rule.findings.append(f"{ctx}: read beats {self._datas(r)} differ from the written data")
        cla_post = await self._rd(rule, port, "CLA_POST", CLA_BASE, 4)
        rule.compares += 1
        if cla_post != cla_pre or cla_pre is None:
            rule.findings.append(f"{ctx}: first CLA word {_hx(cla_pre)} -> {_hx(cla_post)}")
        self._cell(rule, "S1", f"{port}/spm-end")
        rule.bursts += 2
        n += 2
        _first, cpu_last = generated_window("smc_cpu_ctrl")
        cpu_start = LOCAL_BASE_RESET + (cpu_last & ~(BEAT - 1)) - 7 * BEAT
        ctx = f"RULEEDGE {port}/cpu_ctrl-end 0x{cpu_start:x}"
        item, hs = await self._issue(port, "CPU_END_RD", cpu_start, write=False, beats=8)
        r = self._check_read(rule, ctx, port, item, hs)
        self._obs(rule, port=port, rresp=self._codes(r), rdata=self._datas(r))
        self._cell(rule, "S2", f"{port}/cpu_ctrl-end")
        rule.bursts += 1
        n += 1
        base = GLOBAL_BASE_RESET if port == "SYS_IN" else LOCAL_BASE_RESET
        rs_start = base + REGION_SIZE_RESET - 16 * BEAT
        ctx = f"REGIONEDGE {port}/rs16M-end 0x{rs_start:x}"
        item, hs = await self._issue(port, "RS16M_RD", rs_start, write=False, beats=16)
        r = self._check_read(region, ctx + " read", port, item, hs)
        self._cell(region, "S1", f"{port}/rs16M-end/rd")
        payload = _pack([((0xD0 + pidx) << 56) | 0x16_0000 | i for i in range(16)])
        item, hs = await self._issue(
            port, "RS16M_WR", rs_start, write=True, beats=16, wdata=payload
        )
        bresp = self._check_write(region, ctx + " write", port, item, hs)
        self._cell(region, "S1", f"{port}/rs16M-end/wr")
        self._obs(
            region,
            port=port,
            rs=hex(REGION_SIZE_RESET),
            rresp=self._codes(r),
            bresp=_rname(bresp),
            restore_bresp="-",
        )
        region.bursts += 2
        n += 2
        return n

    # --------------------------------------------------------------- 1K window

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

    @staticmethod
    def _region_size_out() -> int | None:
        """The REGION_SIZE CSR value on the DUT output ``smc_region_size_o``.

        Once the window is 1 KiB the CSR lies beyond it, so no inbound port can read it back.
        """
        value = cocotb.top.smc_region_size.value
        return int(value) if value.is_resolvable else None

    async def _window_1k(self) -> int:
        fam = self.fams["REGIONEDGE"]
        n = 0
        wdt_pre = {
            name: await self._rd(fam, "SEP_IN", f"WDT_PRE_{name}", addr, 4)
            for name, addr in WDT_REGS
        }
        # Unlock the core-0 watchdog so a beat that wraps onto CTRL / COUNT lands (wdt.rdl drops a
        # write while locked, and every landed write relocks, so KEY reading 1 after the bursts
        # shows nothing landed).
        await self._wr(fam, "SEP_IN", "WDT_KEY_UNLOCK", WDT_KEY_REG, WDT_KEY, 4)
        key = await self._rd(fam, "SEP_IN", "WDT_KEY_UNLOCKED", WDT_KEY_REG, 4)
        cocotb.log.info(
            "CTRL-BT-WDT-UNLOCKED: core-0 WDT KEY reads %s after the 0x%x write (want 1)",
            _hx(key),
            WDT_KEY,
        )
        assert key == 1, (
            f"core-0 WDT KEY reads {_hx(key)} after the 0x{WDT_KEY:x} write: the 1 KiB window "
            f"legs would run against a locked watchdog"
        )
        wdt_pre["KEY"] = key
        before = self._region_size_out()
        await self._wr(fam, "SEP_IN", "REGION_SIZE_1K", REGION_SIZE_REG, REGION_SIZE_1K)
        after = self._region_size_out()
        self.rs_1k = (before, after)
        fam.compares += 2
        if before != REGION_SIZE_RESET or after != REGION_SIZE_1K:
            fam.findings.append(
                f"REGIONEDGE smc_region_size_o reads {_hx(before)} before and {_hx(after)} after "
                f"the REGION_SIZE write, want 0x{REGION_SIZE_RESET:x} then 0x{REGION_SIZE_1K:x}"
            )
        cocotb.log.info(
            "CTRL-BT-REGION-SIZE-1K: smc_region_size_o %s before, %s after the REGION_SIZE write "
            "(want 0x%x then 0x%x)",
            _hx(before),
            _hx(after),
            REGION_SIZE_RESET,
            REGION_SIZE_1K,
        )
        assert after == REGION_SIZE_1K, (
            f"REGION_SIZE output reads {_hx(after)} after the 0x{REGION_SIZE_1K:x} write: the 1 KiB "
            f"window legs would run at the reset size"
        )
        rows = []
        for pidx, port in enumerate(PORTS):
            base = GLOBAL_BASE_RESET if port == "SYS_IN" else LOCAL_BASE_RESET
            start = base + WINDOW_1K_OFFSET
            ctx = f"REGIONEDGE {port}/rs1K-cross 0x{start:x}"
            item, hs = await self._issue(port, "RS1K_RD", start, write=False, beats=4)
            r = self._check_read(fam, ctx + " read", port, item, hs)
            self._cell(fam, "S2", f"{port}/rs1K-cross/rd")
            payload = _pack([((0xE0 + pidx) << 56) | 0x1_0000 | i for i in range(4)])
            item, hs = await self._issue(port, "RS1K_WR", start, write=True, beats=4, wdata=payload)
            bresp = self._check_write(fam, ctx + " write", port, item, hs)
            self._cell(fam, "S2", f"{port}/rs1K-cross/wr")
            rows.append((port, r, bresp))
            fam.bursts += 2
            n += 2
        item, hs = await self._issue(
            "SEP_IN", "REGION_SIZE_RESTORE", REGION_SIZE_REG, write=True, wdata=REGION_SIZE_RESET
        )
        restore = self._check_write(
            fam, "REGIONEDGE SEP_IN REGION_SIZE restore at 1 KiB", "SEP_IN", item, hs
        )
        for port, r, bresp in rows:
            self._obs(
                fam,
                port=port,
                rs=hex(REGION_SIZE_1K),
                rresp=self._codes(r),
                rdata=self._datas(r),
                bresp=_rname(bresp),
                restore_bresp=_rname(restore),
            )
        for name, addr in WDT_REGS:
            got = await self._rd(fam, "SEP_IN", f"WDT_POST_{name}", addr, 4)
            fam.compares += 1
            if got != wdt_pre[name]:
                what = "relocked (a write landed)" if name == "KEY" else "changed"
                fam.findings.append(
                    f"REGIONEDGE unlocked core-0 watchdog {name} {what}: {_hx(wdt_pre[name])} -> "
                    f"{_hx(got)} after the 1 KiB window bursts"
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
        await self._admit(self.fams["SETUP"], "REARM")
        rs = await self._rd(fam, "SEP_IN", "REGION_SIZE_AFTER_RESET", REGION_SIZE_REG)
        fam.compares += 1
        if rs != REGION_SIZE_RESET:
            fam.findings.append(
                f"REGIONEDGE REGION_SIZE after the primary reset reads {_hx(rs)}, "
                f"want 0x{REGION_SIZE_RESET:x}"
            )
        wdt_reset = []
        for name, addr in WDT_REGS:
            got = await self._rd(fam, "SEP_IN", f"WDT_RESET_{name}", addr, 4)
            wdt_reset.append(f"{name}={_hx(got)}")
        cocotb.log.info(
            "INFO-WDT: core-0 watchdog after the primary reset %s (before the leg %s)",
            " ".join(wdt_reset),
            " ".join(f"{k}={_hx(v)}" for k, v in wdt_pre.items()),
        )
        for port in PORTS:
            await self._live(fam, port, "S4", f"{port}/after-regionedge")
            n += 1
        return n

    # ------------------------------------------------------------------ body

    async def _admit(self, fam: Fam, tag: str) -> None:
        for name, addr, value in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("START", INBOUND0_START, 0),
            ("END", INBOUND0_END, PASS_ALL_END),
        ):
            await self._wr(fam, "SEP_IN", f"{tag}_INBOUND0_{name}", addr, value)
        for name, addr, value in (
            ("CONFIG", INBOUND0_FILTER_CONFIG, PASS_ALL_CONFIG),
            ("START", INBOUND0_START, 0),
            ("END", INBOUND0_END, PASS_ALL_END),
        ):
            got = await self._rd(fam, "SEP_IN", f"{tag}_INBOUND0_{name}_RB", addr)
            if got != value:
                fam.findings.append(
                    f"{tag} inbound entry 0 {name} reads {_hx(got)}, want 0x{value:x}"
                )
        item, hs = await self._issue("SYS_IN", f"{tag}_ADMIT", LOCAL_BASE_REG, write=False)
        admit = Fam("ADMIT", "", "", "", ())
        r = self._check_read(admit, f"CTRL-M4-ADMIT {tag}", "SYS_IN", item, hs, OKAY)
        assert not admit.findings and r and r[0].data == LOCAL_BASE_RESET, (
            f"SYS_IN read of LOCAL_BASE through inbound entry 0 answered "
            f"{self._codes(r)} {self._datas(r)}: {admit.findings}"
        )
        cocotb.log.info(
            "CTRL-M4-ADMIT: %s SYS_IN 64-bit read of LOCAL_BASE @ 0x%x through pass-all inbound "
            "entry 0 (allow_burst=1) answered OKAY %s RID %d",
            tag,
            LOCAL_BASE_REG,
            _hl(r[0].data),
            r[0].ident,
        )

    def _decerr_addrs(self) -> set[int]:
        """Start addresses of the bursts whose response code the contract leaves open."""
        addrs: set[int] = {REGION_SIZE_REG}
        for isl in self.i64 + self.i32:
            addrs.update(self._shape_start(isl, b) for _s, b, _w, _c in SHAPES)
        stride = smc_addr("SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_STRIDE")
        slot_k = smc_indexed_addr(
            "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_BASE_ADDR", ALIAS_EDGE_K
        )
        addrs.update((slot_k + 0x10, slot_k + stride + 0x10))
        for _k, live, *_rest in self._extent_targets():
            addrs.add(live.addr)
        _first, cpu_last = generated_window("smc_cpu_ctrl")
        addrs.add(LOCAL_BASE_RESET + (cpu_last & ~(BEAT - 1)) - 7 * BEAT)
        addrs.add(LOCAL_BASE_RESET + REGION_SIZE_RESET - 16 * BEAT)
        addrs.add(LOCAL_BASE_RESET + WINDOW_1K_OFFSET)
        for pidx in range(len(PORTS)):
            region = SPM_MEMORY_BASE + 0x2_0000 + pidx * 0x1_0000
            for j, ln in enumerate(SPM_WRAP_LENS):
                addrs.add(region + (3 + j) * PAGE + 0x100 + (ln + 1) * BEAT // 2)
            addrs.add(region + 7 * PAGE + 0x200)
        return addrs

    async def body(self) -> None:
        dut = cocotb.top
        await self.wait_fuse_sense_done(FUSE_WAIT_BOUND_SMC_CYCLES)
        states = []
        for name in ("tb_fuse_sense_done", "tb_fuse_reset_n", "tb_rst_warm_smc_clk_n"):
            sig = getattr(dut, name)
            assert sig.value.is_resolvable, f"{name} is X/Z after the wait"
            states.append(f"{name}={int(sig.value)}")
        self.fuse_state = ",".join(states)
        self.sampler = SmcPortHandshakeSampler(dut)
        cocotb.start_soon(self.sampler.run())
        try:
            await self._run()
        except BaseException:
            self._log_waits("INFO-TIMEOUT-PATHS")
            raise

    async def _run(self) -> None:
        setup = self.fams["SETUP"]
        self.env.axi_monitor.expected_decerr_addrs.update(self._decerr_addrs())
        await self._admit(setup, "S1")
        for isl in self.i64 + self.i32 + (self.edge, self.gpio_isl):
            self._check_window(isl)
        cocotb.log.info(
            "INFO-HW-BITS: GPIO DATA_CTRL pad2core and lsio_enable (mask 0x%x) are read-only "
            "fields the pad and LSIO hardware drive; unchanged compares exclude them",
            GPIO_DATA_CTRL_HW,
        )
        for slot in (0, ALIAS_LAST_SLOT):
            attrs = _alias_regs(slot)[2]
            got = await self._rd(setup, "SEP_IN", f"ALIAS{slot}_ATTRS_SNAP", attrs.addr)
            assert got is not None and not got & ALIAS_VALID, (
                f"alias slot {slot} REGION_ATTRS {_hx(got)} has valid set: a burst landing there "
                "would change live address translation"
            )
        for isl in self.i64 + self.i32 + (self.edge,):
            await self._seed_island(isl, setup)
        await self._seed_extent(setup)
        self._mark("ADMIT", self.setup_compares, len(self.ref))

        fam = self.fams["ISLAND64"]
        for pidx, port in enumerate(PORTS):
            for iidx, isl in enumerate(self.i64):
                await self._island(fam, isl, port, pidx, iidx)
        self._mark("ISLAND64", fam.bursts, len(PORTS) * len(self.i64) * len(SHAPES))
        self._report(fam)

        fam = self.fams["ISLAND32"]
        for pidx, port in enumerate(PORTS):
            for iidx, isl in enumerate(self.i32):
                await self._island(fam, isl, port, pidx, 3 + iidx)
        self._mark("ISLAND32", fam.bursts, len(PORTS) * len(self.i32) * len(SHAPES))
        self._report(fam)

        count = 0
        for pidx, port in enumerate(PORTS):
            count += await self._strobes(port, pidx)
        self._mark("STROBES", count, 9 * len(PORTS))
        self._report(self.fams["STRB"])

        count = 0
        for pidx, port in enumerate(PORTS):
            count += await self._gpio(port, pidx)
        self._mark("GPIO", count, 6 * len(PORTS))
        self._report(self.fams["GPIO"])

        count = 0
        for pidx, port in enumerate(PORTS):
            count += await self._spm(port, pidx)
        planned = 2 * len(SPM_INCR_LENS) + 2 * len(SPM_WRAP_LENS) + 2 + 4 + 1
        self._mark("SPM", count, planned * len(PORTS))
        self._report(self.fams["SPM"])

        count = 0
        for pidx, port in enumerate(PORTS):
            count += await self._slot_edge(port, pidx)
        self._mark("SLOT_EDGE", count, 5 * len(PORTS))
        self._report(self.fams["SLOTEDGE"])

        count = 0
        await self._reseed_extent(self.fams["EXTENTEDGE"])
        for pidx, port in enumerate(PORTS):
            count += await self._extent_edge(port, pidx)
        await self._extent_restore(self.fams["EXTENTEDGE"])
        self._mark("EXTENT_EDGE", count, 2 * len(self._extent_targets()) * len(PORTS))
        self._report(self.fams["EXTENTEDGE"])

        count = 0
        for pidx, port in enumerate(PORTS):
            count += await self._rule_ends(port, pidx)
        self._mark("RULE_ENDS", count, 5 * len(PORTS))
        self._report(self.fams["RULEEDGE"])

        for port in PORTS:
            await self._live(self.fams["RULEEDGE"], port, None, f"{port}/after-rule-ends")
        self._mark("LIVENESS", self.live_reads, 11 * len(PORTS))

        count = await self._window_1k()
        self._mark("WINDOW_1K", count, 3 * len(PORTS))
        self._report(self.fams["REGIONEDGE"])

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
        if self.fams["SETUP"].findings:
            self.other_findings.extend(f"SETUP: {f}" for f in self.fams["SETUP"].findings)
        rst = cocotb.top.rst_primary_smc_clk_no.value
        for port in PORTS:
            cocotb.log.info(
                "INFO-CLASSIFY: port=%s unanswered=0; ocah_axi_sva fires are simulator records "
                "in this log; last %s; rst_primary_smc_clk_no=%s",
                port,
                self.sampler.describe(port),
                int(rst) if rst.is_resolvable else "X",
            )
        self.failed = [
            f"{f.key}: {len(f.findings)} finding(s), first: {f.findings[0]}"
            for f in self.fams.values()
            if f.findings and f.key != "SETUP"
        ] + self.other_findings

    def _report(self, fam: Fam) -> None:
        for scen, cell in fam.planned:
            cocotb.log.info(
                "INFO-CELL: %s %s %s driven=%d", fam.key, scen, cell, fam.cells.get((scen, cell), 0)
            )
        missing = [f"{s} {c}" for s, c in fam.planned if not fam.cells.get((s, c))]
        if missing:
            fam.findings.append(f"{len(missing)} planned cells not driven, first {missing[:3]}")
        for finding in fam.findings:
            cocotb.log.info("INFO-FINDING: %s %s", fam.key, finding)
        for island, (fails, cannot, protocol) in fam.per_island.items():
            cocotb.log.info(
                "INFO-COMPARES: %s %s %d unchanged compares that can fail, %d that cannot "
                "(reference equal to a beat), protocol-only cells [%s]",
                fam.key,
                island,
                fails,
                cannot,
                ", ".join(sorted(protocol)) or "none",
            )
        if fam.findings:
            return
        cells = len(fam.planned)
        if fam.key == "EXTENTEDGE":
            cocotb.log.info(
                "CHK-BT-EXTENTEDGE: %d extent-edge bursts x 3 ports, protocol held, seeded lower "
                "registers unchanged (%d compares that can fail), read-only lower registers "
                "protocol-only, liveness OKAY",
                fam.bursts,
                fam.failable,
            )
            cocotb.log.info(
                "INFO-CHK-BT-EXTENTEDGE: %d cells of %d planned, %d graded accesses",
                len(fam.cells),
                cells,
                fam.graded,
            )
            return
        text = {
            "ISLAND64": f"{fam.bursts} bursts on 3 islands x 3 ports, protocol held, "
            f"BRESP OKAY where every beat lands on a register, INCR data landed "
            f"({fam.data_compares} register compares), out-of-footprint registers unchanged, "
            f"liveness OKAY",
            "ISLAND32": f"{fam.bursts} bursts on 3 islands x 3 ports, protocol held, "
            f"INCR BRESP OKAY with data landed ({fam.data_compares} register compares) where "
            f"every beat lands on a register, multi-beat FIXED/WRAP BRESP open under #3598 "
            f"(OBS-BT-ISLAND32), out-of-footprint registers unchanged, liveness OKAY",
            "STRB": f"{fam.bursts} strobed writes and pair reads, only strobed lanes changed, "
            f"64-bit pair assembly as stated",
            "GPIO": f"{fam.bursts} GPIO bursts x 3 ports, protocol held, INCR data landed where "
            f"the write answers OKAY ({fam.data_compares} register compares), seeded slots "
            f"GPIO{GPIO_K - 1}..GPIO{GPIO_K + 3} unchanged outside each footprint, liveness OKAY",
            "SPM": "INCR data match, WRAP/FIXED protocol held, strobes exact, ROM write SLVERR "
            "unchanged, liveness OKAY",
            "SLOTEDGE": f"{fam.bursts} slot-edge bursts x 3 ports, protocol held, INCR data "
            f"landed where the write answers OKAY ({fam.data_compares} register compares), "
            f"out-of-footprint slots unchanged, liveness OKAY",
            "RULEEDGE": "scratchpad-end burst OKAY with data, CLA word unchanged, CPU-control-end "
            "read protocol held",
            "REGIONEDGE": f"window-end bursts protocol held, 1 KiB legs run with "
            f"smc_region_size_o {_hx(self.rs_1k[1])} (was {_hx(self.rs_1k[0])}), watchdog "
            f"unchanged, REGION_SIZE 0x{REGION_SIZE_RESET:08X} and liveness after recovery",
        }[fam.key]
        cocotb.log.info(
            "%s: %s (%d cells of %d planned, %d graded accesses, %d reference compares)",
            fam.chk,
            text,
            len(fam.cells),
            cells,
            fam.graded,
            fam.compares,
        )

    def raise_findings(self) -> None:
        assert not self.failed, "burst-type island findings: " + " | ".join(self.failed)

    def _log_waits(self, prefix: str) -> None:
        cocotb.log.info(
            "%s: %d bounded waits, %d expired: wait_fuse_sense_done sub-waits (tb_fuse_sense_done, "
            "tb_fuse_reset_n, tb_rst_warm_smc_clk_n) bounded %d clk_smc_i rises each, before the "
            "first access and after the primary reset, last %s; %d inbound accesses each bounded "
            "%d ns by First(task, Timer), the expiry path printing INFO-CLASSIFY (last AR/AW/W/R/B "
            "handshake of the port and rst_primary_smc_clk_no) and failing the leaf, longest answer "
            "%d ns, driver backup timeout %d ns; reset waits [%s] each failing on expiry with the "
            "last sampled reset state; last access %s",
            prefix,
            self.waits + 6 + len(self.reset_waits),
            self.expired,
            FUSE_WAIT_BOUND_SMC_CYCLES,
            self.fuse_state,
            self.waits,
            ACCESS_BOUND_NS,
            self.max_wait_ns,
            DRIVER_TIMEOUT_NS,
            "; ".join(self.reset_waits) or "none reached",
            self.last_access,
        )

    def log_timeout_paths(self) -> None:
        self._log_waits("CHK-TIMEOUT-PATHS")

    def nonvac_fence(self) -> None:
        terms = tuple(t for t, _time, _n, _p in self.fence)
        assert terms == FENCE, f"fence terms {terms}, want {FENCE}"
        times = [time for _t, time, _n, _p in self.fence]
        assert all(b > a for a, b in zip(times, times[1:])), f"fence times not increasing: {times}"
        for term, _time, n, planned in self.fence:
            assert n > 0 and n >= planned, f"{term}: {n} against {planned} planned"
        cocotb.log.info(
            "CHK-NONVAC: %s (time and count per term: %s)",
            " < ".join(FENCE),
            ", ".join(f"{t}@{time}ps={n}/{p}" for t, time, n, p in self.fence),
        )


def _hx(value: int | None) -> str:
    return "X" if value is None else hex(value)
