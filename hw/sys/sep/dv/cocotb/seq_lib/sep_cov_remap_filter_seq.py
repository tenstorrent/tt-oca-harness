# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Coverage-stimulus drivers for the SEP remap and filter datapath.

STIMULUS ONLY. Nothing in this module asserts a DUT contract. The register
programming is the payload: the remap and filter banks execute their decode on
every beat, but the suite programs one entry with one value, so the bank inputs
hold their reset state. These drivers write the whole bank and drive traffic
through each entry in turn.

Addresses and field positions come from ``seq_lib.sep_fabric_csr_bank_seq`` and
``seq_lib.sep_outbound_remap_seq``, which derive them from the generated
register export.

Layering, so a caller picks the right bank:

* ``SepCovFilterBank`` -- inbound (16) and outbound (32) ``axi_filter_wrap``
  entries: START_ADDR, END_ADDR, FILTER_CONFIG.
* ``SepCovAliasRemap`` -- the sixteen local-master ``axi_alias_remap`` regions
  ahead of the system-peripherals routing demux.
* ``SepCovOutputRemap`` -- the AP and STEE ``output_remap`` region tables.
* ``SepCovDma`` -- the Secure DMA descriptor CSRs, so a DMA-mastered beat
  crosses ``axi_window_remap`` on the DMA path.

Safety rule for every driver here: a rule is programmed explicitly, never
randomised, and a window that the driver does not also drive traffic through is
left disabled or placed in address space the caller never issues. A filter or
remap rule that swallowed the caller's own register path would wedge the test.
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from sep_reg_meta import (
    AP_OUTPUT_REMAP_CTRL_0,
    LOCAL_MASTER_ALIAS_REMAP_CTRL_0,
    RegBlock,
    indexed_block_count,
    sym,
)

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_ATTRS,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_START,
    ALIAS_STRIDE,
    F_ALLOW_BURST,
    F_ALLOW_NS,
    F_ENTRY_ENABLED,
    F_GROUP_ID_LSB,
    F_READ_ALLOWED,
    F_SRC_ID_LSB,
    F_WRITE_ALLOWED,
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_RW_MASK,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    OUTFILT_BASE,
    REMAP_STRIDE,
)
from seq_lib.sep_outbound_remap_seq import (
    AP_BASE,
    AP_REGION_BASE,
    REMAP_ATTRS,
    REMAP_OFFSET_MASK,
    STEE_BASE,
    STEE_REGION_BASE,
)
from seq_lib.sep_outbound_remap_seq import (
    IDX_START as REMAP_IDX_START,
)

# --- bank sizes ---------------------------------------------------------------
# From the generated export, never a literal: a short count silently skips the
# tail entries and still reports a clean pass.
INFILT_ENTRIES = indexed_block_count("INBOUND_FILTER_CTRL")
OUTFILT_ENTRIES = indexed_block_count("OUTBOUND_FILTER_CTRL")
ALIAS_REGIONS = indexed_block_count("LOCAL_MASTER_ALIAS_REMAP_CTRL")
AP_REGIONS = indexed_block_count("AP_OUTPUT_REMAP_CTRL")
STEE_REGIONS = indexed_block_count("STEE_OUTPUT_REMAP_CTRL")

# --- address geometry ---------------------------------------------------------
SEP_SRAM_BASE = sym("SEP_SRAM_MEM_BASE_ADDR")
SEP_SRAM_SIZE = sym("SEP_SRAM_MEM_SIZE")
PAGE_SHIFT = 12
PAGE_SIZE = 1 << PAGE_SHIFT

# axi_filter START_ADDR / END_ADDR and axi_alias_remap REGION_ATTRS.offset are
# all 4 KiB-granular fields spanning address bits [55:12].
ADDR_FIELD_LSB = 12
ADDR_FIELD_MSB = 55
ADDR_FIELD_MASK = ((1 << (ADDR_FIELD_MSB + 1)) - 1) & ~((1 << ADDR_FIELD_LSB) - 1)

ALIAS_VALID_HI = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "valid") >> 32
ALIAS_CACHEABLE_HI = (
    LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "cacheable") >> 32
)
ALIAS_OFFSET_MASK = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_mask("REGION_REGION_ATTRS", "offset")

