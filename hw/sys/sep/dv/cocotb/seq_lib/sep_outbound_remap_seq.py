# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Live AP/STEE output-remap + outbound-filter datapath driver.

Programs one output-remap region so an AP or STEE window access is rewritten
to a seed-selected outbound address, then programs one outbound-filter entry
to allow only that remapped beat. A second region is left at offset 0 so its
translated address misses the allow window (block-by-default DECERR).

Address rewrite: ``{offset[55:IdxStart], adjusted[IdxStart-1:0]}``.
IdxStart is log2(AP window / region count) from the generated map
and fabric.adoc. Region bases are ``AP_REGION_MEM_BASE_ADDR`` /
``STEE_REGION_MEM_BASE_ADDR``.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from env.sep_spec_tables import fabric_output_remap_regions
from sep_reg_meta import AP_OUTPUT_REMAP_CTRL_0, indexed_block_count, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    AP_BASE,
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_READ_ALLOWED,
    F_SRC_ID_LSB,
    F_WRITE_ALLOWED,
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    OUTFILT_BASE,
    REMAP_STRIDE,
    STEE_BASE,
)

# och_sep_top_addrmap / hw/sys/sep/regs/gen/c/sep_addr.h
AP_REGION_BASE = sym("AP_REGION_MEM_BASE_ADDR")
STEE_REGION_BASE = sym("STEE_REGION_MEM_BASE_ADDR")
# Region count from fabric.adoc ("Sixteen remap regions") and the RDL array.
# IdxStart is log2(AP window / N), so a size or count change fails import.
N_REGIONS = indexed_block_count("AP_OUTPUT_REMAP_CTRL")
_AP_WINDOW = sym("AP_REGION_MEM_SIZE")
if _AP_WINDOW % N_REGIONS:
    raise RuntimeError(
        f"AP_REGION_MEM_SIZE 0x{_AP_WINDOW:x} is not divisible by {N_REGIONS} regions"
    )
_REGION_SPAN = _AP_WINDOW // N_REGIONS
if _REGION_SPAN.bit_count() != 1:
    raise RuntimeError(f"output-remap region span 0x{_REGION_SPAN:x} is not a power of two")
IDX_START = _REGION_SPAN.bit_length() - 1
if N_REGIONS != fabric_output_remap_regions():
    raise RuntimeError(
        f"RDL has {N_REGIONS} AP remap regions; fabric.adoc states {fabric_output_remap_regions()}"
    )
# `outbound_filter_ctrl[32]`; the count comes from the export so a seed can
# select any entry the bank actually has.
OUTFILT_N_ENTRIES = indexed_block_count("OUTBOUND_FILTER_CTRL")

# sep_outbound_mbx STDOUT window. The responder OKAYs every outbound address;
# only console capture decodes the write address.
REMAP_TARGET_BASE = 0x8000_0000
REMAP_ATTRS = AP_OUTPUT_REMAP_CTRL_0.offset("REGION_REGION_ATTRS")
REMAP_OFFSET_MASK = AP_OUTPUT_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "offset")

RESP_OKAY = 0
RESP_DECERR = 3


def remap_access_addr(region_base: int, region: int, intra: int) -> int:
    return region_base + (region << IDX_START) + intra


def remapped_addr(offset: int, intra: int) -> int:
    """Predicted post-remap address for intra-region offset ``intra``."""
    return ((offset >> IDX_START) << IDX_START) | (intra & ((1 << IDX_START) - 1))


