# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every local-master alias-remap region with full-width bounds and offsets.

RANDCFG. The CPU-LSU source beat is a staged CSR word in the inbound-filter
bank page (a pure-RW START_ADDR low word of the last inbound entry, which stays
disabled). For each of the N_REGIONS alias regions:

  * Hit. The region starts at the source page and its offset sends the beat to a
    seed-chosen 56-bit target T at or above EXTERNAL_TO_CHIPLET_BASE_ADDR, so
    the beat leaves on the SMU path through the block-by-default outbound
    filter. Only the outbound entry under test is enabled, holding the one
    granule at T: an OKAY shows the beat reached T exactly, and the next beat
    (next granule) answers DECERR. The region runs offset O, then ~O.
  * Miss. A region that starts above the source page (start S, then ~S) does
    not translate: the read answers OKAY with the staged value. A region that
    starts at the source page and ends there (END = source page, valid set,
    offset ~O) does not translate either, so the END compare decides a beat.
  * Valid clear. The hit bounds with valid=0 do not translate either.

So every alias START, END and offset bit takes a 0->1 and a 1->0 step, and
the alias adder's upper bits decide where the beat lands.

The rewrite is ``{offset[55:12] + addr[55:12], addr[11:0]}`` modulo 2^56
(``hw/ip/axi_alias_remap/regs/alias_remap.rdl``); the region matches when
start <= addr < end (end is non-inclusive).

no_cpu, +skip_fuse_sense.

Checkers:
  CHK-ALIAS-WALK-READBACK  alias START/END/ATTRS and the outbound entry read
                           back as programmed (56 bits).
  CHK-ALIAS-WALK-HIT       the translated beat answers OKAY in the one
                           granule at T, and DECERR one granule up.
  CHK-ALIAS-WALK-MISS      a region above the source page, or one whose END
                           is the source page, leaves the beat untranslated:
                           OKAY with the staged value.
  CHK-ALIAS-WALK-VALID     valid=0 leaves the beat untranslated: OKAY with the
                           staged value.