# Source pages for the alias-remap sweep. The remapper sits on the local-master
# port of `sep_system_peripherals`, which the SEP crossbar reaches only for the
# ranges `sep_local_axi_xbar_pkg` gives that port, so a source page outside them
# never reaches the region table. 0x0800_0000 is inside
# SEP_SYSTEM_PERIPHERALS_EXTERNAL_CHIPLET (0x0 .. 0x1000_0000,
# hw/sys/sep/rtl/sep_local_axi_xbar_pkg.sv) and carries no block of its own, so
# no other stimulus in these tests issues an address there and a region left
# valid over one of these pages cannot swallow a live beat.
ALIAS_SRC_BASE = 0x0800_0000
# Destination pages: the SEP SRAM answers a read and a write at any offset, so a
# remapped beat completes OKAY wherever in the bank a region points it.
ALIAS_DST_BASE = SEP_SRAM_BASE

# The outbound target aperture. tb/sep_outbound_mbx.sv answers every address in
# this window, so an outbound beat that the filter allows completes OKAY.
OUTBOUND_TARGET_BASE = 0x8000_0000
OUTBOUND_TARGET_SPAN = 0x1_0000

# --- Secure DMA ---------------------------------------------------------------
SECURE_DMA = RegBlock("SECURE_DMA")
DMA_SRC_LO = SECURE_DMA.addr("SRC_ADDR_LO")
DMA_SRC_HI = SECURE_DMA.addr("SRC_ADDR_HI")
DMA_DST_LO = SECURE_DMA.addr("DST_ADDR_LO")
DMA_DST_HI = SECURE_DMA.addr("DST_ADDR_HI")
DMA_ASID = SECURE_DMA.addr("ADDR_SPACE_ID")
DMA_ASID_BOTH_OT = SECURE_DMA.reset32("ADDR_SPACE_ID")
DMA_RANGE_BASE = SECURE_DMA.addr("ENABLED_MEMORY_RANGE_BASE")
DMA_RANGE_LIMIT = SECURE_DMA.addr("ENABLED_MEMORY_RANGE_LIMIT")
DMA_RANGE_VALID = SECURE_DMA.addr("RANGE_VALID")
DMA_TOTAL_SIZE = SECURE_DMA.addr("TOTAL_DATA_SIZE")
DMA_CHUNK_SIZE = SECURE_DMA.addr("CHUNK_DATA_SIZE")
DMA_WIDTH = SECURE_DMA.addr("TRANSFER_WIDTH")
DMA_CONTROL = SECURE_DMA.addr("CONTROL")
DMA_SRC_CONFIG = SECURE_DMA.addr("SRC_CONFIG")
DMA_DST_CONFIG = SECURE_DMA.addr("DST_CONFIG")
DMA_STATUS = SECURE_DMA.addr("STATUS")
DMA_CTRL_GO = SECURE_DMA.field_mask("CONTROL", "go")
DMA_CTRL_INITIAL = SECURE_DMA.field_mask("CONTROL", "initial_transfer")
DMA_SRC_INCREMENT = SECURE_DMA.field_mask("SRC_CONFIG", "increment")
DMA_DST_INCREMENT = SECURE_DMA.field_mask("DST_CONFIG", "increment")
DMA_STATUS_DONE = SECURE_DMA.field_mask("STATUS", "done")
DMA_STATUS_ERROR = SECURE_DMA.field_mask("STATUS", "error")
DMA_STATUS_CHUNK_DONE = SECURE_DMA.field_mask("STATUS", "chunk_done")
DMA_WIDTH_4B = 0x2  # TRANSFER_WIDTH encoding, dv/fw/drivers/sep_dma.h
# sep_pkg::SEP_LOCAL_ALIAS_REGION_BASE / _SIZE and the SEP_LOCAL_BASE_ADDR CSR
# drive axi_window_remap on the DMA path (sep_dma_wrap.sv u_dma_local_alias_remap).
SEP_CPU_CTRL_LOCAL_BASE = RegBlock("SEP_CPU_CTRL").addr("SEP_LOCAL_BASE_ADDR")
DMA_ALIAS_TARGET_BASE = 0x1000_0000  # sep_pkg::SEP_LOCAL_ALIAS_REGION_BASE


