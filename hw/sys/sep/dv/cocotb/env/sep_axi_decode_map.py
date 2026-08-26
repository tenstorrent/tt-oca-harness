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

The RTL decode table in ``hw/sys/sep/rtl/crossbars/sep_local_axi_xbar.sv``
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
_XBAR = _DV_ROOT.parent / "rtl" / "crossbars" / "sep_local_axi_xbar.sv"

# Reserved marker in the memory-map Unit column.
_RSV = "_RSV_"


@dataclass(frozen=True)
class SpecRegion:
    """One row of the memory-map table. ``end_addr`` is inclusive."""

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
# coarse rows deliberately span the fine ones. All are parsed and the most
# specific row wins, which is how a reader resolves them too.
_SPEC_HEADER = "|Base Address |End Address |Size |Unit |Description"

# A row is reserved when the Unit column says so, or when Unit is blank and the
# description does. Both spellings appear in the document.
_RSV_DESC = ("reserved",)


def _is_reserved(unit: str, desc: str) -> bool:
    if unit == _RSV:
        return True
    if unit == "":
        return desc.strip().lower().startswith(_RSV_DESC)
    return False


def spec_regions() -> tuple[SpecRegion, ...]:
    """Every allocation row, finest first. Raises if the tables vanish."""
    lines = _SPEC.read_text().splitlines()
    rows: list[SpecRegion] = []
    line_re = re.compile(
        r"^\|(0x[0-9A-Fa-f_]+)\s*\|(0x[0-9A-Fa-f_]+)\s*\|([^|]*)\|([^|]*)\|(.*)$"
    )
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
        rows.append(
            SpecRegion(
                _hexint(base), _hexint(end),
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
                f"memory-map row runs backwards: 0x{r.base:08x}-"
                f"0x{r.end_addr:08x} ({r.unit})"
            )
    # Finest first so region_of() resolves the hierarchy the way a reader does.
    return tuple(sorted(rows, key=lambda r: (r.end_addr - r.base, r.base)))


def rtl_ranges() -> tuple[RtlRange, ...]:
    """Parse the crossbar AddrMap. Cross-check input only, never an expectation."""
    text = _XBAR.read_text()
    rule_re = re.compile(
        r"'\{idx:\s*(\d+),\s*start_addr:\s*32'h([0-9A-Fa-f_]+),"
        r"\s*end_addr:\s*33'h([0-9A-Fa-f_]+)\}"
    )
    out = [
        RtlRange(int(i), _hexint(s), _hexint(e))
        for i, s, e in rule_re.findall(text)
    ]
    if not out:
        raise RuntimeError(
            f"no AddrMap rules parsed from {_XBAR}; the table format changed"
        )
    return tuple(out)


def region_of(addr: int, regions=None) -> SpecRegion | None:
    """The spec row covering ``addr``, or None when no row describes it."""
    for r in regions if regions is not None else spec_regions():
        if r.contains(addr):
            return r
    return None


def may_complete(addr: int, regions=None) -> bool:
    """True when the specification allocates something at ``addr``.

    False means the fabric must refuse -- DECERR or SLVERR, the map does not
    mandate which flavour. An address in no row at all is also False.
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
    assert any(
        r.start_addr == 0x1080_0000 and r.end_addr == 0x1080_1000 for r in rtl
    ), "dma_csr AddrMap rule not found"


_selftest()
