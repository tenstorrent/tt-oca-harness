# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""SEP address-map classification for AXI response expectations.

``may_complete(addr)`` is true only when ``_MAP_ROWS`` (plus derived holes)
allocates that address. A reserved row, and a gap inside a coarse window
with no detailed row, must not return OKAY. The refusal flavour is unnamed.
"""

from __future__ import annotations

from dataclasses import dataclass

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
    (0x1080_2000, 0x1080_2FFF, "SRB", "Dual Scratch Register Banks"),
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
    (0x1093_0000, 0x1093_7FFF, "OTP", "Fuse Control and Shadow Memory"),
    (0x1093_8000, 0x1093_FFFF, _RSV, "Reserved"),
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
    (0x10A0_0000, 0x10A3_FFFF, "SYS", "System Bus I/F"),
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
    assert len(_MAP_ROWS) == 43, f"DV-owned map has {len(_MAP_ROWS)} rows, want 43"
    regions = spec_regions()
    assert len(regions) >= 25, f"only {len(regions)} memory-map rows after holes"

    assert may_complete(0x1080_0000, regions), "DMA CSR base read as unallocated"
    sram = region_of(0x1001_0000, regions)
    assert sram is not None and sram.unit == "SRAM", f"0x10010000 -> {sram}"
    # The SRAM row must span the generated SystemRDL memory, so a map edit that
    # shrinks or grows either side fails here instead of in the refuse walk.
    from sep_reg_meta import sym

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