def addr_field_walk_values() -> tuple[int, ...]:
    """START/END/offset values that toggle every bit of a 4 KiB-granular field.

    All-ones then all-zeros moves every bit of the field in both directions on
    whichever sub-filter instance holds it, which a walking one alone does not:
    a walking one visits each bit once, but the bank has one instance per entry
    and the toggle report scores each instance separately.
    """
    return (ADDR_FIELD_MASK, 0, 0x5555_5555_5555_5555 & ADDR_FIELD_MASK, 0)


def filter_config_word(
    *,
    read_allowed: bool = True,
    write_allowed: bool = True,
    entry_enabled: bool = False,
    allow_ns: bool = True,
    allow_burst: bool = False,
    src_id: int = 0,
    group_id: int = 0,
) -> int:
    """One FILTER_CONFIG low word. Bit 63 (locked) lives in the hi word and is
    never written here: the lock is sticky until reset and would freeze the bank
    part way through a sweep."""
    word = (src_id & 0xF) << F_SRC_ID_LSB | (group_id & 0xF) << F_GROUP_ID_LSB
    if read_allowed:
        word |= F_READ_ALLOWED
    if write_allowed:
        word |= F_WRITE_ALLOWED
    if entry_enabled:
        word |= F_ENTRY_ENABLED
    if allow_ns:
        word |= F_ALLOW_NS
    if allow_burst:
        word |= F_ALLOW_BURST
    return word & FILTER_RW_MASK


class SepCovFilterBank(SepAxiRegDriver):
    """CPU-LSU driver over both ``axi_filter_wrap`` CSR banks."""

    _DRIVER_TAG = "COVFILT"

    @staticmethod
    def entry_base(*, inbound: bool, entry: int) -> int:
        base = INFILT_BASE if inbound else OUTFILT_BASE
        return base + entry * FILTER_STRIDE

    async def write_window(self, *, inbound: bool, entry: int, start: int, end: int) -> None:
        """Program one entry's 64-bit START_ADDR and END_ADDR as lo/hi words."""
        base = self.entry_base(inbound=inbound, entry=entry)
        await self._wr(base + FILTER_START_ADDR, start & 0xFFFF_FFFF)
        await self._wr(base + FILTER_START_ADDR + 4, (start >> 32) & 0x00FF_FFFF)
        await self._wr(base + FILTER_END_ADDR, end & 0xFFFF_FFFF)
        await self._wr(base + FILTER_END_ADDR + 4, (end >> 32) & 0x00FF_FFFF)

    async def write_config(self, *, inbound: bool, entry: int, word: int) -> None:
        base = self.entry_base(inbound=inbound, entry=entry)
        await self._wr(base + FILTER_CONFIG, word & FILTER_RW_MASK)

    async def disable_all(self, *, inbound: bool) -> None:
        """Clear FILTER_CONFIG on every entry of one bank.

        Block-by-default then decides every beat on that port, so a later
        deny-path beat is the bank's answer and not a leftover allow window.
        """
        count = INFILT_ENTRIES if inbound else OUTFILT_ENTRIES
        for entry in range(count):
            await self.write_config(inbound=inbound, entry=entry, word=0)

    async def value_walk(self, *, inbound: bool) -> int:
        """Walk every entry of one bank through the address-field values and a
        spread of FILTER_CONFIG field combinations, with ``entry_enabled`` clear
        throughout.

        The entry stays disabled, so this walk changes no access decision on any
        port: it moves ``cfg_start_addr_i`` / ``cfg_end_addr_i`` / ``cfg_src_id_i``
        / ``cfg_group_id_i`` on every ``traffic_filter`` instance and nothing else.
        Returns the number of register writes issued.
        """
        count = INFILT_ENTRIES if inbound else OUTFILT_ENTRIES
        writes = 0
        for entry in range(count):
            for value in addr_field_walk_values():
                await self.write_window(inbound=inbound, entry=entry, start=value, end=value)
                writes += 4
            # Complementary START/END so the two fields differ, and the 4 KiB
            # granule bit of each one moves independently.
            await self.write_window(
                inbound=inbound,
                entry=entry,
                start=(entry << PAGE_SHIFT) & ADDR_FIELD_MASK,
                end=(~(entry << PAGE_SHIFT)) & ADDR_FIELD_MASK,
            )
            writes += 4
            for combo in range(4):
                word = filter_config_word(
                    read_allowed=bool(combo & 1),
                    write_allowed=bool(combo & 2),
                    entry_enabled=False,
                    allow_ns=bool(combo & 1),
                    allow_burst=bool(combo & 2),
                    src_id=(entry + combo) & 0xF,
                    group_id=(entry * 3 + combo) & 0xF,
                )
                await self.write_config(inbound=inbound, entry=entry, word=word)
                writes += 1
            await self.write_config(inbound=inbound, entry=entry, word=0)
            writes += 1
        return writes


