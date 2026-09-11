# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP address-map classification for AXI response expectations.

Answers one question for an arbitrary address: may a transaction there
legally complete, or must the fabric refuse it?

The expected answer comes from the SPECIFICATION table in
``hw/sys/sep/doc/memory_map.adoc``, never from the RTL decoder. A checker
that asked the decoder what the decoder should do would pass on any
decoder. Rows whose Unit column is ``_RSV_`` are reserved: nothing is
allocated there, so an access must not return OKAY.

The RTL decode table in ``hw/sys/sep/rtl/sep_local_axi_xbar.sv``
is parsed too, but only as a cross-check. ``audit_rtl_vs_spec()`` reports
every span the crossbar routes that the specification calls reserved.
Those are real findings -- an address the fabric accepts and the map does
not describe -- and they are returned for the caller to log, not silently
folded into the expectation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_DV_ROOT = Path(__file__).resolve().parents[2]
_SPEC = _DV_ROOT.parent / "doc" / "memory_map.adoc"
_XBAR = _DV_ROOT.parent / "rtl" / "sep_local_axi_xbar.sv"
_ADDRMAP_PKG = _DV_ROOT.parent / "regs" / "gen" / "sv" / "sep_addrmap_pkg.sv"

# A row at least this wide is a container the detailed rows carve up, not an
# allocation in its own right.
_COARSE_SPAN = 0x0100_0000

# Reserved marker in the memory-map Unit column.
_RSV = "_RSV_"


@dataclass(frozen=True)
class SpecRegion:
    """One row of a memory-map table.

    ``end_addr`` is INCLUSIVE. The coarse region table writes an exclusive end
    (0x0000_0000-0x1000_0000 for a 256 MB region) while the detailed tables
    write an inclusive one (0x1000_0000-0x1000_FFFF for 64 kB).
    ``spec_regions`` normalises the coarse rows on the way in, so everything
    downstream sees one convention: an inclusive ``end_addr``.
    """

    base: int
    end_addr: int
    unit: str
    desc: str

    @property
    def reserved(self) -> bool:
        return self.unit == _RSV

    def contains(self, addr: int) -> bool:
        return self.base <= addr <= self.end_addr


@dataclass(frozen=True)
class RtlRange:
    """One AddrMap rule. ``end_addr`` is exclusive, as written in the RTL."""

    idx: int
    start_addr: int
    end_addr: int

    def contains(self, addr: int) -> bool:
        return self.start_addr <= addr < self.end_addr


def _hexint(text: str) -> int:
    return int(text.replace("_", ""), 16)


# The document holds three tables under this header: a coarse region summary,
# the CPU TCM detail, and the SEP-local detail. They are hierarchical, so the
# coarse rows span the fine ones. All are parsed and the most
# specific row wins, which is how a reader resolves them too.
_SPEC_HEADER = "|Base Address |End Address |Size |Unit |Description"

# A row is reserved when the Unit column says so, or when Unit is blank and the
# description does. Both spellings appear in the document.
_RSV_DESC = ("reserved",)


def _is_reserved(unit: str, desc: str) -> bool:
    """True when the row allocates nothing.

    Three spellings appear in the document: Unit ``_RSV_``; a blank Unit with
    a Description that starts "Reserved"; and a named Unit whose Description
    says it is reserved (the 512 MB "SEP External Region ... Reserved for
    adopter extension IP"). All three forms classify as reserved, or the
    region is probed as allocated and never counted as a skip.
    """
    if unit == _RSV:
        return True
    return desc.strip().lower().startswith(_RSV_DESC)


