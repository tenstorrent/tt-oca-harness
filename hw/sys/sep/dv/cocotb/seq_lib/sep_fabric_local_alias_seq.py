# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Live local-master alias-remap datapath driver.

Programs one of the sixteen ``axi_alias_remap`` regions on the system-
peripherals local-master path so a CPU-LSU beat of a filter-bank page is
rewritten to ``CLOCK_GATE_CTRL``. The predicted address is
``{offset[55:12] + addr[55:12], addr[11:0]}``
(``hw/ip/axi_alias_remap/regs/alias_remap.rdl`` REGION_ATTRS offset:
add to bits [55:12], preserve [11:0]). The mailbox
window at ``0x8000_0000`` is not an LSU identity target.

CSR programming of the bank stays on ``sep_fabric_csr_bank_seq``. This
module owns the live offset proof only. Spec cacheable / valid-as-woset /
unprogrammed-passthrough bits are not claimed here.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import LOCAL_MASTER_ALIAS_REMAP_CTRL_0, SEP_CPU_CTRL, indexed_block_count, sym

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_ATTRS,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_START,
    ALIAS_STRIDE,
    CLOCK_GATE_CTRL,
    CLOCK_GATE_UNGATE,
    INFILT_BASE,
    OUTFILT_BASE,
)

# `local_master_alias_remap_ctrl[16]`; the count comes from the export. The
# datapath test selects the upper half so the remap debug index's MSB is exercised.
N_REGIONS = indexed_block_count("LOCAL_MASTER_ALIAS_REMAP_CTRL")
# Remap geometry from the REGION_ATTRS ``offset`` field and the START/END
# address fields of alias_remap.rdl: the addend covers [ADDR_TOP-1:IDX_START].
OFFSET_MASK = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "offset")
IDX_START = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_lsb("REGION_REGION_ATTRS", "offset")
ADDR_TOP = IDX_START + LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_width("REGION_REGION_ATTRS", "offset")
ADDEND_MASK = (1 << (ADDR_TOP - IDX_START)) - 1
START_MASK = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_mask("REGION_REGION_START", "start_addr")
END_MASK = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_mask("REGION_REGION_END", "end_addr")
PAGE = 1 << IDX_START
VALID_HI = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "valid") >> 32
SRC_PAGES = (OUTFILT_BASE & ~(PAGE - 1), INFILT_BASE & ~(PAGE - 1))
DEST_ADDR = CLOCK_GATE_CTRL
DEST_MARKER = CLOCK_GATE_UNGATE
# Implemented CLOCK_GATE_CTRL bits (sep_cpu_ctrl.rdl).
DEST_MASK = SEP_CPU_CTRL.mask32("CLOCK_GATE_CTRL")


def remapped_addr(offset: int, addr: int) -> int:
    """Predicted post-remap address (4 KiB-aligned addend, low 12 bits kept)."""
    addend = (offset >> IDX_START) & ADDEND_MASK
    high = ((addr >> IDX_START) + addend) & ADDEND_MASK
    return (high << IDX_START) | (addr & (PAGE - 1))


class SepLocalAliasCfg:
    """Single source of truth: region, source page, and intra-page beat from the seed."""

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        upper_half = N_REGIONS // 2
        self.region = upper_half + rng.randrange(N_REGIONS - upper_half)
        self.src_page = rng.choice(SRC_PAGES)
        self.intra = DEST_ADDR & (PAGE - 1)
        self.access_addr = self.src_page + self.intra
        self.expect_addr = DEST_ADDR
        self.marker = DEST_MARKER
        # Implemented bits of CLOCK_GATE_CTRL inverted: distinct from the marker
        # in every implemented bit, so a write that lands elsewhere cannot move it.
        self.parked = DEST_MARKER ^ DEST_MASK
        addend = (self.expect_addr >> IDX_START) - (self.access_addr >> IDX_START)
        self.offset = (addend & ADDEND_MASK) << IDX_START
        if remapped_addr(self.offset, self.access_addr) != self.expect_addr:
            raise RuntimeError("local-alias offset does not predict CLOCK_GATE_CTRL")
        if self.parked == self.marker:
            raise RuntimeError("CLOCK_GATE_CTRL has no implemented bit to park -- vacuous")
        if self.expect_addr == self.access_addr:
            raise RuntimeError("local-alias target equals identity -- vacuous")
        if self.src_page == (DEST_ADDR & ~(PAGE - 1)):
            raise RuntimeError("source page collides with CLOCK_GATE_CTRL")

    def summary(self) -> str:
        return (
            f"seed={self.seed} region={self.region} "
            f"access=0x{self.access_addr:08x} expect=0x{self.expect_addr:08x} "
            f"offset=0x{self.offset:x}"
        )


class SepLocalAlias(SepAxiRegDriver):
    """CPU-LSU driver: program one alias-remap region."""

    _DRIVER_TAG = "ALIAS"

    async def program(self, cfg: SepLocalAliasCfg, *, valid: bool = True) -> None:
        base = ALIAS_BASE + cfg.region * ALIAS_STRIDE
        start = cfg.src_page
        end = cfg.src_page + PAGE
        start &= START_MASK
        end &= END_MASK
        offset = cfg.offset & OFFSET_MASK
        await self._wr(base + ALIAS_START, start & 0xFFFF_FFFF)
        await self._wr(base + ALIAS_START + 4, start >> 32)
        await self._wr(base + ALIAS_END, end & 0xFFFF_FFFF)
        await self._wr(base + ALIAS_END + 4, end >> 32)
        await self._wr(base + ALIAS_ATTRS, offset & 0xFFFF_FFFF)
        # REGION_ATTRS.valid gates the remap (alias_remap.rdl). Programming the
        # window with the bit clear is what makes the pass-through path
        # observable: bounds and offset are live, only the enable is not.
        valid_bit = VALID_HI if valid else 0
        await self._wr(base + ALIAS_ATTRS + 4, (offset >> 32) | valid_bit)
        rb_lo = await self._rd(base + ALIAS_ATTRS)
        rb_hi = await self._rd(base + ALIAS_ATTRS + 4)
        want_lo = offset & 0xFFFF_FFFF
        want_hi = (offset >> 32) | valid_bit
        assert rb_lo == want_lo and rb_hi == want_hi, (
            f"alias r{cfg.region} ATTRS read 0x{rb_hi:08x}{rb_lo:08x} "
            f"!= 0x{want_hi:08x}{want_lo:08x}"
        )


def alias_probe_seq(addr: int) -> SepAxiAccessSeq:
    """32-bit CPU-LSU read of a remapped or identity address."""
    return SepAxiAccessSeq(
        "alias_rd",
        op=SepAxiOp.READ,
        addr=addr,
        length=4,
        size=2,
    )


def _selftest() -> None:
    assert remapped_addr(0x1_0000, 0x10A2_0008) == 0x10A3_0008
    cfg = SepLocalAliasCfg(1)
    assert remapped_addr(cfg.offset, cfg.access_addr) == DEST_ADDR
    _ = sym("LOCAL_MASTER_ALIAS_REMAP_CTRL_0__REG_MAP_BASE_ADDR")


_selftest()