class SepOutboundRemapCfg:
    """Single source of truth: bank/region/target/forbidden beat from the seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.use_ap = bool(rng.getrandbits(1))
        self.region_base = AP_REGION_BASE if self.use_ap else STEE_REGION_BASE
        self.csr_base = AP_BASE if self.use_ap else STEE_BASE
        self.bank = "AP" if self.use_ap else "STEE"
        self.region = rng.randrange(N_REGIONS)
        others = [i for i in range(N_REGIONS) if i != self.region]
        self.forbidden_region = rng.choice(others)
        self.entry = rng.randrange(OUTFILT_N_ENTRIES)
        # 8-byte aligned intra-region offset so the filter window is one beat.
        self.intra = rng.randrange(0, 0x1000, 8)
        # Next beat of the same region. The allow entry covers one address,
        # so this beat translates to a non-zero address outside that entry.
        # Offset 0 on the other region can also miss because the translated
        # address is low; this beat cannot.
        self.neighbor_intra = self.intra + 8 if self.intra + 8 < _REGION_SPAN else self.intra - 8
        self.offset = REMAP_TARGET_BASE
        self.access_addr = remap_access_addr(self.region_base, self.region, self.intra)
        self.expect_addr = remapped_addr(self.offset, self.intra)
        self.neighbor_addr = remap_access_addr(self.region_base, self.region, self.neighbor_intra)
        self.neighbor_expect = remapped_addr(self.offset, self.neighbor_intra)
        self.forbidden_addr = remap_access_addr(self.region_base, self.forbidden_region, self.intra)
        self.forbidden_expect = remapped_addr(0, self.intra)
        if self.expect_addr == self.access_addr:
            raise RuntimeError("remap target equals identity -- vacuous")
        if self.expect_addr == self.forbidden_expect:
            raise RuntimeError("allowed and forbidden remaps collide")
        if (
            self.neighbor_expect == self.expect_addr
            or self.neighbor_expect == self.forbidden_expect
        ):
            raise RuntimeError("neighbor remap does not leave the allow window")
        if self.neighbor_expect < REMAP_TARGET_BASE:
            raise RuntimeError("neighbor remap collapsed to a low address")

    def summary(self) -> str:
        return (
            f"seed={self.seed} bank={self.bank} region={self.region} "
            f"forbidden_region={self.forbidden_region} entry={self.entry} "
            f"access=0x{self.access_addr:08x} expect=0x{self.expect_addr:08x} "
            f"forbidden=0x{self.forbidden_addr:08x}"
        )


class SepOutboundRemap(SepAxiRegDriver):
    """CPU-LSU driver: program remap ATTRS + one outbound-filter allow entry."""

    _DRIVER_TAG = "OUTREMAP"

    async def program(self, cfg: SepOutboundRemapCfg) -> None:
        attrs = cfg.csr_base + cfg.region * REMAP_STRIDE + REMAP_ATTRS
        masked = cfg.offset & REMAP_OFFSET_MASK
        await self._wr(attrs, masked & 0xFFFF_FFFF)
        await self._wr(attrs + 4, masked >> 32)
        rb_lo = await self._rd(attrs)
        rb_hi = await self._rd(attrs + 4)
        want_lo = masked & 0xFFFF_FFFF
        want_hi = masked >> 32
        assert rb_lo == want_lo and rb_hi == want_hi, (
            f"{cfg.bank} r{cfg.region} ATTRS read 0x{rb_hi:08x}{rb_lo:08x} "
            f"!= 0x{want_hi:08x}{want_lo:08x}"
        )

        ebase = OUTFILT_BASE + cfg.entry * FILTER_STRIDE
        await self._wr(ebase + FILTER_START_ADDR, cfg.expect_addr)
        await self._wr(ebase + FILTER_START_ADDR + 4, 0)
        await self._wr(ebase + FILTER_END_ADDR, cfg.expect_addr)
        await self._wr(ebase + FILTER_END_ADDR + 4, 0)
        await self.set_filter_enable(cfg, True)

    async def set_filter_enable(self, cfg: SepOutboundRemapCfg, enabled: bool) -> None:
        ebase = OUTFILT_BASE + cfg.entry * FILTER_STRIDE
        cfg_lo = F_READ_ALLOWED | F_WRITE_ALLOWED | F_ALLOW_NS | (0 << F_SRC_ID_LSB)
        if enabled:
            cfg_lo |= F_ENTRY_ENABLED
        await self._wr(ebase + FILTER_CONFIG, cfg_lo)


def remap_probe_seq(addr: int, *, expect_error: bool) -> SepAxiAccessSeq:
    """32-bit CPU-LSU read of an AP/STEE window address."""
    return SepAxiAccessSeq(
        "outremap_rd",
        op=SepAxiOp.READ,
        addr=addr,
        length=4,
        size=2,
        expect_error=expect_error,
    )


def _selftest() -> None:
    assert remapped_addr(0x8000_0000, 0) == 0x8000_0000
    assert remapped_addr(0x8000_0000, 0x10) == 0x8000_0010
    assert remapped_addr(0, 0x20) == 0x20
    assert remap_access_addr(AP_REGION_BASE, 0, 0) == AP_REGION_BASE
    cfg = SepOutboundRemapCfg(1)
    assert cfg.access_addr != cfg.expect_addr
    _ = sym("AP_OUTPUT_REMAP_CTRL_0__REG_MAP_BASE_ADDR")


_selftest()