def spec_regions() -> tuple[SpecRegion, ...]:
    """Every allocation row, finest first. Raises if the tables vanish."""
    # utf-8 explicitly: these sources carry box-drawing characters, and the
    # simulator runs cocotb under an ASCII default locale.
    lines = _SPEC.read_text(encoding="utf-8").splitlines()
    rows: list[SpecRegion] = []
    line_re = re.compile(r"^\|(0x[0-9A-Fa-f_]+)\s*\|(0x[0-9A-Fa-f_]+)\s*\|([^|]*)\|([^|]*)\|(.*)$")
    in_table = False
    for raw in lines:
        stripped = raw.strip()
        if stripped == _SPEC_HEADER:
            in_table = True
            continue
        if in_table and stripped.startswith("|===="):
            in_table = False
            continue
        if not in_table:
            continue
        m = line_re.match(stripped)
        if not m:
            continue
        base, end, _size, unit, desc = m.groups()
        unit, desc = unit.strip(), desc.strip()
        lo, hi = _hexint(base), _hexint(end)
        # Normalise the coarse table's exclusive end. A row whose base and end
        # are both 4 kB aligned is exclusive; a detailed row ends on an
        # all-ones boundary, which is inclusive and never 4 kB aligned.
        if hi > lo and (hi & 0xFFF) == 0 and (lo & 0xFFF) == 0:
            hi -= 1
        rows.append(
            SpecRegion(
                lo,
                hi,
                _RSV if _is_reserved(unit, desc) else unit,
                desc,
            )
        )
    if not rows:
        raise RuntimeError(
            f"no allocation rows parsed from {_SPEC} under the header "
            f"{_SPEC_HEADER!r}. Every response expectation is built from those "
            "tables, so refusing to guess which format replaced them."
        )
    for r in rows:
        if r.end_addr < r.base:
            raise RuntimeError(
                f"memory-map row runs backwards: 0x{r.base:08x}-0x{r.end_addr:08x} ({r.unit})"
            )
    rows.extend(_hole_regions(rows))
    # Finest first so region_of() resolves the hierarchy the way a reader does.
    return tuple(sorted(rows, key=lambda r: (r.end_addr - r.base, r.base)))


def _hole_regions(rows: list[SpecRegion]) -> list[SpecRegion]:
    """Reserved rows for the spans no detailed row describes.

    A coarse row names a region and the detailed rows carve it up. Where the
    detailed rows leave a gap, nothing is allocated there -- but the gap is
    inside the coarse row, so ``region_of`` would otherwise resolve it to the
    coarse parent and report it allocated. An address described by no detailed
    row allocates nothing and must read as reserved, the same as an explicit
    ``_RSV_`` row.
    """
    coarse = [r for r in rows if (r.end_addr - r.base) >= _COARSE_SPAN]
    holes: list[SpecRegion] = []
    for parent in coarse:
        inner = sorted(
            (
                r
                for r in rows
                if r is not parent
                and r.base >= parent.base
                and r.end_addr <= parent.end_addr
                and (r.end_addr - r.base) < _COARSE_SPAN
            ),
            key=lambda r: r.base,
        )
        if not inner:
            continue
        cursor = parent.base
        for r in inner:
            if r.base > cursor:
                holes.append(
                    SpecRegion(
                        cursor,
                        r.base - 1,
                        _RSV,
                        f"described by no detailed row inside {parent.unit}",
                    )
                )
            cursor = max(cursor, r.end_addr + 1)
        if cursor <= parent.end_addr:
            holes.append(
                SpecRegion(
                    cursor,
                    parent.end_addr,
                    _RSV,
                    f"described by no detailed row inside {parent.unit}",
                )
            )
    return holes


def _addrmap_symbols() -> dict[str, int]:
    """The generated address-map localparams, by bare name.

    The crossbar states some rules as `PKG::SYM` arithmetic rather than a hex
    literal, so the rule text alone does not carry the bound.
    """
    text = _ADDRMAP_PKG.read_text(encoding="utf-8")
    sym_re = re.compile(r"localparam\s+longint\s+unsigned\s+(\w+)\s*=\s*64'h([0-9A-Fa-f_]+)\s*;")
    return {n: _hexint(v) for n, v in sym_re.findall(text)}


def _resolve_bound(expr: str, syms: dict[str, int]) -> int:
    """One AddrMap bound: a hex literal, or a sum of address-map symbols.

    Only `+` is supported. Anything else raises rather than
    resolving to a plausible wrong number -- a bound this cross-check cannot
    read must stop the parse, not silently drop the rule.
    """
    expr = re.sub(r"\b\d+'\s*", "", expr)  # width casts
    expr = expr.replace("och_sep_top_addrmap_pkg::", "")
    expr = expr.replace("(", " ").replace(")", " ").strip()
    total = 0
    for term in expr.split("+"):
        term = term.strip()
        if not term:
            continue
        if re.fullmatch(r"h?[0-9A-Fa-f_]+", term) and not term.isalpha():
            try:
                total += _hexint(term.lstrip("h"))
                continue
            except ValueError:
                pass
        if term not in syms:
            raise RuntimeError(
                f"AddrMap bound `{term}` is neither a hex literal nor a symbol "
                f"in {_ADDRMAP_PKG.name}"
            )
        total += syms[term]
    return total


