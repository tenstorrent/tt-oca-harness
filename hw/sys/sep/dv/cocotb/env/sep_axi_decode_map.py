# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP address-map classification for AXI response expectations.

``may_complete(addr)`` is true only when ``_MAP_ROWS`` (plus derived holes)
allocates that address. A reserved row, and a gap inside a coarse window
with no detailed row, must not return OKAY. The refusal flavour is unnamed.
"""

from __future__ import annotations

from dataclasses import dataclass

from sep_reg_meta import indexed_block_count, sep_reg, sym

# A row at least this wide is a container the detailed rows carve up, not an
# allocation in its own right.
_COARSE_SPAN = 0x0100_0000

_RSV = "_RSV_"


@dataclass(frozen=True)
class SpecRegion:
    """One DV-owned memory-map row. ``end_addr`` is inclusive."""

    base: int
    end_addr: int
    unit: str
    desc: str

    @property
    def reserved(self) -> bool:
        return self.unit == _RSV

    def contains(self, addr: int) -> bool:
        return self.base <= addr <= self.end_addr


def _block_span(stem: str) -> tuple[int, int]:
    """(base, end_inclusive) of one generated register block or register array.

    ``stem`` names a ``<stem>_REG_MAP_BASE_ADDR`` / ``_SIZE`` pair in the
    generated SystemRDL export (``hw/sys/sep/regs/gen/py/sep_reg.py``), or an
    RDL array ``<stem>_0_`` ... ``<stem>_<n-1>_``. An array spans all ``n``
    elements at the array stride, so the padding after each element belongs to
    the array.
    """
    if hasattr(sep_reg, f"{stem}_REG_MAP_BASE_ADDR"):
        base = sym(f"{stem}_REG_MAP_BASE_ADDR")
        return base, base + sym(f"{stem}_REG_MAP_SIZE") - 1
    count = indexed_block_count(stem)
    base = sym(f"{stem}_0__REG_MAP_BASE_ADDR")
    if count == 1:
        return base, base + sym(f"{stem}_0__REG_MAP_SIZE") - 1
    stride = sym(f"{stem}_1__REG_MAP_BASE_ADDR") - base
    for k in range(count):
        if sym(f"{stem}_{k}__REG_MAP_BASE_ADDR") != base + k * stride:
            raise RuntimeError(f"{stem}: array element {k} is not at the array stride")
    return base, base + count * stride - 1


def _rdl_window_rows(
    base: int, end_addr: int, blocks: tuple[tuple[str, str, str], ...]
) -> tuple[tuple[int, int, str, str], ...]:
    """Rows for one memory-map window whose units are generated RDL blocks.

    Each block row spans that block's decoded extent in the register export.
    Every span inside [``base``, ``end_addr``] that no block owns is a reserved
    row: no RDL block claims it, so an access there must be refused.
    """
    spans = sorted((*_block_span(stem), unit, desc) for stem, unit, desc in blocks)
    rows: list[tuple[int, int, str, str]] = []
    cursor = base
    for lo, hi, unit, desc in spans:
        if lo < cursor or hi > end_addr:
            raise RuntimeError(
                f"{unit} 0x{lo:08x}-0x{hi:08x} overlaps a neighbour or leaves "
                f"window 0x{base:08x}-0x{end_addr:08x}"
            )
        if lo > cursor:
            rows.append((cursor, lo - 1, _RSV, "Reserved (no RDL block)"))
        rows.append((lo, hi, unit, desc))
        cursor = hi + 1
    if cursor <= end_addr:
        rows.append((cursor, end_addr, _RSV, "Reserved (no RDL block)"))
    return tuple(rows)


# Dual scratch register banks (0x1080_2000-0x1080_2FFF), OTP (0x1093_0000-0x1093_FFFF)
# and System Bus I/F (0x10A0_0000-0x10A3_FFFF): each window holds several RDL
# blocks with reserved space between them, so its rows come from the export.
_SRB_ROWS = _rdl_window_rows(
    0x1080_2000,
    0x1080_2FFF,
    (
        ("SEP_SCRATCH_COLD", "SRB cold", "Cold-reset scratch register bank"),
        ("SEP_SCRATCH_WARM", "SRB warm", "Warm-reset scratch register bank"),
    ),
)
_OTP_ROWS = _rdl_window_rows(
    0x1093_0000,
    0x1093_FFFF,
    (
        ("SEP_EFUSE_MAP", "OTP shadow", "eFuse shadow map"),
        ("EFUSE_INTERFACE_CTRL", "OTP interface", "eFuse command and status registers"),
        ("EFUSE_MMR", "OTP MMR", "eFuse security-token registers"),
    ),
)
_SYS_ROWS = _rdl_window_rows(
    0x10A0_0000,
    0x10A3_FFFF,
    (
        ("AXIL_MAILBOX", "SYS mailbox", "Mailbox pairs"),
        ("LOCAL_MASTER_ALIAS_REMAP_CTRL", "SYS alias remap", "Local master alias remap"),
        ("AP_OUTPUT_REMAP_CTRL", "SYS AP remap", "AP output remap"),
        ("STEE_OUTPUT_REMAP_CTRL", "SYS STEE remap", "STEE output remap"),
        ("OUTBOUND_FILTER_CTRL", "SYS outbound filter", "Outbound filter control"),
        ("INBOUND_FILTER_CTRL", "SYS inbound filter", "Inbound filter control"),
        ("SEP_CPU_CTRL", "SYS CPU control", "SEP CPU control and interrupt registers"),
    ),
)

# From the SEP address map in hw/sys/sep/doc/memory_map.adoc (its tables are
# hw/sys/sep/regs/gen/adoc/memory_map.adoc). Inclusive ends. Reserved rows use _RSV_.
# (base, end_inclusive, unit, desc)
_MAP_ROWS = (
    # Coarse CPU view.
    (0x0000_0000, 0x0FFF_FFFF, "External", "External to chiplet, but not in SMU (SMC, DTP, etc)."),
    (0x1000_0000, 0x1FFF_FFFF, "SEP Local", "SEP Local resources (DMA, Crypto, etc)"),
    (0x2000_0000, 0x3FFF_FFFF, _RSV, "Reserved for adopter extension IP"),
    (0x4000_0000, 0x7FFF_FFFF, "SMC", "SMC Resources"),
    (0x8000_0000, 0xBFFF_FFFF, "SMU", "SMU Resources (DTP, etc)"),
    (0xC000_0000, 0xCFFF_FFFF, "SEP CPU Resources", "EL2 Veer Resources (DCCM, ICCM, PIC)"),
    (0xD000_0000, 0xFFFF_FFFF, "SEP Local Alias", "Corresponds to 0x1000_0000 - 0x4000_0000"),
    # CPU TCM detail.
    (0xC000_0000, 0xC003_FFFF, "ICCM", "Tightly Coupled Instruction SRAM"),
    (0xC004_0000, 0xC005_FFFF, "DCCM", "Tightly Coupled Data SRAM"),
    (0xC006_0000, 0xC007_FFFF, _RSV, "Reserved"),
    (0xC008_0000, 0xC008_7FFF, "PIC", "Interrupt controller for El2 CPU"),
    (0xC008_8000, 0xCFFF_FFFF, _RSV, "Reserved"),
    # SEP-local detail.
    (0x1000_0000, 0x1003_FFFF, "SRAM", "Scratch SRAM"),
    (0x1004_0000, 0x1004_FFFF, "ROM", "BL0 immutable instruction memory"),
    (0x1005_0000, 0x107F_FFFF, _RSV, "reserved"),
    (0x1080_0000, 0x1080_0FFF, "DMA", "DMA CSR"),
    (0x1080_1000, 0x1080_1FFF, "WDT", "Watchdog Timer"),
    *_SRB_ROWS,
    (
        0x1080_3000,
        0x1080_3007,
        "RST_CTRL",
        "SEP Reset Controller (software reset for KM, the crypto accelerators and the TRNG)",
    ),
    (0x1080_3008, 0x108F_FFFF, _RSV, "reserved"),
    (0x1090_0000, 0x1090_FFFF, "OTBN", "Public Key processor memory and CSR"),
    (0x1091_0000, 0x1091_0FFF, "AES", "Block Cipher"),
    (0x1091_1000, 0x1091_2FFF, "HMAC-SHA2", "Hash / MAC"),
    (0x1091_3000, 0x1091_3FFF, "KMAC-SHA3", "Hash / MAC"),
    (0x1091_4000, 0x1091_4FFF, _RSV, "Reserved"),
    (0x1091_5000, 0x1091_5FFF, "DRBG", "Deterministic Random Bit Generator"),
    (0x1091_6000, 0x1091_6FFF, "ESRC", "Entropy Source"),
    (0x1091_7000, 0x1091_7FFF, "TRNG", "External TRNG CSR passthrough"),
    (0x1091_8000, 0x1091_FFFF, "LC", "Life Cycle Controller"),
    (0x1092_0000, 0x1092_0FFF, "KM", "Key Manager"),
    (0x1092_1000, 0x1092_FFFF, _RSV, "Reserved"),
    *_OTP_ROWS,
    (
        0x1094_0000,
        0x1094_FFFF,
        "ABR",
        "Adams Bridge post-quantum accelerator (ML-DSA-87 / ML-KEM-1024) CSR aperture",
    ),
    (
        0x1095_0000,
        0x1095_FFFF,
        "EPOOL",
        "Entropy Pool FIFO (read-only drain; writes return SLVERR). Filled by native EDN.",
    ),
    (0x1096_0000, 0x109F_FFFF, _RSV, "Reserved"),
    *_SYS_ROWS,
    (0x10A4_0000, 0x10AF_FFFF, _RSV, "Reserved"),
    (0x10B0_0000, 0x10BF_FFFF, "IO", "External IO Peripherals Bridge: UART, GPIO etc."),
    (
        0x1100_0000,
        0x117F_FFFF,
        "AP Remap Region",
        "Write to this region to be routed to the AP remapper",
    ),
    (
        0x1180_0000,
        0x11FF_FFFF,
        "STEE Remap Region",
        "Write to this region to be routed to the STEE remapper",
    ),
    (0x1200_0000, 0x1FFF_FFFF, _RSV, "Reserved"),
    (0x2000_0000, 0x3FFF_FFFF, _RSV, "Reserved for adopter extension IP"),
)


def spec_regions() -> tuple[SpecRegion, ...]:
    """Every allocation row, finest first."""
    rows = [SpecRegion(*row) for row in _MAP_ROWS]
    for r in rows:
        if r.end_addr < r.base:
            raise RuntimeError(
                f"memory-map row runs backwards: 0x{r.base:08x}-0x{r.end_addr:08x} ({r.unit})"
            )
    rows.extend(_hole_regions(rows))
    return tuple(sorted(rows, key=lambda r: (r.end_addr - r.base, r.base)))


def _hole_regions(rows: list[SpecRegion]) -> list[SpecRegion]:
    """A gap inside a coarse window with no detailed row is reserved."""
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


def region_of(addr: int, regions=None) -> SpecRegion | None:
    """The spec row covering ``addr``, or None when no row describes it."""
    for r in regions if regions is not None else spec_regions():
        if r.contains(addr):
            return r
    return None


def may_complete(addr: int, regions=None) -> bool:
    """True when the map allocates ``addr``. False: the fabric must refuse."""
    r = region_of(addr, regions)
    return r is not None and not r.reserved


def _selftest() -> None:
    regions = spec_regions()
    # Inside the SRB, OTP and SYS windows, no RDL block owns these spans
    # (hw/sys/sep/regs/gen/py/sep_reg.py bases and sizes), so none may complete.
    for lo, hi in (
        (0x1080_2040, 0x1080_207F),
        (0x1080_20C0, 0x1080_2FFF),
        (0x1093_0600, 0x1093_FFFF),
        (0x10A1_0280, 0x10A1_02FF),
        (0x10A1_0380, 0x10A1_FFFF),
        (0x10A2_0400, 0x10A2_0FFF),
        (0x10A2_1200, 0x10A2_FFFF),
        (0x10A3_2000, 0x10A3_FFFF),
    ):
        for a in (lo, hi & ~0x3):
            assert not may_complete(a, regions), f"0x{a:08x} has no RDL block but reads allocated"
    for unit, stem in (
        ("SRB cold", "SEP_SCRATCH_COLD"),
        ("SRB warm", "SEP_SCRATCH_WARM"),
        ("OTP MMR", "EFUSE_MMR"),
        ("SYS CPU control", "SEP_CPU_CTRL"),
    ):
        hit = region_of(sym(f"{stem}_REG_MAP_BASE_ADDR"), regions)
        assert hit is not None and hit.unit == unit, f"{stem} base -> {hit}"
    infilt = region_of(sym("INBOUND_FILTER_CTRL_15__REG_MAP_BASE_ADDR") + 0x18, regions)
    assert infilt is not None and infilt.unit == "SYS inbound filter", f"array padding -> {infilt}"
    assert len(regions) >= 25, f"only {len(regions)} memory-map rows after holes"

    assert may_complete(0x1080_0000, regions), "DMA CSR base read as unallocated"
    sram = region_of(0x1001_0000, regions)
    assert sram is not None and sram.unit == "SRAM", f"0x10010000 -> {sram}"
    # The SRAM row must span the generated SystemRDL memory, so a map edit that
    # shrinks or grows either side fails here instead of in the refuse walk.
    assert sram.base == sym("SEP_SRAM_MEM_BASE_ADDR"), f"{sram}"
    assert sram.end_addr + 1 - sram.base == sym("SEP_SRAM_MEM_SIZE"), f"{sram}"
    assert may_complete(0x1080_1FFF, regions), "WDT window top read as unallocated"
    assert not may_complete(0x1080_3008, regions), "reset-ctrl gap read as allocated"
    assert not may_complete(0x1092_1000, regions), "KM reserved gap read as allocated"
    assert not may_complete(0x10FF_0000, regions), "SEP-local hole read as allocated"

    dma = region_of(0x1080_0000, regions)
    assert dma is not None and dma.unit == "DMA", f"0x10800000 -> {dma}"
    assert dma.base == 0x1080_0000 and dma.end_addr == 0x1080_0FFF, f"{dma}"

    from sep_spec_tables import window

    alias = window("SEP Local Alias")
    hit = region_of(alias.base, regions)
    assert hit is not None and hit.unit == "SEP Local Alias"
    assert hit.base == alias.base and hit.end_addr == alias.end - 1
    for name in ("ABR", "EPOOL", "AP Remap Region", "STEE Remap Region"):
        w = window(name)
        hit = region_of(w.base, regions)
        assert hit is not None and hit.unit == name, f"{name} -> {hit}"
        assert hit.base == w.base and hit.end_addr == w.end, f"{name} {hit} vs {w}"


_selftest()