class SepCovAliasRemap(SepAxiRegDriver):
    """CPU-LSU driver over the sixteen local-master ``axi_alias_remap`` regions."""

    _DRIVER_TAG = "COVALIAS"

    @staticmethod
    def region_base(region: int) -> int:
        return ALIAS_BASE + region * ALIAS_STRIDE

    @staticmethod
    def src_page(region: int) -> int:
        return ALIAS_SRC_BASE + region * PAGE_SIZE

    @staticmethod
    def dst_page(region: int) -> int:
        return ALIAS_DST_BASE + region * PAGE_SIZE

    @staticmethod
    def offset_for(src: int, dst: int) -> int:
        """REGION_ATTRS.offset that carries ``src`` onto ``dst``.

        ``axi_alias_remap`` adds ``offset[55:12]`` to ``addr[55:12]`` and keeps
        ``addr[11:0]`` (hw/ip/axi_alias_remap/regs/alias_remap.rdl).
        """
        addend = ((dst >> PAGE_SHIFT) - (src >> PAGE_SHIFT)) & ((1 << (56 - PAGE_SHIFT)) - 1)
        return (addend << PAGE_SHIFT) & ALIAS_OFFSET_MASK

    async def program(
        self,
        region: int,
        *,
        start: int,
        end: int,
        offset: int,
        valid: bool,
        cacheable: bool = False,
    ) -> None:
        base = self.region_base(region)
        await self._wr(base + ALIAS_START, start & 0xFFFF_FFFF)
        await self._wr(base + ALIAS_START + 4, (start >> 32) & 0x00FF_FFFF)
        await self._wr(base + ALIAS_END, end & 0xFFFF_FFFF)
        await self._wr(base + ALIAS_END + 4, (end >> 32) & 0x00FF_FFFF)
        hi = (offset >> 32) & 0x00FF_FFFF
        if valid:
            hi |= ALIAS_VALID_HI
        if cacheable:
            hi |= ALIAS_CACHEABLE_HI
        await self._wr(base + ALIAS_ATTRS, offset & 0xFFFF_FFFF)
        await self._wr(base + ALIAS_ATTRS + 4, hi)

    async def invalidate_all(self) -> None:
        """Clear REGION_ATTRS.valid on every region.

        A region left valid over a page the caller then issues would rewrite
        that beat, so a sweep starts from a bank that translates nothing.
        """
        for region in range(ALIAS_REGIONS):
            await self._wr(self.region_base(region) + ALIAS_ATTRS + 4, 0)

    async def map_all_regions_to_sram(self, *, cacheable: bool = False) -> None:
        """Give every region its own 4 KiB source page and its own SRAM page.

        Every window sits in the unissued ``ALIAS_SRC_BASE`` range, so the whole
        bank can be valid at once without any region capturing the driver's own
        register path.
        """
        for region in range(ALIAS_REGIONS):
            src = self.src_page(region)
            dst = self.dst_page(region)
            await self.program(
                region,
                start=src,
                end=src + PAGE_SIZE,
                offset=self.offset_for(src, dst),
                valid=True,
                cacheable=cacheable,
            )

    async def offset_value_walk(self) -> int:
        """Walk REGION_ATTRS.offset over the 4 KiB-granular field on every region.

        Every region is invalidated first and stays invalid, so these offsets
        reach ``remap_regions_i`` and the ``prim_carry_select_adder`` addend
        input without steering a beat.
        """
        await self.invalidate_all()
        writes = 0
        for region in range(ALIAS_REGIONS):
            for value in addr_field_walk_values():
                await self.program(
                    region,
                    start=self.src_page(region),
                    end=self.src_page(region) + PAGE_SIZE,
                    offset=value & ALIAS_OFFSET_MASK,
                    valid=False,
                )
                writes += 6
            # Addends that carry across each 9-bit chunk of the 45-bit adder.
            for chunk in range(5):
                addend = (1 << (9 * chunk + 9)) - 1
                await self.program(
                    region,
                    start=self.src_page(region),
                    end=self.src_page(region) + PAGE_SIZE,
                    offset=(addend << PAGE_SHIFT) & ALIAS_OFFSET_MASK,
                    valid=False,
                )
                writes += 6
        return writes