def rtl_ranges() -> tuple[RtlRange, ...]:
    """Parse the crossbar AddrMap. Cross-check input only, never an expectation."""
    text = _XBAR.read_text(encoding="utf-8")
    syms = _addrmap_symbols()
    # Bounds are matched loosely and resolved after: a rule stated in package
    # symbols (see dma_csr / sep_wdt) must not fall out of the sweep just
    # because it carries no hex literal.
    rule_re = re.compile(
        r"'\{\s*idx:\s*(\d+),\s*start_addr:\s*(.+?),"
        r"\s*end_addr:\s*(.+?)\}",
        re.DOTALL,
    )
    out = [
        RtlRange(int(i), _resolve_bound(s, syms), _resolve_bound(e, syms))
        for i, s, e in rule_re.findall(text)
    ]
    if not out:
        raise RuntimeError(f"no AddrMap rules parsed from {_XBAR}; the table format changed")
    return tuple(out)


def region_of(addr: int, regions=None) -> SpecRegion | None:
    """The spec row covering ``addr``, or None when no row describes it."""
    for r in regions if regions is not None else spec_regions():
        if r.contains(addr):
            return r
    return None


def may_complete(addr: int, regions=None) -> bool:
    """True when the specification allocates something at ``addr``.

    False means the fabric must refuse. ``memory_map.adoc`` mandates DECERR for
    the remainder inside a unit's aperture and is silent on the flavour for the
    reserved rows between apertures, so this says only that the access must not
    complete. An address described by no detailed row is also False: the gap
    inside a coarse container allocates nothing.
    """
    r = region_of(addr, regions)
    return r is not None and not r.reserved


def audit_rtl_vs_spec() -> tuple[str, ...]:
    """Spans the crossbar routes that the specification calls reserved.

    Returned for the caller to log as findings. Not used to build any
    expectation: folding them in would let the RTL define its own contract.
    """
    regions = spec_regions()
    findings: list[str] = []
    for rng in rtl_ranges():
        for reg in regions:
            if not reg.reserved:
                continue
            lo = max(rng.start_addr, reg.base)
            hi = min(rng.end_addr - 1, reg.end_addr)
            if lo <= hi:
                findings.append(
                    f"xbar idx {rng.idx} routes 0x{lo:08x}-0x{hi:08x}, which "
                    f"memory_map.adoc lists as reserved ({reg.desc or _RSV})"
                )
    return tuple(findings)


def _selftest() -> None:
    """Pin the parse against values a human can check in the two sources."""
    regions = spec_regions()
    assert len(regions) >= 25, f"only {len(regions)} memory-map rows parsed"

    # Allocated: DMA CSR base, and the last byte of the WDT window.
    assert may_complete(0x1080_0000, regions), "DMA CSR base read as unallocated"
    assert may_complete(0x1080_1FFF, regions), "WDT window top read as unallocated"
    # Reserved: the gap above the reset controller, and above the KM window.
    assert not may_complete(0x1080_3008, regions), "reset-ctrl gap read as allocated"
    assert not may_complete(0x1092_1000, regions), "KM reserved gap read as allocated"

    dma = region_of(0x1080_0000, regions)
    assert dma is not None and dma.unit == "DMA", f"0x10800000 -> {dma}"
    assert dma.base == 0x1080_0000 and dma.end_addr == 0x1080_0FFF, f"{dma}"

    # The RTL table must still be parseable; ranges are exclusive-end there.
    rtl = rtl_ranges()
    assert len(rtl) >= 14, f"only {len(rtl)} AddrMap rules parsed"
    # The dma_csr rule spans the secure_dma register extent, NOT the 4 kB spec
    # aperture: secure_dma_reg_top decodes 9 bits, so a wider window aliases.
    assert any(r.start_addr == 0x1080_0000 and r.end_addr == 0x1080_0150 for r in rtl), (
        "dma_csr AddrMap rule not found"
    )


_selftest()
