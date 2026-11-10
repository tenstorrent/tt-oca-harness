# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Alias remap and SEP output remap windows, offsets and cache attributes at seed-drawn cells.

``hw/ip/axi_alias_remap/regs/alias_remap.rdl``: a region with ``valid`` set translates an address
in [``start_addr``, ``end_addr``) by adding ``offset`` to bits [55:12], keeps the low 12 bits, and
its ``cacheable`` value overrides every AxCACHE bit; ``end_addr`` is non-inclusive.
``hw/ip/output_remap/regs/output_remap.rdl``: a region with ``valid`` set remaps an access by
``offset``; with ``valid`` clear the access passes unchanged. The SEP AP and STEE tables have 16
regions of 512 KiB each (``sep_addr.h``), so the leaving address keeps the 19 in-window bits.

The SMC fabric JTAG2AXI bridge drives the alias table and its accesses; the SEP debug module's
system bus (RISC-V Debug Specification 0.13, "System Bus Access") drives the AP and STEE tables and
their accesses. Every access leaves on ``u_axi_out_if``, where a passive tap records AxADDR and
AxCACHE, and the bench responder holds the bytes.

Every table is exercised on every seed. The seed draws, per table, the region index, the window
(alias: 4 KB-granule start page and length; output: the fixed 512 KiB window of the region) and
the offset, the low address bits of the alias cells and the in-window word of the output cells,
and the alias ``cacheable`` value among those that differ from the reference AxCACHE. Pinned on
every seed: the hit at start, the hit one granule below ``end_addr`` and the misses one granule
below ``start_addr`` and at ``end_addr``; a hit at the ``cacheable`` value whose four bits all
differ from the reference AW AxCACHE; the last word inside each output window and the first word
past it; ``valid`` cleared after programming on every table (on an output table graded at an index
other than 7, at which it is logged).

S1: JTAG2AXI tap, apertures, reference write and read outside every region (AxCACHE reference,
    cross-checked against the AxCACHE the bridge issues on the DTP-to-SMC debug AXI tap).
S2: alias region programmed at the pinned ``cacheable`` and read back; the pinned hit.
S3: alias region at the drawn ``cacheable``, read back; hits at start and one granule below end.
S4: alias misses one granule below start and at ``end_addr``.
S5: alias ``valid`` cleared, read back; the access at start passes unchanged.
S6: two valid alias regions over one page leave by the lowest-numbered region's offset and an
    offset sum past bit 55 leaves at the sum modulo 2^44 (``alias_remap.rdl``, ``offset``); the
    second region is drawn above or below the drawn region, its registers and the drawn region's
    re-set ATTRS are read back before the access, so a lost write fails the read-back and the
    leaving address grades the priority in either ordering; restore.
