# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Live AP/STEE output-remap + outbound-filter datapath driver.

Programs one output-remap region so an AP or STEE window access is rewritten
to a seed-selected outbound address, then programs one outbound-filter entry
to allow only that remapped beat. A second region is left at offset 0 so its
translated address misses the allow window (block-by-default DECERR).

Address rewrite (``hw/common/axi/output_remap/rtl/output_remap.sv``):
``{offset[55:IdxStart], adjusted[IdxStart-1:0]}`` with IdxStart=19
(``sep_pkg`` 512 KiB regions). Region bases are
``OCH_SEP_TOP_AP_REGION_BASE_ADDR`` / ``STEE_REGION_BASE_ADDR``.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    AP_BASE, FILTER_CONFIG, FILTER_STRIDE, F_ALLOW_NS, F_ENTRY_ENABLED,
    F_READ_ALLOWED, F_SRC_ID_LSB, F_WRITE_ALLOWED, OUTFILT_BASE, REMAP_STRIDE,
    STEE_BASE,
)
from sep_reg_meta import sym

# och_sep_top_addrmap / hw/sys/sep/regs/gen/c/sep_addr.h
AP_REGION_BASE = 0x1100_0000
STEE_REGION_BASE = 0x1180_0000
# sep_pkg::NUM_*_OUTPUT_REMAP_IDX_START / NUM_*_OUTPUT_REMAP_REGIONS
IDX_START = 19
N_REGIONS = 16
OUTFILT_N_ENTRIES = 16

# sep_outbound_mbx STDOUT window: always-ready OKAY responder on smn_outbound.
REMAP_TARGET_BASE = 0x8000_0000

FILTER_START_ADDR = 0x08
FILTER_END_ADDR = 0x10
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
        self.offset = REMAP_TARGET_BASE
        self.access_addr = remap_access_addr(self.region_base, self.region, self.intra)
        self.expect_addr = remapped_addr(self.offset, self.intra)
        self.forbidden_addr = remap_access_addr(
            self.region_base, self.forbidden_region, self.intra)
        self.forbidden_expect = remapped_addr(0, self.intra)
        if self.expect_addr == self.access_addr:
            raise RuntimeError("remap target equals identity -- vacuous")
        if self.expect_addr == self.forbidden_expect:
            raise RuntimeError("allowed and forbidden remaps collide")

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
        attrs = cfg.csr_base + cfg.region * REMAP_STRIDE
        await self._wr(attrs, cfg.offset & 0xFFFF_FFFF)
        await self._wr(attrs + 4, (cfg.offset >> 32) & 0x00FF_FFFF)
        rb_lo = await self._rd(attrs)
        rb_hi = await self._rd(attrs + 4)
        want_lo = cfg.offset & 0xFFFF_FFFF
        want_hi = (cfg.offset >> 32) & 0x00FF_FFFF
        assert rb_lo == want_lo and rb_hi == want_hi, (
            f"{cfg.bank} r{cfg.region} ATTRS read 0x{rb_hi:08x}{rb_lo:08x} "
            f"!= 0x{want_hi:08x}{want_lo:08x}"
        )

        ebase = OUTFILT_BASE + cfg.entry * FILTER_STRIDE
        await self._wr(ebase + FILTER_START_ADDR, cfg.expect_addr)
        await self._wr(ebase + FILTER_START_ADDR + 4, 0)
        await self._wr(ebase + FILTER_END_ADDR, cfg.expect_addr)
        await self._wr(ebase + FILTER_END_ADDR + 4, 0)
        cfg_lo = (
            F_READ_ALLOWED | F_WRITE_ALLOWED | F_ENTRY_ENABLED | F_ALLOW_NS
            | (0 << F_SRC_ID_LSB)
        )
        await self._wr(ebase + FILTER_CONFIG, cfg_lo)


def remap_probe_seq(addr: int, *, expect_error: bool) -> SepAxiAccessSeq:
    """32-bit CPU-LSU read of an AP/STEE window address."""
    return SepAxiAccessSeq(
        "outremap_rd", op=SepAxiOp.READ, addr=addr, length=4, size=2,
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