class SepCovOutputRemap(SepAxiRegDriver):
    """CPU-LSU driver over the AP and STEE ``output_remap`` region tables."""

    _DRIVER_TAG = "COVOUTREMAP"

    @staticmethod
    def attrs_addr(*, ap: bool, region: int) -> int:
        base = AP_BASE if ap else STEE_BASE
        return base + region * REMAP_STRIDE + REMAP_ATTRS

    @staticmethod
    def access_addr(*, ap: bool, region: int, intra: int) -> int:
        base = AP_REGION_BASE if ap else STEE_REGION_BASE
        return base + (region << REMAP_IDX_START) + intra

    @staticmethod
    def remapped_addr(offset: int, intra: int) -> int:
        """``{offset[55:IdxStart], adjusted[IdxStart-1:0]}`` (output_remap.sv)."""
        return ((offset >> REMAP_IDX_START) << REMAP_IDX_START) | (
            intra & ((1 << REMAP_IDX_START) - 1)
        )

    async def set_offset(self, *, ap: bool, region: int, offset: int) -> None:
        addr = self.attrs_addr(ap=ap, region=region)
        masked = offset & REMAP_OFFSET_MASK
        await self._wr(addr, masked & 0xFFFF_FFFF)
        await self._wr(addr + 4, (masked >> 32) & 0xFFFF_FFFF)

    async def offset_value_walk(self, *, ap: bool) -> int:
        """Walk REGION_ATTRS.offset on every region of one output-remap table.

        No beat is issued into the aperture during the walk, so an offset that
        points nowhere useful steers nothing.
        """
        count = AP_REGIONS if ap else STEE_REGIONS
        writes = 0
        for region in range(count):
            for value in addr_field_walk_values():
                await self.set_offset(ap=ap, region=region, offset=value)
                writes += 2
            # A distinct per-region offset so the table holds sixteen different
            # values at once rather than one value written sixteen times.
            await self.set_offset(
                ap=ap, region=region, offset=(region + 1) << (REMAP_IDX_START + 4)
            )
            writes += 2
        return writes


class SepCovOutboundGate(SepCovFilterBank):
    """One outbound-filter entry opened over the whole outbound target window.

    Every outbound beat in these tests lands in ``OUTBOUND_TARGET_BASE`` plus at
    most ``OUTBOUND_TARGET_SPAN``, so one allow window covers the traffic and no
    other entry needs to be enabled.
    """

    _DRIVER_TAG = "COVOUTGATE"
    GATE_ENTRY = 0

    async def open_target_window(self) -> None:
        await self.disable_all(inbound=False)
        await self.write_window(
            inbound=False,
            entry=self.GATE_ENTRY,
            start=OUTBOUND_TARGET_BASE,
            end=OUTBOUND_TARGET_BASE + OUTBOUND_TARGET_SPAN,
        )
        await self.write_config(
            inbound=False,
            entry=self.GATE_ENTRY,
            word=filter_config_word(entry_enabled=True, src_id=0),
        )