S7: SEP debug module, admit pair, AP and STEE regions programmed and read back.
S8: output hits at the drawn word and at the last word of each window.
S9: output misses at the first word past each window.
S10: output ``valid`` cleared, read back; the drawn word passes unchanged; restore.
S11: every bounded wait reports its bound, its use and its last state.
"""

from __future__ import annotations

import random

import cocotb
from cocotb.triggers import ClockCycles, RisingEdge
from cocotb.utils import get_sim_time
from ocah_jtag_vip import OcahJtagState

from seq_lib.smu_addr_map import (
    _REPO_ROOT,
    c_header_u32,
    smc_addr,
    smc_indexed_addr,
)
from seq_lib.smu_alias_priority_overflow_test_seq import FIELDS, _OutboundTap
from seq_lib.smu_boundary_regs import smc_base_config_u32
from seq_lib.smu_compose_helpers import sample
from seq_lib.smu_dtp_sep_dm_dmi_test_seq import (
    DMI_OP_READ,
    smu_dtp_sep_dm_dmi_test_seq,
)
from seq_lib.smu_dtp_sep_dm_sba_test_seq import SBDATA1_ADDR, _indexed_addr
from seq_lib.smu_jtag_helpers import (
    DTP_DEFAULT_IDCODE,
    J2A_STATUS_BUSY,
    J2A_STATUS_SUCCESS,
    jtag2axi_single_read,
    jtag2axi_single_write,
    make_smu_jtag_tap,
    require_jtag_tdo_resolved,
)
from seq_lib.smu_lc_export_seq import _ReadCounter
from seq_lib.smu_sep_out_filter_rule_matrix_test_seq import (
    ADMIT_ENTRY_HIGH,
    ADMIT_ENTRY_LOW,
    OBSERVE_BOUND_CYCLES,
    SIZE_DOUBLEWORD,
    _config,
    smu_sep_out_filter_rule_matrix_test_seq,
)
from seq_lib.smu_sep_sba_fabric_sweep_test_seq import (
    _OUTPUT_REMAP_H,
    _SEP_ADDR_H,
    ADDR_MASK,
    AP_REGION_BASE,
    SMU_BASE,
    SMU_SIZE,
    STEE_REGION_BASE,
)

_ALIAS_REMAP_H = _REPO_ROOT / "hw/ip/axi_alias_remap/regs/gen/c/alias_remap.h"
_SEP_CPU_CTRL_H = _REPO_ROOT / "hw/sys/sep/regs/gen/c/blocks/sep_cpu_ctrl.h"

# alias_remap.h REGION_START / REGION_END / REGION_ATTRS fields.
ALIAS_ADDR_BM = c_header_u32(
    _ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_START__START_ADDR_bm"
)
ALIAS_OFFSET_BM = c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bm")
ALIAS_OFFSET_BP = c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__OFFSET_bp")
ALIAS_CACHE_BM = c_header_u32(
    _ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__CACHEABLE_bm"
)
ALIAS_CACHE_BP = c_header_u32(
    _ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__CACHEABLE_bp"
)
ALIAS_VALID_BM = c_header_u32(_ALIAS_REMAP_H, "ALIAS_REMAP__REMAP_REGION__REGION_ATTRS__VALID_bm")
CACHE_VALUES = (ALIAS_CACHE_BM >> ALIAS_CACHE_BP) + 1
PAGE = 1 << ALIAS_OFFSET_BP
LOW_MASK = PAGE - 1
ADDR56 = (1 << 56) - 1

# smc_addr.h: eight alias regions, each a START, END and ATTRS register.
ALIAS_REGIONS = smc_addr("SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_NUM")
_A_START = "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_START_BASE_ADDR"
_A_END = "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_END_BASE_ADDR"
_A_ATTRS = "SMC_TOP_SMC_ALIAS_REMAP_WRAP_ALIAS_REMAP_REGION_REGION_ATTRS_BASE_ADDR"

# output_remap.h REGION_ATTRS fields; sep_addr.h table and window sizes.
OUT_VALID = c_header_u32(
    _OUTPUT_REMAP_H, "OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__VALID_bm"
)
OUT_OFFSET_BM = c_header_u32(
    _OUTPUT_REMAP_H, "OUTPUT_REMAP__OUTPUT_REMAP_REGION__REGION_ATTRS__OFFSET_bm"
)
OUT_REGIONS = c_header_u32(_SEP_ADDR_H, "SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_NUM")
OUT_REGION_SIZE = c_header_u32(_SEP_ADDR_H, "SEP_TOP_AP_REGION_SIZE") // OUT_REGIONS
_OUT_CSR = {
    "AP": "SEP_TOP_AP_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_BASE_ADDR",
    "STEE": "SEP_TOP_STEE_OUTPUT_REMAP_CTRL_WRAP_OUTPUT_REMAP_REGION_BASE_ADDR",
}
_OUT_WINDOW = {"AP": AP_REGION_BASE, "STEE": STEE_REGION_BASE}
TABLES = ("AP", "STEE")
# Output region indices drawn: 1 to 14 (region 0 stays never programmed; region 15 is the last).
OUT_FIRST, OUT_LAST = 1, OUT_REGIONS - 2
# A drawn output region whose valid-cleared cell is logged, not graded.
OUT_CONTROL_REGION = 7

# SEP and SMC apertures at their generated reset values; the SMC local window and the M-mode and
# Xvisor windows inside it (smc_addr.h, smc_base_config.h, sep_cpu_ctrl.h).
SEP_BASE_RESET = c_header_u32(_SEP_CPU_CTRL_H, "SEP_CPU_CTRL__SEP_GLOBAL_BASE_ADDR__ADDR_reset")
SMC_LOCAL_BASE = smc_base_config_u32("SMC_BASE_CONFIG__LOCAL_BASE__BASE_reset")
SMC_REGION_RESET = smc_base_config_u32("SMC_BASE_CONFIG__REGION_SIZE__SIZE_reset")
MMODE_WINDOW = smc_addr("SMC_TOP_MMODE_REGION_BASE_ADDR")
XVISOR_END = smc_addr("SMC_TOP_XVISOR_REGION_BASE_ADDR") + smc_addr("SMC_TOP_XVISOR_REGION_SIZE")

# Alias input pages, outside the SMC and SEP apertures as smu_alias_priority_overflow_test places
# them; the reference page is the top page of the span, the input windows below it.
INPUT_BASE = 0x8100_0000
INPUT_PAGES = 4096
MIN_PAGES, MAX_PAGES = 2, 16
REF_ADDR = INPUT_BASE + (INPUT_PAGES - 1) * PAGE + 0x100
# Translated pages: above 4 GiB, below 2^40, one range per use.
ALIAS_TARGET_LO, ALIAS_TARGET_HI = 0x1_0000_0000, 0x8_0000_0000
OVERLAP_TARGET_LO, OVERLAP_TARGET_HI = 0x8_0000_0000, 0x10_0000_0000
OUT_TARGET = {"AP": (0x10_0000_0000, 0x40_0000_0000), "STEE": (0x40_0000_0000, 0x80_0000_0000)}
# The page the offset sum past bit 55 lands on, modulo 2^44.
CARRY_WRAP_PAGE = 0x0900_0000

SENTINEL = 0x5A5A_5A5A_5A5A_5A5A
SALT_REDRAW_BOUND = 8
REGION_REDRAW_BOUND = 8
# 13 x 14 slots: slot % len(rest) is uniform over the 13 or 14 values cache_values leaves.
CACHE_DRAW_SLOTS = (CACHE_VALUES - 3) * (CACHE_VALUES - 2)

J2A_POLL_LIMIT = 128
STEP_CLOCK_GAP = 2
STEPS = tuple(f"S{i}" for i in range(1, 12))
J2A_STEPS = ("S1", "S2", "S3", "S4", "S5", "S6")
SBA_STEPS = ("S7", "S8", "S9", "S10")
# JTAG2AXI accesses: S1 2, S2 8, S3 6, S4 4, S5 4, S6 19 (sum 43).
J2A_EXPECTED = 43
# System-bus accesses: S7 6 + 2x2, S8 2x4, S9 2x2, S10 2x(2+2+1) (sum 32).
SBA_EXPECTED = 32
EXPECTED_WAIT_LABELS = (
    "j2a_poll",
    "responder_observe",
    "sba_busy_poll",
    "stated_observe",
)
_CACHE = FIELDS.index("cache")
# The fixed cells of the entries this one extends, named beside each drawn compare.
CONTROLS = {
    "CHK-RMAPA-TRANSLATE": (
        "CHK-ALIASPRI-HIT-TRANSLATE and CHK-ALIASPRI-OFFSET-LOWBITS of "
        "smu_alias_priority_overflow_test"
    ),
    "CHK-RMAPA-CACHE": "CHK-ALIAS-CACHE-HIT of smu_alias_cache_reset_test",
    "CHK-RMAPA-OUTPUT": (
        "CHK-SEPREMAP-AP-REGIONS, CHK-SEPREMAP-STEE-REGIONS, CHK-SEPREMAP-TABLE-INDEP, "
        "CHK-SEPREMAP-AP-INVALID and CHK-SEPREMAP-STEE-INVALID of "
        "smu_sep_output_remap_region_matrix_test"
    ),
    "CHK-RMAPA-READBACK": (
        "CHK-ALIAS-REGS-MASKS and CHK-OREMAP-REGS-MASKS of smu_remap_cfg_register_map_test"
    ),
}


def payload(salt: int, tag: int) -> int:
    """A 64-bit value per access tag; distinct for distinct tags below 256."""
    return (salt ^ (tag * 0x0101_0101_0101_0101)) & ((1 << 64) - 1)


def draw(seed: int) -> dict:
    """Every drawn cell of one run, a pure function of the seed."""
    rng = random.Random(seed)
    d: dict = {"seed": seed}
    d["alias_region"] = rng.randrange(ALIAS_REGIONS)
    d["start_page"] = rng.randint(1, INPUT_PAGES - MAX_PAGES - 3)
    d["n_pages"] = rng.randint(MIN_PAGES, MAX_PAGES)
    d["low"] = 8 * rng.randrange(PAGE // 8)
    span = (ALIAS_TARGET_HI - ALIAS_TARGET_LO) // PAGE - MAX_PAGES
    d["alias_target"] = ALIAS_TARGET_LO + PAGE * rng.randrange(span)
    d["cache_slot"] = rng.randrange(CACHE_DRAW_SLOTS)
    d["overlap_region"] = (d["alias_region"] + rng.randint(1, ALIAS_REGIONS - 1)) % ALIAS_REGIONS
    span = (OVERLAP_TARGET_HI - OVERLAP_TARGET_LO) // PAGE
    d["overlap_target"] = OVERLAP_TARGET_LO + PAGE * rng.randrange(span)
    redraws = 0
    while True:
        for table in TABLES:
            lo, hi = OUT_TARGET[table]
            d[f"{table}_region"] = rng.randint(OUT_FIRST, OUT_LAST)
            d[f"{table}_target"] = lo + OUT_REGION_SIZE * rng.randrange(
                (hi - lo) // OUT_REGION_SIZE
            )
            d[f"{table}_word"] = 8 * rng.randrange(OUT_REGION_SIZE // 8 - 1)
        if d["AP_region"] != OUT_CONTROL_REGION or d["STEE_region"] != OUT_CONTROL_REGION:
            break
        redraws += 1
        if redraws >= REGION_REDRAW_BOUND:
            raise AssertionError(f"seed {seed}: both output regions drawn 7 {redraws} times")
    d["region_redraws"] = redraws
    redraws = 0
    while True:
        d["salt"] = rng.getrandbits(64)
        values = {payload(d["salt"], tag) for tag in range(64)}
        if len(values) == 64 and SENTINEL not in values:
            break
        redraws += 1
        if redraws >= SALT_REDRAW_BOUND:
            raise AssertionError(f"seed {seed}: payload salt redrawn {redraws} times")
    d["salt_redraws"] = redraws
    return d


def check_draw(d: dict) -> None:
    """The filters the entry states; raises on a draw that breaks one."""
    start = INPUT_BASE + d["start_page"] * PAGE
    end = start + d["n_pages"] * PAGE
    facts = (
        (0 <= d["alias_region"] < ALIAS_REGIONS, "alias region index"),
        (d["overlap_region"] != d["alias_region"], "overlap region differs"),
        (MIN_PAGES <= d["n_pages"] <= MAX_PAGES, "window length"),
        (INPUT_BASE + PAGE <= start and end + PAGE < REF_ADDR - 0x100, "input window in span"),
        (d["low"] % 8 == 0 and d["low"] < PAGE, "doubleword low bits"),
        (d["alias_target"] + MAX_PAGES * PAGE <= ALIAS_TARGET_HI, "alias target range"),
        ((d["alias_target"] - start) & ~ALIAS_OFFSET_BM & ADDR56 == 0, "offset field"),
        (d["alias_target"] + MAX_PAGES * PAGE < 1 << 55, "sum below bit 55"),
        (0 <= d["cache_slot"] < CACHE_DRAW_SLOTS, "cache slot"),
        (
            d["AP_region"] != OUT_CONTROL_REGION or d["STEE_region"] != OUT_CONTROL_REGION,
            "a graded output valid-cleared cell",
        ),
    )
    for table in TABLES:
        lo, hi = OUT_TARGET[table]
        t = d[f"{table}_target"]
        facts += (
            (OUT_FIRST <= d[f"{table}_region"] <= OUT_LAST, f"{table} region"),
            (lo <= t and t + OUT_REGION_SIZE <= hi, f"{table} target range"),
            (t % OUT_REGION_SIZE == 0 and t & ~OUT_OFFSET_BM == 0, f"{table} offset field"),
            (d[f"{table}_word"] <= OUT_REGION_SIZE - 16, f"{table} word below the last"),
            (not SMU_BASE <= t < SMU_BASE + SMU_SIZE, f"{table} target clear of the SMU"),
        )
    bad = [name for ok, name in facts if not ok]
    if bad:
        raise AssertionError(f"seed {d['seed']}: draw breaks " + ", ".join(bad))


def cache_values(ref_aw: int, ref_ar: int, slot: int) -> tuple[int, int]:
    """(pinned, drawn) cacheable values, both differing from the AW and AR references."""
    pinned = ~ref_aw & (CACHE_VALUES - 1)
    if pinned == ref_ar:
        pinned = max(v for v in range(CACHE_VALUES) if v not in (ref_aw, ref_ar))
    rest = [v for v in range(CACHE_VALUES) if v not in (ref_aw, ref_ar, pinned)]
    return pinned, rest[slot % len(rest)]


class _IssuedCacheTap:
    """AW and AR AxCACHE on the DTP-to-SMC debug AXI request at every clock its VALID is high."""

    def __init__(self, dut) -> None:
        self._dut = dut
        self.seen: dict[str, list[int]] = {"aw": [], "ar": []}
        self._task = cocotb.start_soon(self._watch())

    async def _watch(self) -> None:
        while True:
            await RisingEdge(self._dut.clk_smu_i)
            for ch, seen in self.seen.items():
                valid = f"dtp_smc_dbg_{ch}_valid_o"
                if sample(getattr(self._dut, valid), valid):
                    cache = f"dtp_smc_dbg_{ch}_cache_o"
                    seen.append(sample(getattr(self._dut, cache), cache))

    def issued(self, ch: str) -> tuple[int, ...]:
        """The distinct AxCACHE values seen on ``ch`` while its VALID was high."""
        return tuple(sorted(set(self.seen[ch])))

    def stop(self) -> None:
        if not self._task.done():
            self._task.cancel()


class smu_remap_attr_rand_test_seq(smu_sep_out_filter_rule_matrix_test_seq):
    """Alias, AP and STEE remap tables at seed-drawn regions, edges, offsets and attributes."""

    def __init__(self, test) -> None:
        super().__init__(test)
        self.seed = test.random_seed()
        self.d = draw(self.seed)
        check_draw(self.d)
        self.step_access = {step: 0 for step in STEPS}
        self.j2a_tap = None
        self.j2a_count = 0
        self.tag = 0
        self.hits = 0
        self.misses = 0
        self.done = False
        self.start = INPUT_BASE + self.d["start_page"] * PAGE
        self.end = self.start + self.d["n_pages"] * PAGE
        self.offset = self.d["alias_target"] - self.start
        self.drawn = (
            f"drawn alias region={self.d['alias_region']} start=0x{self.start:x} "
            f"end=0x{self.end:x} offset=0x{self.offset:x} low=0x{self.d['low']:x} "
            f"cache_slot={self.d['cache_slot']}; "
            + "; ".join(
                f"{t} region={self.d[f'{t}_region']} offset=0x{self.d[f'{t}_target']:x} "
                f"word=0x{self.d[f'{t}_word']:x}"
                for t in TABLES
            )
        )

    def _grade(self, sb, chk: str, observed, expected, text: str, *, evidence: str) -> None:
        if evidence != chk:
            raise AssertionError(f"{chk} graded under evidence {evidence}")
        if chk in CONTROLS:
            self._log(
                f"CONTROL {chk}: the fixed cells {CONTROLS[chk]} are the control of these drawn "
                "cells, graded by that entry and not here"
            )
        self._log(f"{chk}: {text} observed={observed} expected={expected}")
        sb.expect_eq(f"{chk} {text}", observed, expected, evidence=evidence)

    def _next(self) -> int:
        self.tag += 1
        return payload(self.d["salt"], self.tag)

    # JTAG2AXI side.

    async def _j2a(self, write: bool, addr: int, data: int = 0) -> tuple[int, int]:
        kind = "WR" if write else "RD"
        tap = _ReadCounter(self.j2a_tap)
        if write:
            status, raw = await jtag2axi_single_write(tap, addr, data, poll_limit=J2A_POLL_LIMIT)
        else:
            status, raw = await jtag2axi_single_read(tap, addr, poll_limit=J2A_POLL_LIMIT)
        require_jtag_tdo_resolved(f"J2A {kind} @0x{addr:x}")
        last = f"{kind} @0x{addr:x} status={status}"
        if status == J2A_STATUS_BUSY:
            self._site("j2a_poll", J2A_POLL_LIMIT, J2A_POLL_LIMIT + 1, f"EXPIRED {last}", "polls")
            raise AssertionError(f"TIMEOUT j2a_poll {last} after {tap.reads} polls")
        self._site("j2a_poll", J2A_POLL_LIMIT, tap.reads, last, "polls")
        self.j2a_count += 1
        self.step_access[self.step] += 1
        return status, int(raw)

    async def _j2a_ok(self, write: bool, addr: int, data: int = 0) -> int:
        status, raw = await self._j2a(write, addr, data)
        if status != J2A_STATUS_SUCCESS:
            raise AssertionError(f"J2A {'WR' if write else 'RD'} @0x{addr:x} status={status}")
        return raw

    async def _alias_regs(self, region: int, start: int, end: int, attrs: int) -> None:
        for sym, value in ((_A_START, start), (_A_END, end), (_A_ATTRS, attrs)):
            await self._j2a_ok(True, smc_indexed_addr(sym, region), value)

    async def _alias_readback(self, region: int, *syms: str) -> tuple:
        return tuple([await self._j2a_ok(False, smc_indexed_addr(s, region)) for s in syms])

    async def _j2a_pair(self, addr: int, leave: int) -> tuple:
        """Write then read one doubleword; returns (AW, AR, statuses, read data, held, data)."""
        data = self._next()
        mark = self.tap.mark()
        wst, _ = await self._j2a(True, addr, data)
        await self._observe(mark, 1, 0)
        rst, rdata = await self._j2a(False, addr)
        await self._observe(mark, 1, 1)
        aw, ar = self.tap.since(mark)
        return aw[0], ar[0], wst, rst, rdata, self.mem.read_int(leave, 8), data

    async def _j2a_stated(self, addr: int, label: str) -> tuple[int, list[int]]:
        """One JTAG2AXI write whose leaving address the register description states; returns the
        initiator status and the AW addresses tapped on ``u_axi_out_if`` inside the bound."""
        mark = self.tap.mark()
        status, _ = await self._j2a(True, addr, self._next())
        used, aw = 0, []
        while used < OBSERVE_BOUND_CYCLES:
            aw, _ = self.tap.since(mark)
            if aw:
                break
            await ClockCycles(self.clk, 1)
            used += 1
        aw, _ = self.tap.since(mark)
        last = f"{label} aw={[hex(p[0]) for p in aw]}" if aw else f"{label} no AW inside the bound"
        self._site("stated_observe", OBSERVE_BOUND_CYCLES, used, last, "clk_smu cycles")
        self._log(
            f"OBSERVATION {label}: issued=0x{addr:x} status={status} leaving="
            f"{[hex(p[0]) for p in aw] if aw else 'no AW inside the bound'} after {used} "
            f"cycles; graded by CHK-RMAPA-TRANSLATE"
        )
        return status, [p[0] for p in aw]

    def _attrs(self, offset: int, cache: int, valid: bool) -> int:
        word = (offset & ALIAS_OFFSET_BM) | (cache << ALIAS_CACHE_BP)
        return word | (ALIAS_VALID_BM if valid else 0)

    def _prefill(self, *addrs: int) -> None:
        for addr in addrs:
            self.mem.write_int(addr, SENTINEL, 8)

    def _check_apertures(self) -> None:
        smc_base = sample(self.dut.smc_global_base_o, "smc_global_base_o")
        smc_size = sample(self.dut.smc_region_size_o, "smc_region_size_o")
        sep_base = sample(self.dut.sep_global_base_o, "sep_global_base_o")
        sep_size = sample(self.dut.sep_region_size_o, "sep_region_size_o")
        spans = (
            (smc_base, smc_base + smc_size),
            (sep_base, sep_base + sep_size),
            (SMC_LOCAL_BASE, SMC_LOCAL_BASE + SMC_REGION_RESET),
            (MMODE_WINDOW, XVISOR_END),
        )
        inputs = (INPUT_BASE, INPUT_BASE + INPUT_PAGES * PAGE)
        targets = [(lo, hi) for lo, hi in (*OUT_TARGET.values(),)]
        targets += [(ALIAS_TARGET_LO, OVERLAP_TARGET_HI)]
        for lo, hi in (inputs, *targets):
            for a, b in spans:
                if lo < b and a < hi:
                    raise AssertionError(
                        f"window 0x{lo:x}..0x{hi:x} meets aperture 0x{a:x}..0x{b:x}"
                    )
        self._log(
            f"OBSERVATION apertures smc=0x{smc_base:x}+0x{smc_size:x} sep=0x{sep_base:x}+"
            f"0x{sep_size:x} (reset base 0x{SEP_BASE_RESET:x}); inputs and targets clear"
        )

    async def _s1(self, sb) -> None:
        await self.cfg.reset_done.wait()
        self.j2a_tap = jtag = make_smu_jtag_tap(self.dut, self.cfg.jtag_period_ns)
        await jtag.reset_tap()
        await jtag.goto_state(OcahJtagState.RUN_TEST_IDLE)
        for _ in range(8):
            await jtag.step_tms(0)
        idcode = await jtag.read_idcode()
        if idcode != DTP_DEFAULT_IDCODE:
            raise AssertionError(f"IDCODE want 0x{DTP_DEFAULT_IDCODE:x} got 0x{idcode:08x}")
        if sample(self.dut.tb_smc_jtag2axi_security_disable, "j2a gate") & 1:
            raise AssertionError("SMC JTAG2AXI bridge gated")
        self._check_apertures()
        self.tap = _OutboundTap(self.dut)
        self._prefill(REF_ADDR)
        issued = _IssuedCacheTap(self.dut)
        try:
            aw, ar, wst, rst, rdata, _, data = await self._j2a_pair(REF_ADDR, REF_ADDR)
        finally:
            issued.stop()
        self.ref_aw, self.ref_ar = aw[_CACHE], ar[_CACHE]
        self.issued_aw, self.issued_ar = issued.issued("aw"), issued.issued("ar")
        self.cache_pin, self.cache_drawn = cache_values(
            self.ref_aw, self.ref_ar, self.d["cache_slot"]
        )
        self._log(
            f"OBSERVATION reference access 0x{REF_ADDR:x}: aw={aw} ar={ar} status=({wst},{rst}) "
            f"AxCACHE aw={self.ref_aw} ar={self.ref_ar}; cacheable pinned={self.cache_pin} "
            f"drawn={self.cache_drawn}; issued AxCACHE on the DTP-to-SMC debug AXI tap "
            f"aw={self.issued_aw} ar={self.issued_ar}"
        )
        if (aw[0], ar[0], rdata) != (REF_ADDR, REF_ADDR, data):
            raise AssertionError(f"reference access not at its own address: aw={aw} ar={ar}")

    def _leave(self, addr: int, hit: bool) -> int:
        return (addr + self.offset) & ADDR56 if hit else addr

    def _alias_cell(self, got: tuple, addr: int, hit: bool) -> tuple:
        aw, ar, wst, rst, rdata, held, data = got
        leave = self._leave(addr, hit)
        observed = (aw[0], ar[0], aw[0] & LOW_MASK, wst, rst, rdata, held)
        ok = J2A_STATUS_SUCCESS
        expected = (leave, leave, addr & LOW_MASK, ok, ok, data, data)
        return observed, expected, (aw[_CACHE], ar[_CACHE])

    async def _alias(self, sb) -> None:
        d, low, region = self.d, self.d["low"], self.d["alias_region"]
        at_start = self.start + low
        below_end = self.end - PAGE + low
        below_start = self.start - PAGE + low
        at_end = self.end + low
        self._prefill(
            at_start + self.offset,
            below_end + self.offset,
            below_start,
            at_end,
            at_start,
        )
        await self._mark("S2", f"alias region {region} at the pinned cacheable {self.cache_pin}")
        pin_attrs = self._attrs(self.offset, self.cache_pin, True)
        await self._alias_regs(region, self.start, self.end, pin_attrs)
        rb_pin = await self._alias_readback(region, _A_START, _A_END, _A_ATTRS)
        pin_hit = await self._j2a_pair(at_start, self._leave(at_start, True))
        self.hits += 1

        await self._mark("S3", f"alias at the drawn cacheable {self.cache_drawn}: hits")
        drawn_attrs = self._attrs(self.offset, self.cache_drawn, True)
        await self._j2a_ok(True, smc_indexed_addr(_A_ATTRS, region), drawn_attrs)
        (rb_drawn,) = await self._alias_readback(region, _A_ATTRS)
        hit_start = await self._j2a_pair(at_start, self._leave(at_start, True))
        hit_end = await self._j2a_pair(below_end, self._leave(below_end, True))
        self.hits += 2

        await self._mark("S4", "alias misses one granule below start and at end_addr")
        miss_start = await self._j2a_pair(below_start, below_start)
        miss_end = await self._j2a_pair(at_end, at_end)
        self.misses += 2

        await self._mark("S5", "alias valid cleared after programming")
        cleared_attrs = self._attrs(self.offset, self.cache_drawn, False)
        await self._j2a_ok(True, smc_indexed_addr(_A_ATTRS, region), cleared_attrs)
        (rb_cleared,) = await self._alias_readback(region, _A_ATTRS)
        cleared = await self._j2a_pair(at_start, at_start)
        self.misses += 1

        cells = {
            "pinned hit at start": (pin_hit, at_start, True),
            "hit at start": (hit_start, at_start, True),
            "hit one granule below end": (hit_end, below_end, True),
            "miss one granule below start": (miss_start, below_start, False),
            "miss at end_addr": (miss_end, at_end, False),
            "valid cleared at start": (cleared, at_start, False),
        }
        res = {k: self._alias_cell(*v) for k, v in cells.items()}
        translate = ("pinned hit at start", "hit at start", "valid cleared at start")
        self._grade(
            sb,
            "CHK-RMAPA-TRANSLATE",
            {k: res[k][0] for k in translate},
            {k: res[k][1] for k in translate},
            f"(AW, AR, low 12 bits, statuses, read data, responder word) of the hits leave at "
            f"the issued address plus the offset and the valid-cleared access at its own, "
            f"{self.drawn}",
            evidence="CHK-RMAPA-TRANSLATE",
        )
        caches = {k: res[k][2] for k in res}
        caches["reference access (S1)"] = ((self.ref_aw,), (self.ref_ar,))
        want_cache = {
            "reference access (S1)": (self.issued_aw, self.issued_ar),
            "pinned hit at start": (self.cache_pin,) * 2,
            "hit at start": (self.cache_drawn,) * 2,
            "hit one granule below end": (self.cache_drawn,) * 2,
            "miss one granule below start": (self.ref_aw, self.ref_ar),
            "miss at end_addr": (self.ref_aw, self.ref_ar),
            "valid cleared at start": (self.ref_aw, self.ref_ar),
        }
        self._grade(
            sb,
            "CHK-RMAPA-CACHE",
            caches,
            want_cache,
            f"(AW, AR) AxCACHE: hits carry the cacheable value, misses the reference "
            f"(aw={self.ref_aw}, ar={self.ref_ar}), and the reference leaves with the AxCACHE "
            f"the bridge issued on the DTP-to-SMC debug AXI tap (aw={self.issued_aw}, "
            f"ar={self.issued_ar}; fabric.adoc: a transaction that misses every alias region "
            f"keeps the AxCACHE its initiator issued), pinned cacheable={self.cache_pin}, drawn "
            f"cacheable={self.cache_drawn}, {self.drawn}",
            evidence="CHK-RMAPA-CACHE",
        )
        edge = ("hit one granule below end", "miss one granule below start", "miss at end_addr")
        self.edge_obs = {f"alias {k}": res[k][0] for k in edge}
        self.edge_want = {f"alias {k}": res[k][1] for k in edge}
        self.readback_obs = {
            "alias START, END, ATTRS (pinned cacheable)": rb_pin,
            "alias ATTRS (drawn cacheable)": rb_drawn,
            "alias ATTRS (valid cleared)": rb_cleared,
        }
        self.readback_want = {
            "alias START, END, ATTRS (pinned cacheable)": (self.start, self.end, pin_attrs),
            "alias ATTRS (drawn cacheable)": drawn_attrs,
            "alias ATTRS (valid cleared)": cleared_attrs,
        }

        await self._mark("S6", "two valid regions over one page; an offset sum past bit 55")
        other = d["overlap_region"]
        overlap_offset = d["overlap_target"] - self.start
        await self._j2a_ok(True, smc_indexed_addr(_A_ATTRS, region), drawn_attrs)
        other_attrs = self._attrs(overlap_offset, 0, True)
        await self._alias_regs(other, self.start, self.start + PAGE, other_attrs)
        # Both regions read back before the access: the leaving address evidences the second
        # region only when it is the lower-numbered one, and the drawn region only when it is.
        self.readback_obs[
            "alias ATTRS (drawn region re-set for the overlap cell)"
        ] = await self._alias_readback(region, _A_ATTRS)
        self.readback_want["alias ATTRS (drawn region re-set for the overlap cell)"] = (
            drawn_attrs,
        )
        self.readback_obs[
            f"alias region {other} START, END, ATTRS (over the start page)"
        ] = await self._alias_readback(other, _A_START, _A_END, _A_ATTRS)
        self.readback_want[f"alias region {other} START, END, ATTRS (over the start page)"] = (
            self.start,
            self.start + PAGE,
            other_attrs,
        )
        overlap_got = await self._j2a_stated(
            at_start,
            f"overlap regions {region} and {other}: candidates "
            f"0x{at_start + self.offset:x} and 0x{at_start + overlap_offset:x}",
        )
        lowest_offset = self.offset if region < other else overlap_offset
        carry_page = self.end + PAGE
        carry_offset = ((1 << 56) + CARRY_WRAP_PAGE - carry_page) & ALIAS_OFFSET_BM
        await self._alias_regs(
            other, carry_page, carry_page + PAGE, self._attrs(carry_offset, 0, True)
        )
        carry_got = await self._j2a_stated(carry_page + low, "offset sum past bit 55")
        await self._alias_regs(region, 0, 0, 0)
        await self._alias_regs(other, 0, 0, 0)
        # alias_remap.rdl, offset: "When more than one valid region contains the address, the
        # lowest-numbered region applies"; "The addition is modulo 2^44, so a carry out of bit 55
        # is discarded".
        self._grade(
            sb,
            "CHK-RMAPA-TRANSLATE",
            {
                "two valid regions over one page": overlap_got,
                "offset sum past bit 55": carry_got,
            },
            {
                "two valid regions over one page": (
                    J2A_STATUS_SUCCESS,
                    [(at_start + lowest_offset) & ADDR56],
                ),
                "offset sum past bit 55": (
                    J2A_STATUS_SUCCESS,
                    [(carry_page + low + carry_offset) & ADDR56],
                ),
            },
            f"(status, leaving AW addresses) of an address inside valid alias regions {region} "
            f"and {other}, both read back, leave by the lowest-numbered region's offset "
            f"({min(region, other)}; the second region {other} is "
            f"{'below' if other < region else 'above'} the drawn region {region}) and of an "
            f"offset sum past bit 55 leave at the sum modulo 2^44 (alias_remap.rdl, offset: the "
            "lowest-numbered region applies; the addition is modulo 2^44, so a carry out of bit "
            f"55 is discarded), {self.drawn}",
            evidence="CHK-RMAPA-TRANSLATE",
        )

    # System-bus side.

    async def _read64(self, addr: int) -> tuple[int, int]:
        err, low = await self._bus(addr, SIZE_DOUBLEWORD)
        if err:
            return err, 0
        high = await self._dmi(self.jtag, SBDATA1_ADDR, 0, DMI_OP_READ)
        return 0, (high << 32) | low

    async def _sba_pair(self, addr: int, leave: int) -> tuple:
        data = self._next()
        mark = self.tap.mark()
        werr, _ = await self._bus(addr, SIZE_DOUBLEWORD, data)
        if werr == 0:
            await self._observe(mark, 1, 0)
        rerr, rdata = await self._read64(addr)
        if rerr == 0:
            await self._observe(mark, 1, 1)
        aw, ar = self.tap.since(mark)
        held = self.mem.read_int(leave, 8)
        return [p[0] for p in aw], [p[0] for p in ar], werr, rerr, rdata, held, data

    def _out_cell(self, got: tuple, leave: int) -> tuple:
        aw, ar, werr, rerr, rdata, held, data = got
        observed = (aw, ar, werr, rerr, rdata, held)
        return observed, ([leave], [leave], 0, 0, data, data)

    async def _output(self, sb) -> None:
        await self._mark("S7", "SEP debug module, admit pair, AP and STEE regions programmed")
        await smu_dtp_sep_dm_dmi_test_seq.run(self)
        if not (self.s1_ok and self.s2_ok and self.s3_ok):
            raise AssertionError("debug module bring-up incomplete")
        for entry, allow_ns in ((ADMIT_ENTRY_LOW, 0), (ADMIT_ENTRY_HIGH, 1)):
            await self._program(entry, 0, ADDR_MASK, _config(allow_ns))
        cell = {}
        for t in TABLES:
            k, target, word = self.d[f"{t}_region"], self.d[f"{t}_target"], self.d[f"{t}_word"]
            win = _OUT_WINDOW[t] + k * OUT_REGION_SIZE
            cell[t] = {
                "csr": _indexed_addr(_OUT_CSR[t], k),
                "drawn": (win + word, target + word),
                "last": (win + OUT_REGION_SIZE - 8, target + OUT_REGION_SIZE - 8),
                "past": (win + OUT_REGION_SIZE, win + OUT_REGION_SIZE),
                "cleared": (win + word, win + word),
            }
            self._prefill(*(cell[t][name][1] for name in ("drawn", "last", "past", "cleared")))
            await self._bus_ok(cell[t]["csr"], SIZE_DOUBLEWORD, OUT_VALID | target)
            self.readback_obs[f"{t} region {k} ATTRS (valid)"] = await self._read64(cell[t]["csr"])
            self.readback_want[f"{t} region {k} ATTRS (valid)"] = (0, OUT_VALID | target)

        await self._mark("S8", "output hits at the drawn word and the last word of each window")
        obs, want = {}, {}
        for t in TABLES:
            for name in ("drawn", "last"):
                addr, leave = cell[t][name]
                obs[f"{t} {name}"], want[f"{t} {name}"] = self._out_cell(
                    await self._sba_pair(addr, leave), leave
                )
                self.hits += 1
        self._grade(
            sb,
            "CHK-RMAPA-OUTPUT",
            {k: v for k, v in obs.items() if k.endswith("drawn")},
            {k: v for k, v in want.items() if k.endswith("drawn")},
            f"(AW, AR, sberror, read data, responder word) of the drawn in-window word leave at "
            f"the offset plus the 19 in-window bits on each table, {self.drawn}",
            evidence="CHK-RMAPA-OUTPUT",
        )
        for t in TABLES:
            self.edge_obs[f"{t} last word inside"] = obs[f"{t} last"]
            self.edge_want[f"{t} last word inside"] = want[f"{t} last"]

        await self._mark("S9", "output misses at the first word past each window")
        for t in TABLES:
            addr, leave = cell[t]["past"]
            o, w = self._out_cell(await self._sba_pair(addr, leave), leave)
            self.edge_obs[f"{t} first word past"], self.edge_want[f"{t} first word past"] = o, w
            self.misses += 1
        self._grade(
            sb,
            "CHK-RMAPA-EDGE",
            self.edge_obs,
            self.edge_want,
            f"alias end_addr non-inclusive and output window ends: one granule below end and "
            f"the last word inside hit, below start, end_addr and the first word past miss, "
            f"{self.drawn}",
            evidence="CHK-RMAPA-EDGE",
        )

        await self._mark("S10", "output valid cleared after programming; restore")
        graded, logged = {}, {}
        for t in TABLES:
            k, target = self.d[f"{t}_region"], self.d[f"{t}_target"]
            await self._bus_ok(cell[t]["csr"], SIZE_DOUBLEWORD, target)
            self.readback_obs[f"{t} region {k} ATTRS (valid cleared)"] = await self._read64(
                cell[t]["csr"]
            )
            self.readback_want[f"{t} region {k} ATTRS (valid cleared)"] = (0, target)
            addr, leave = cell[t]["cleared"]
            o, w = self._out_cell(await self._sba_pair(addr, leave), leave)
            (logged if k == OUT_CONTROL_REGION else graded)[f"{t} region {k}"] = (o, w)
            self.misses += 1
            await self._bus_ok(cell[t]["csr"], SIZE_DOUBLEWORD, 0)
        for key, (o, w) in logged.items():
            self._log(
                f"OBSERVATION {key} valid cleared: observed={o} unchanged-address outcome={w}; "
                "region 7 is the control cell of smu_sep_output_remap_region_matrix_test, "
                "logged and not graded here"
            )
        self._grade(
            sb,
            "CHK-RMAPA-OUTPUT",
            {k: o for k, (o, _) in graded.items()},
            {k: w for k, (_, w) in graded.items()},
            f"the drawn region cleared after programming passes the drawn word unchanged at an "
            f"index other than 7 ({len(graded)} graded, {len(logged)} logged), {self.drawn}",
            evidence="CHK-RMAPA-OUTPUT",
        )
        self._grade(
            sb,
            "CHK-RMAPA-READBACK",
            self.readback_obs,
            self.readback_want,
            f"every programmed region register reads back the drawn value, {self.drawn}",
            evidence="CHK-RMAPA-READBACK",
        )
        self.graded_cleared = len(graded)

    def _timeout_paths(self, sb) -> None:
        expired = [
            n for n, s in self.sites.items() if s["used"] is not None and s["used"] > s["bound"]
        ]
        for name, site in sorted(self.sites.items()):
            self._log(
                f"TIMEOUT-PATH {name}: bound={site['bound']} {site['unit']} "
                f"most used={site['used']} {site['unit']} count={site['count']} "
                f"{'EXPIRED' if name in expired else 'ok'} last={site['last']}"
            )
        finite = all(0 < s["bound"] < 10**9 for s in self.sites.values())
        has_last = all(s["last"] and s["used"] is not None for s in self.sites.values())
        self._log(
            f"CHK-TIMEOUT-PATHS: sites={len(self.sites)} expired={len(expired)} "
            f"labels={sorted(self.sites)}"
        )
        self._grade(
            sb,
            "CHK-TIMEOUT-PATHS",
            (expired, sorted(self.sites), finite, has_last),
            ([], sorted(EXPECTED_WAIT_LABELS), True, True),
            "no bounded wait expired, each label present, every bound finite with a use and a "
            "last state",
            evidence="CHK-TIMEOUT-PATHS",
        )

    async def run(self) -> None:
        sb = self.test.env.scoreboard
        self._log(
            f"SEED: RANDOM_SEED={self.seed} {self.drawn}; region redraws="
            f"{self.d['region_redraws']} salt redraws={self.d['salt_redraws']}"
        )
        await self._mark("S1", "SETUP: JTAG2AXI tap, apertures, reference access")
        try:
            await self._s1(sb)
            # smu_remap_cg samples the register writes and accesses of S2 to S10 only.
            self.dut.tb_fcov_gate.value = 1
            await self._alias(sb)
            await self._output(sb)
            await self._mark("S11", "TIMEOUT: bounded waits and last state")
            self._timeout_paths(sb)
        finally:
            self.dut.tb_fcov_gate.value = 0
            if self.tap is not None:
                self.tap.stop()
        await ClockCycles(self.clk, STEP_CLOCK_GAP)
        self.step_ts["PASS"] = get_sim_time("ns")
        order = [*STEPS, "PASS"]
        stamps = [self.step_ts[k] for k in order]
        j2a = sum(self.step_access[s] for s in J2A_STEPS)
        sba = sum(self.step_access[s] for s in SBA_STEPS)
        every = all(self.step_access[s] > 0 for s in (*J2A_STEPS, *SBA_STEPS))
        fence = " ".join(f"{k}={t:.0f}ns" for k, t in zip(order, stamps))
        self._log(f"OBSERVATION step fence {fence} (logged, not compared)")
        self._log(
            f"CHK-NONVAC: JTAG2AXI accesses {j2a} system-bus accesses "
            f"{sba} hits={self.hits} misses={self.misses} graded valid-cleared output cells="
            f"{self.graded_cleared}"
        )
        self._grade(
            sb,
            "CHK-NONVAC",
            (
                every,
                (j2a, sba, self.j2a_count, self.accesses),
                self.hits > 0 and self.misses > 0,
                self.graded_cleared > 0,
            ),
            (True, (J2A_EXPECTED, SBA_EXPECTED) * 2, True, True),
            f"access counts, at least one hit and one miss, {self.drawn}",
            evidence="CHK-NONVAC",
        )
        self.done = True
