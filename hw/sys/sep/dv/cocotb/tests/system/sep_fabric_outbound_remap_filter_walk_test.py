# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Every AP/STEE output-remap region and every outbound-filter entry, full width.

RANDCFG. Each of the 2 x N_REGIONS remap regions is paired with its own
outbound-filter entry (AP region r -> entry r, STEE region r -> entry
N_REGIONS + r). For each pair the test runs two phases with offsets O and ~O,
so the remapped target X sits below 2^55 in phase 1 and at or above 2^55 in
phase 2, and every offset, START_ADDR and END_ADDR bit takes both a 0->1 and a
1->0 step. Every outbound beat is a CPU-LSU read of the region's local window
(the outbound responder ``tb/sep_outbound_mbx.sv`` answers OKAY at any
address).

The outbound filter blocks by default, and only the entry under test is
enabled. So the response of each read shows where the remapped beat landed:
an OKAY means the beat's 56-bit address is inside the programmed window, and
a DECERR means it is outside. Remap and filter grade each other; a wrong upper
offset bit, or a wrong upper compare bit, changes the response.

no_cpu, +skip_fuse_sense: remap and the outbound filter do not depend on
sense; the outbound filter skip is tied off in RTL.

Checkers:
  CHK-WALK-READBACK  each programmed START/END (56 bits), FILTER_CONFIG and
                     remap ATTRS (offset[55:0] + valid) reads back as the
                     readback model says.
  CHK-WALK-ALLOW     a random 56-bit window that holds X answers OKAY.
  CHK-WALK-EXACT     the one granule that holds X answers OKAY, and the
                     neighbour beat (next granule, same region) answers DECERR.
  CHK-WALK-ABOVE     START = ~start of the ALLOW window (> X) answers DECERR.
  CHK-WALK-BELOW     END = ~end of the ALLOW window (< X) answers DECERR.
  CHK-WALK-BIT       for every address bit k above the granule and for each
                     bound, a window where that bound's bit k alone decides
                     the response for a phase-2 beat of the region (the beat
                     is chosen per bit among the region's beats): a compare
                     that ignores bit k of either bound flips the answer.
                     Every such window is read back (CHK-WALK-READBACK).
  CHK-WALK-PASSTHRU  with valid cleared, the exact granule at the beat's own
                     (untranslated) address answers OKAY, and the granule at
                     the translated address answers DECERR: the beat passes
                     through with its address unchanged.
"""

from __future__ import annotations

import pyuvm
from env.sep_seeded_rng import SepSeededRng
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_csr_bank_seq import AP_BASE, OUTFILT_BASE, STEE_BASE
from seq_lib.sep_fabric_entry_walk_seq import (
    ADDR_MASK,
    ADDR_W,
    GRANULE_BYTES,
    SepFilterEntryWalker,
    SepRemapRegionDriver,
    bit_legs,
    containing_window,
    exact_window,
    granule,
)
from seq_lib.sep_outbound_remap_seq import (
    AP_REGION_BASE,
    IDX_START,
    N_REGIONS,
    OUTFILT_N_ENTRIES,
    RESP_DECERR,
    RESP_OKAY,
    STEE_REGION_BASE,
    remap_access_addr,
    remap_probe_seq,
    remapped_addr,
)

_REGION_SPAN = 1 << IDX_START
TOP_BIT = 1 << (ADDR_W - 1)
if OUTFILT_N_ENTRIES < 2 * N_REGIONS:
    raise RuntimeError(
        f"{OUTFILT_N_ENTRIES} outbound entries cannot pair with 2 x {N_REGIONS} remap regions"
    )


class _Pair:
    """One region/entry pair and its seed-derived values (single source of truth)."""

    def __init__(self, rng: SepSeededRng, bank: str, region: int) -> None:
        self.bank = bank
        self.region = region
        self.csr_base = AP_BASE if bank == "AP" else STEE_BASE
        self.entry = region if bank == "AP" else N_REGIONS + region
        region_base = AP_REGION_BASE if bank == "AP" else STEE_REGION_BASE
        # 8-byte aligned, not the last granule, so the neighbour stays in-region.
        self.intra = rng.randrange(0, _REGION_SPAN - GRANULE_BYTES, GRANULE_BYTES)
        self.access = remap_access_addr(region_base, region, self.intra)
        self.neighbour = remap_access_addr(region_base, region, self.intra + GRANULE_BYTES)
        self.o1 = rng.getrandbits(ADDR_W) & ~TOP_BIT & ADDR_MASK
        self.o2 = ~self.o1 & ADDR_MASK
        self.region_base = region_base
        # Beats of the same region whose intra offset differs in one bit, so
        # bit_legs can pick, per address bit, a beat where that bit decides.
        self.probe_intras = [self.intra] + [
            self.intra ^ (1 << b)
            for b in range(GRANULE_BYTES.bit_length() - 1, IDX_START)
            if (self.intra ^ (1 << b)) < _REGION_SPAN
        ]
        self.rng = rng

    def target(self, offset: int) -> int:
        return remapped_addr(offset, self.intra)

    def probes(self, offset: int) -> list[tuple[int, int]]:
        """(local access address, remapped target) for every probe beat."""
        return [
            (remap_access_addr(self.region_base, self.region, i), remapped_addr(offset, i))
            for i in self.probe_intras
        ]

    def tag(self) -> str:
        return f"{self.bank} r{self.region}/entry {self.entry}"


@pyuvm.test()
class sep_fabric_outbound_remap_filter_walk_test(sep_base_test):
    """All remap regions x their outbound entries, offsets and bounds at full width."""

    async def _read(self, addr: int, *, deny: bool) -> int:
        if deny:
            self.env.axi_monitor.arm_expected_decerr(1)
        seq = remap_probe_seq(addr, expect_error=deny)
        await self.start_seq(seq)
        return seq.resp_code

    async def _expect(self, chk: str, pair: _Pair, addr: int, x: int, win, *, deny: bool) -> None:
        resp = await self._read(addr, deny=deny)
        want = RESP_DECERR if deny else RESP_OKAY
        assert resp == want, (
            f"{chk} FAIL: {pair.tag()} read 0x{addr:08x} (target 0x{x:014x}) with window "
            f"0x{win[0]:014x}..0x{win[1]:014x} resp={resp}, want {want}"
        )

    async def run_scenario(self) -> None:
        rng = SepSeededRng(self.random_seed())
        pairs = [_Pair(rng, b, r) for b in ("AP", "STEE") for r in range(N_REGIONS)]
        self.logger.info(
            "outbound walk: %d pairs, IdxStart=%d, granule=%d", len(pairs), IDX_START, GRANULE_BYTES
        )
        await self.bring_up_no_cpu()
        filt = SepFilterEntryWalker(
            self, bank_base=OUTFILT_BASE, bank="OUTFILT", n_entries=OUTFILT_N_ENTRIES
        )
        remap = SepRemapRegionDriver(self)
        counts = dict.fromkeys(("ALLOW", "EXACT", "ABOVE", "BELOW", "BIT", "PASSTHRU"), 0)

        for p in pairs:
            e = p.entry
            # Phase 1: offset O1 (bit 55 clear), so X1 < 2^55.
            x1 = p.target(p.o1)
            assert x1 < TOP_BIT, f"{p.tag()} X1 0x{x1:014x} is not below the top address bit"
            await remap.program(p.csr_base, p.region, p.o1, True)
            allow = containing_window(p.rng, x1)
            await filt.program_window(e, *allow)
            win = await filt.check_window(e, "allow-1")
            await filt.set_enabled(e, True)
            await self._expect("CHK-WALK-ALLOW", p, p.access, x1, win, deny=False)

            ex = exact_window(x1)
            await filt.program_window(e, *ex)
            win = await filt.check_window(e, "exact-1")
            await self._expect("CHK-WALK-EXACT", p, p.access, x1, win, deny=False)
            nx = p.target(p.o1) + GRANULE_BYTES
            assert granule(nx) != granule(x1)
            await self._expect("CHK-WALK-EXACT", p, p.neighbour, nx, win, deny=True)

            above_start = ~allow[0] & ADDR_MASK
            above = (above_start, p.rng.randrange(above_start, ADDR_MASK + 1))
            assert granule(above[0]) > granule(x1)
            await filt.program_window(e, *above)
            win = await filt.check_window(e, "above-1")
            await self._expect("CHK-WALK-ABOVE", p, p.access, x1, win, deny=True)

            # Phase 2: offset O2 = ~O1 (bit 55 set), so X2 >= 2^55.
            x2 = p.target(p.o2)
            assert x2 >= TOP_BIT, f"{p.tag()} X2 0x{x2:014x} is not at or above the top address bit"
            await remap.program(p.csr_base, p.region, p.o2, True)
            allow2 = containing_window(p.rng, x2)
            await filt.program_window(e, *allow2)
            win = await filt.check_window(e, "allow-2")
            await self._expect("CHK-WALK-ALLOW", p, p.access, x2, win, deny=False)

            below_end = ~allow2[1] & ADDR_MASK
            below = (p.rng.randrange(0, below_end + 1), below_end)
            assert granule(below[1]) < granule(x2)
            await filt.program_window(e, *below)
            win = await filt.check_window(e, "below-2")
            await self._expect("CHK-WALK-BELOW", p, p.access, x2, win, deny=True)

            ex2 = exact_window(x2)
            await filt.program_window(e, *ex2)
            win = await filt.check_window(e, "exact-2")
            await self._expect("CHK-WALK-EXACT", p, p.access, x2, win, deny=False)

            probes = p.probes(p.o2)
            for k, field, bwin, bit_allow, i in bit_legs([x for _, x in probes]):
                acc, x = probes[i]
                await filt.program_window(e, *bwin)
                bwin = await filt.check_window(e, f"bit{k}-{field}")
                await self._expect(
                    f"CHK-WALK-BIT k={k} {field}", p, acc, x, bwin, deny=not bit_allow
                )
                counts["BIT"] += 1

            # valid=0: the beat keeps its local address. The granule at X2
            # misses it; the granule at its own address admits it.
            await remap.program(p.csr_base, p.region, p.o2, False)
            assert granule(p.access) != granule(x2)
            await filt.program_window(e, *ex2)
            win = await filt.check_window(e, "passthru-x2")
            await self._expect("CHK-WALK-PASSTHRU", p, p.access, p.access, win, deny=True)
            own = exact_window(p.access)
            await filt.program_window(e, *own)
            win = await filt.check_window(e, "passthru-own")
            await self._expect("CHK-WALK-PASSTHRU", p, p.access, p.access, win, deny=False)

            await filt.restore(e)
            await remap.program(p.csr_base, p.region, 0, False)
            counts["ALLOW"] += 2
            counts["EXACT"] += 3
            counts["ABOVE"] += 1
            counts["BELOW"] += 1
            counts["PASSTHRU"] += 2
            self.logger.info(
                "pair %s: O1=0x%014x X1=0x%014x O2=0x%014x X2=0x%014x "
                "allow1=0x%014x..0x%014x above=0x%014x.. below=..0x%014x",
                p.tag(),
                p.o1,
                x1,
                p.o2,
                x2,
                allow[0],
                allow[1],
                above[0],
                below[1],
            )

        n = len(pairs)
        self.logger.info(
            "CHK-WALK-READBACK PASS: %d filter readbacks over %d entries and %d remap ATTRS "
            "readbacks over %d regions match the 56-bit model",
            filt.readbacks,
            n,
            remap.readbacks,
            n,
        )
        self.logger.info(
            "CHK-WALK-ALLOW PASS: %d wide windows holding X answered OKAY", counts["ALLOW"]
        )
        self.logger.info(
            "CHK-WALK-EXACT PASS: %d exact-granule reads (OKAY at X, DECERR at the neighbour)",
            counts["EXACT"],
        )
        self.logger.info(
            "CHK-WALK-ABOVE PASS: %d windows with START above X answered DECERR",
            counts["ABOVE"],
        )
        self.logger.info(
            "CHK-WALK-BELOW PASS: %d windows with END below X answered DECERR", counts["BELOW"]
        )
        self.logger.info(
            "CHK-WALK-BIT PASS: %d single-bit windows (bits %d..%d of START and END on every "
            "entry) decided the response",
            counts["BIT"],
            GRANULE_BYTES.bit_length() - 1,
            ADDR_W - 1,
        )
        self.logger.info(
            "CHK-WALK-PASSTHRU PASS: %d reads with valid clear (OKAY at the untranslated "
            "address, DECERR at the translated one)",
            counts["PASSTHRU"],
        )