class SepCovDma(SepAxiRegDriver):
    """CPU-LSU driver over the Secure DMA descriptor CSRs.

    The register order mirrors ``dv/fw/tests/dma_basic_test/dma_basic_test.c``
    ``dma_run_asid``: address pair, ASID, width, sizes, per-side config, then
    CONTROL with GO. A DMA-mastered beat crosses ``axi_window_remap`` on the DMA
    path, which is the logic this driver exists to reach.
    """

    _DRIVER_TAG = "COVDMA"
    POLL_READS = 400

    async def read32(self, addr: int) -> int:
        """One 32-bit CPU-LSU register read."""
        return await self._rd(addr)

    async def enable_full_range(self) -> None:
        await self._wr(DMA_RANGE_BASE, 0)
        await self._wr(DMA_RANGE_LIMIT, 0xFFFF_FFFF)
        await self._wr(DMA_RANGE_VALID, 1)

    async def clear_status(self) -> None:
        """W1C the sticky STATUS bits so the next transfer starts from idle."""
        await self._wr(DMA_STATUS, DMA_STATUS_DONE | DMA_STATUS_ERROR | DMA_STATUS_CHUNK_DONE)

    async def run_copy(self, *, src: int, dst: int, nbytes: int) -> int:
        """Start one single-chunk 4-byte-wide incrementing copy and poll STATUS.

        The poll is bounded. A transfer that never completes returns the last
        STATUS the caller can log, rather than wedging the run; this driver
        grades nothing either way.
        """
        await self._wr(DMA_SRC_LO, src & 0xFFFF_FFFF)
        await self._wr(DMA_SRC_HI, 0)
        await self._wr(DMA_DST_LO, dst & 0xFFFF_FFFF)
        await self._wr(DMA_DST_HI, 0)
        await self._wr(DMA_ASID, DMA_ASID_BOTH_OT)
        await self._wr(DMA_WIDTH, DMA_WIDTH_4B)
        await self._wr(DMA_TOTAL_SIZE, nbytes)
        await self._wr(DMA_CHUNK_SIZE, nbytes)
        await self._wr(DMA_SRC_CONFIG, DMA_SRC_INCREMENT)
        await self._wr(DMA_DST_CONFIG, DMA_DST_INCREMENT)
        await self._wr(DMA_CONTROL, DMA_CTRL_GO | DMA_CTRL_INITIAL)
        status = 0
        for _ in range(self.POLL_READS):
            status = await self._rd(DMA_STATUS)
            if status & (DMA_STATUS_DONE | DMA_STATUS_ERROR):
                break
        return status


def cov_read_seq(
    addr: int,
    *,
    length: int = 4,
    size: int | None = 2,
    burst: int | None = None,
    axi_id: int = 0,
    user: int = 0,
    allow_error: bool = False,
) -> SepAxiAccessSeq:
    """One read for a coverage sweep, on whichever sequencer the caller starts."""
    return SepAxiAccessSeq(
        "cov_rd",
        op=SepAxiOp.READ,
        addr=addr,
        length=length,
        size=size,
        burst=burst,
        axi_id=axi_id,
        user=user,
        allow_error=allow_error,
    )


def cov_write_seq(
    addr: int,
    wdata: int,
    *,
    length: int = 4,
    size: int | None = 2,
    burst: int | None = None,
    axi_id: int = 0,
    user: int = 0,
    allow_error: bool = False,
) -> SepAxiAccessSeq:
    """One write for a coverage sweep, on whichever sequencer the caller starts."""
    return SepAxiAccessSeq(
        "cov_wr",
        op=SepAxiOp.WRITE,
        addr=addr,
        wdata=wdata,
        length=length,
        size=size,
        burst=burst,
        axi_id=axi_id,
        user=user,
        allow_error=allow_error,
        allow_unverified_write_resp=allow_error,
    )


def walking_data(nbytes: int, bit: int, *, invert: bool = False) -> int:
    """A walking-one (or walking-zero) payload of ``nbytes`` bytes."""
    width = nbytes * 8
    value = 1 << (bit % width)
    return (~value & ((1 << width) - 1)) if invert else value


def _selftest() -> None:
    assert ADDR_FIELD_MASK == 0x00FF_FFFF_FFFF_F000
    src = SepCovAliasRemap.src_page(3)
    dst = SepCovAliasRemap.dst_page(3)
    offset = SepCovAliasRemap.offset_for(src, dst)
    addend = (offset >> PAGE_SHIFT) & ((1 << (56 - PAGE_SHIFT)) - 1)
    assert (((src >> PAGE_SHIFT) + addend) << PAGE_SHIFT) & 0xFFFF_FFFF == dst
    assert SepCovOutputRemap.remapped_addr(OUTBOUND_TARGET_BASE, 0x40) == (
        OUTBOUND_TARGET_BASE | 0x40
    )
    assert walking_data(4, 0) == 1
    assert walking_data(4, 0, invert=True) == 0xFFFF_FFFE
    assert AP_OUTPUT_REMAP_CTRL_0.offset("REGION_REGION_ATTRS") == REMAP_ATTRS
    assert ALIAS_END > ALIAS_START


_selftest()