"""

from __future__ import annotations

import pyuvm
from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from sep_reg_meta import sym
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_ATTRS,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_END_RESET,
    ALIAS_START,
    ALIAS_STRIDE,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    OUTFILT_BASE,
)
from seq_lib.sep_fabric_entry_walk_seq import (
    ADDR_MASK,
    GRANULE_BYTES,
    SepFilterEntryWalker,
    exact_window,
)
from seq_lib.sep_fabric_local_alias_seq import (
    ADDEND_MASK,
    END_MASK,
    IDX_START,
    N_REGIONS,
    OFFSET_MASK,
    PAGE,
    START_MASK,
    VALID_HI,
    remapped_addr,
)
from seq_lib.sep_inbound_filter_rule_seq import INFILT_N_ENTRIES, RESP_DECERR, RESP_OKAY
from seq_lib.sep_outbound_remap_seq import OUTFILT_N_ENTRIES

# hw/sys/sep/doc/fabric.adoc (route demux): any address at or above
# 0x1_0000_0000 goes to the outbound mux, which feeds the outbound filter.
CHIPLET_BASE = 0x1_0000_0000
PG_MASK = ADDEND_MASK  # page-number field [55:12]
SRC_ADDR = INFILT_BASE + (INFILT_N_ENTRIES - 1) * FILTER_STRIDE + FILTER_START_ADDR
SRC_PAGE = SRC_ADDR & ~(PAGE - 1)
SRC_PG = SRC_PAGE >> IDX_START
if OUTFILT_N_ENTRIES < N_REGIONS:
    raise RuntimeError(f"{OUTFILT_N_ENTRIES} outbound entries < {N_REGIONS} alias regions")
if ((SRC_ADDR + GRANULE_BYTES) & ~(PAGE - 1)) != SRC_PAGE:
    raise RuntimeError("the neighbour beat leaves the source page")
if (OUTFILT_BASE & ~(PAGE - 1)) == SRC_PAGE:
    raise RuntimeError("the outbound filter bank shares the source page")
if max(ALIAS_BASE, OUTFILT_BASE) & ~(PAGE - 1) >= SRC_PAGE:
    raise RuntimeError("a programmed bank sits at or above the source page")
_ = sym("LOCAL_MASTER_ALIAS_REMAP_CTRL_0__REG_MAP_BASE_ADDR")


class SepAliasRegionDriver(SepAxiRegDriver):
    """CPU-LSU driver for one alias region: write all three registers and read back."""

    _DRIVER_TAG = "ALIASWALK"

    def __init__(self, test) -> None:
        super().__init__(test)
        self.readbacks = 0

    async def _w64(self, addr: int, val: int) -> None:
        await self._wr(addr, val & 0xFFFF_FFFF)
        await self._wr(addr + 4, (val >> 32) & 0xFFFF_FFFF)

    async def _r64(self, addr: int) -> int:
        lo = await self._rd(addr)
        hi = await self._rd(addr + 4)
        return (hi << 32) | lo

    async def program(self, region: int, start: int, end: int, offset: int, valid: bool) -> None:
        base = ALIAS_BASE + region * ALIAS_STRIDE
        attrs = (offset & OFFSET_MASK) | ((VALID_HI << 32) if valid else 0)
        want = {
            ALIAS_START: start & START_MASK,
            ALIAS_END: end & END_MASK,
            ALIAS_ATTRS: attrs,
        }
        # Disable first, so no half-written window translates a beat.
        await self._w64(base + ALIAS_ATTRS, 0)
        await self._w64(base + ALIAS_START, want[ALIAS_START])
        await self._w64(base + ALIAS_END, want[ALIAS_END])
        await self._w64(base + ALIAS_ATTRS, attrs)
        for off, val in want.items():
            got = await self._r64(base + off)
            assert got == val, (
                f"CHK-ALIAS-WALK-READBACK FAIL: alias r{region} +0x{off:x} read "
                f"0x{got:016x}, want 0x{val:016x}"
            )
            self.readbacks += 1


class _Plan:
    """Seed-derived values for one region (single source of truth)."""

    def __init__(self, rng: SepSeededRng, region: int) -> None:
        self.region = region
        self.entry = region
        while True:
            t_pg = rng.randrange(CHIPLET_BASE >> IDX_START, PG_MASK + 1)
            addend = (t_pg - SRC_PG) & PG_MASK
            t2_pg = (SRC_PG + (~addend & PG_MASK)) & PG_MASK
            if t2_pg >= (CHIPLET_BASE >> IDX_START):
                break
        self.o1 = addend << IDX_START
        self.o2 = (~addend & PG_MASK) << IDX_START
        self.t1 = remapped_addr(self.o1, SRC_ADDR)
        self.t2 = remapped_addr(self.o2, SRC_ADDR)
        # Hit bounds: start = src page < end, with END and ~END both above it.
        # Start cannot go lower: a live window also translates every CPU-LSU
        # beat to the pages below the source page, and the alias and outbound
        # filter banks this test programs sit there. The miss cells walk START.
        self.hit_start = SRC_PAGE
        self.hit_end = rng.randrange(SRC_PG + 1, PG_MASK - SRC_PG) << IDX_START
        # Miss bounds: start S and ~S both above the source page.
        lo = SRC_PG + 1
        self.miss_start = rng.randrange(lo, PG_MASK - lo + 1) << IDX_START
        self.rng = rng

    def summary(self) -> str:
        return (
            f"r{self.region}: O1=0x{self.o1:014x} T1=0x{self.t1:014x} "
            f"O2=0x{self.o2:014x} T2=0x{self.t2:014x} hit=0x{self.hit_start:014x}.."
            f"0x{self.hit_end:014x}/~end miss=0x{self.miss_start:014x}/~"
        )


@pyuvm.test()
class sep_fabric_local_alias_offset_walk_test(sep_base_test):
    """All alias regions: full-width bounds and offsets, graded on live beats."""

    required_evidence = (
        "CHK-ALIAS-WALK-READBACK",
        "CHK-ALIAS-WALK-HIT",
        "CHK-ALIAS-WALK-MISS",
        "CHK-ALIAS-WALK-VALID",
    )

    async def _read(self, addr: int, *, deny: bool) -> tuple[int, int]:
        if deny:
            self.env.axi_monitor.arm_expected_decerr(1)
        seq = SepAxiAccessSeq(
            "aliaswalk_rd", op=SepAxiOp.READ, addr=addr, length=4, size=2, expect_error=deny
        )
        await self.start_seq(seq)
        return seq.resp_code, seq.rdata & 0xFFFF_FFFF

    async def _hit(self, p: _Plan, target: int, win) -> None:
        resp, _ = await self._read(SRC_ADDR, deny=False)
        assert resp == RESP_OKAY, (
            f"CHK-ALIAS-WALK-HIT FAIL: r{p.region} read 0x{SRC_ADDR:08x} -> target "
            f"0x{target:014x}, window 0x{win[0]:014x}..0x{win[1]:014x} resp={resp}, want OKAY"
        )
        resp, _ = await self._read(SRC_ADDR + GRANULE_BYTES, deny=True)
        assert resp == RESP_DECERR, (
            f"CHK-ALIAS-WALK-HIT FAIL: r{p.region} neighbour 0x{SRC_ADDR + GRANULE_BYTES:08x} "
            f"-> 0x{target + GRANULE_BYTES:014x} resp={resp}, want DECERR"
        )

    async def _untranslated(self, chk: str, p: _Plan, staged: int) -> None:
        resp, data = await self._read(SRC_ADDR, deny=False)
        assert resp == RESP_OKAY and data == staged, (
            f"{chk} FAIL: r{p.region} read 0x{SRC_ADDR:08x} resp={resp} data=0x{data:08x}, "
            f"want OKAY and the staged 0x{staged:08x} (untranslated)"
        )

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        # START_ADDR low word: >= 8 so it never shares the reset END granule.
        staged = (rng.getrandbits(32) | 0x8) & 0xFFFF_FFF8
        plans = [_Plan(rng, r) for r in range(N_REGIONS)]
        self.logger.info(
            "alias walk: %d regions, src=0x%08x staged=0x%08x", len(plans), SRC_ADDR, staged
        )
        await self.bring_up_no_cpu()
        alias = SepAliasRegionDriver(self)
        outf = SepFilterEntryWalker(
            self, bank_base=OUTFILT_BASE, bank="OUTFILT", n_entries=OUTFILT_N_ENTRIES
        )
        await alias._wr(SRC_ADDR, staged)
        got = await alias._rd(SRC_ADDR)
        assert got == staged, f"staged 0x{SRC_ADDR:08x}=0x{got:08x} != 0x{staged:08x}"
        counts = dict.fromkeys(("HIT", "MISS", "END_MISS", "VALID"), 0)

        for p in plans:
            r, e = p.region, p.entry
            for target, offset, end in (
                (p.t1, p.o1, p.hit_end),
                (p.t2, p.o2, ~p.hit_end & ADDR_MASK),
            ):
                win = exact_window(target)
                await outf.program_window(e, *win)
                await outf.check_window(e, "alias-exact")
                await outf.set_enabled(e, True)
                await alias.program(r, p.hit_start, end, offset, True)
                await self._hit(p, target, win)
                counts["HIT"] += 1

            await alias.program(r, p.hit_start, ~p.hit_end & ADDR_MASK, p.o2, False)
            await self._untranslated("CHK-ALIAS-WALK-VALID", p, staged)
            counts["VALID"] += 1

            # END miss: START matches and valid is set, but the source address is
            # at END (non-inclusive), so only the END compare keeps the beat
            # local. A translated beat lands at T2, which the outbound entry still
            # admits, and returns the responder's data, not the staged word.
            await alias.program(r, p.hit_start, SRC_PAGE, p.o2, True)
            await self._untranslated("CHK-ALIAS-WALK-MISS", p, staged)
            counts["END_MISS"] += 1

            for s in (p.miss_start, ~p.miss_start & START_MASK):
                assert (s >> IDX_START) > SRC_PG
                end = p.rng.randrange(s >> IDX_START, PG_MASK + 1) << IDX_START
                await alias.program(r, s, end, p.o2, True)
                await self._untranslated("CHK-ALIAS-WALK-MISS", p, staged)
                counts["MISS"] += 1

            await alias.program(r, 0, ALIAS_END_RESET, 0, False)
            await outf.restore(e)
            self.logger.info("alias %s", p.summary())

        n = len(plans)
        self.logger.info(
            "CHK-ALIAS-WALK-READBACK PASS: %d alias register readbacks over %d regions and "
            "%d outbound-filter readbacks match",
            alias.readbacks,
            n,
            outf.readbacks,
        )
        self.logger.info(
            "CHK-ALIAS-WALK-HIT PASS: %d translated beats landed in the one granule at T "
            "(OKAY) and missed it one granule up (DECERR)",
            counts["HIT"],
        )
        self.logger.info(
            "CHK-ALIAS-WALK-MISS PASS: %d regions above the source page and %d regions "
            "ending at the source page (END=0x%014x) left the beat untranslated "
            "(staged 0x%08x)",
            counts["MISS"],
            counts["END_MISS"],
            SRC_PAGE,
            staged,
        )
        self.logger.info(
            "CHK-ALIAS-WALK-VALID PASS: %d regions with valid clear left the beat untranslated",
            counts["VALID"],
        )
