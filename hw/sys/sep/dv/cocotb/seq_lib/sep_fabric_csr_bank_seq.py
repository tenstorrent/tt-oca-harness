# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fabric remap + filter CSR-bank driver.

Combined-per-group CSR R/W sweep over the SEP "System block" fabric banks, driven
over the CPU-LSU AXI master (no_cpu). Proves field R/W + 64-bit upper-word access +
the FILTER write-once-set lock (FILTER_CONFIG locked[63]) + the RO data_bus_width
field. The alias-remap REGION_ATTRS valid[63] is plain R/W (clearable),
NOT write-once-set -- only the filter locked bit is woset. CSR layer only --
live remap translation and outbound-filter drop are not claimed here.

All banks need the fabric clocks ungated first (CLOCK_GATE_CTRL);
sep_address_map_seq writes the same value.

Bank map (see `hw/sys/sep/regs/gen/svh/sep_reg.svh`):
  Local-master alias-remap : base 0x10A1_0000, stride 0x20, 16 regions
      REGION_START +0x00 (64b), REGION_END +0x08 (64b, 4KB-aligned),
      REGION_ATTRS +0x10 (64b; remap offset [55:12], cacheable[62], valid[63]=R/W)
  AP   output-remap        : base 0x10A1_0200, stride 0x08; REGION_ATTRS +0x00 (64b)
  STEE output-remap        : base 0x10A1_0300, stride 0x08; REGION_ATTRS +0x00 (64b)
  Inbound  filter          : base 0x10A2_1000, stride 0x20, 16 entries
  Outbound filter          : base 0x10A2_0000, stride 0x20, 32 entries
      FILTER_CONFIG +0x00 (64b): read_allowed[0] write_allowed[1] entry_enabled[4] allow_ns[8]
      data_bus_width[14:12]=RO 3, src_id[19:16] group_id[23:20] allow_burst[24],
      locked[63]=woset.  START_ADDR +0x08, END_ADDR +0x10.
64-bit registers are accessed as two 32-bit words: lo at +0, hi at +4 (the woset
bit [63] is bit 31 of the hi word).
"""

from __future__ import annotations

from env.sep_axi_agent import SepAxiOp
from env.sep_seeded_rng import SepSeededRng
from sep_reg_meta import (
    INBOUND_FILTER_CTRL_0,
    LOCAL_MASTER_ALIAS_REMAP_CTRL_0,
    SEP_CPU_CTRL,
    indexed_block_count,
    sym,
)

from seq_lib.sep_axi_access_seq import SepAxiAccessSeq
from seq_lib.sep_axi_reg_driver import SepAxiRegDriver

# --- fabric clock ungate ------------------------------------------------------
# Derived from the generated SystemRDL export, never hardcoded.
# sep_cpu_ctrl.rdl declares CLOCK_GATE_CTRL as a placeholder with ONE implemented
# bit (pka_cg_enable[0:0], reset 0). There are no per-block gates, so every bank
# below is unconditionally clocked and there is nothing to ungate.
# Writing the full implemented mask keeps this step's CSR write-path coverage.
CLOCK_GATE_CTRL = SEP_CPU_CTRL.addr("CLOCK_GATE_CTRL")
CLOCK_GATE_UNGATE = SEP_CPU_CTRL.mask32("CLOCK_GATE_CTRL")

# --- alias-remap (local master) -----------------------------------------------
ALIAS_BASE = sym("LOCAL_MASTER_ALIAS_REMAP_CTRL_0__REG_MAP_BASE_ADDR")
ALIAS_STRIDE = sym("LOCAL_MASTER_ALIAS_REMAP_CTRL_1__REG_MAP_BASE_ADDR") - ALIAS_BASE
ALIAS_START = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.offset("REGION_REGION_START")
ALIAS_END_RESET = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.reset32("REGION_REGION_END")
ALIAS_END = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.offset("REGION_REGION_END")
ALIAS_ATTRS = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.offset("REGION_REGION_ATTRS")

# --- AP / STEE output-remap ---------------------------------------------------
AP_BASE = sym("AP_OUTPUT_REMAP_CTRL_0__REG_MAP_BASE_ADDR")
STEE_BASE = sym("STEE_OUTPUT_REMAP_CTRL_0__REG_MAP_BASE_ADDR")
REMAP_STRIDE = sym("AP_OUTPUT_REMAP_CTRL_1__REG_MAP_BASE_ADDR") - AP_BASE
REMAP_ATTRS = sym("AP_OUTPUT_REMAP_CTRL_0__REGION_REGION_ATTRS_REG_OFFSET")
# 64-bit; lo [31:20] offset (1MB-aligned), hi [23:0] offset

# --- inbound / outbound filter config -----------------------------------------
INFILT_BASE = sym("INBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR")
OUTFILT_BASE = sym("OUTBOUND_FILTER_CTRL_0__REG_MAP_BASE_ADDR")
FILTER_STRIDE = sym("INBOUND_FILTER_CTRL_1__REG_MAP_BASE_ADDR") - INFILT_BASE
# Per-entry FILTER_* offsets (64-bit START/END as lo/hi 32-bit words). Both SEP
# filters are instances of the same axi_filter_wrap block (hw/sys/sep/doc/fabric.adoc), so
# one per-entry layout describes the inbound and the outbound bank; only the
# inbound block is exported as a register block, and it is the source here.
FILTER_START_ADDR = INBOUND_FILTER_CTRL_0.offset("START_ADDR")
FILTER_END_ADDR = INBOUND_FILTER_CTRL_0.offset("END_ADDR")
FILTER_CONFIG = INBOUND_FILTER_CTRL_0.offset("FILTER_CONFIG")

# remap valid[63] (R/W) and filter locked[63] (woset) both sit in the hi word.
WOSET_HI_BIT = LOCAL_MASTER_ALIAS_REMAP_CTRL_0.field_lsb("REGION_REGION_ATTRS", "valid") - 32

# axi_pkg response codes (a locked filter entry rejects a further write with SLVERR).
RESP_OKAY = 0
RESP_SLVERR = 2

# FILTER_CONFIG field positions (lo word), from the generated bitfield.
F_READ_ALLOWED = INBOUND_FILTER_CTRL_0.field_mask("FILTER_CONFIG", "read_allowed")
F_WRITE_ALLOWED = INBOUND_FILTER_CTRL_0.field_mask("FILTER_CONFIG", "write_allowed")
F_ENTRY_ENABLED = INBOUND_FILTER_CTRL_0.field_mask("FILTER_CONFIG", "entry_enabled")
F_ALLOW_NS = INBOUND_FILTER_CTRL_0.field_mask("FILTER_CONFIG", "allow_ns")
_DBW_MASK = INBOUND_FILTER_CTRL_0.field_mask("FILTER_CONFIG", "data_bus_width")
DBW_LSB = INBOUND_FILTER_CTRL_0.field_lsb("FILTER_CONFIG", "data_bus_width")
DBW_MASK = _DBW_MASK >> DBW_LSB
DBW_RO_VAL = (INBOUND_FILTER_CTRL_0.reset32("FILTER_CONFIG") >> DBW_LSB) & DBW_MASK
F_SRC_ID_LSB = INBOUND_FILTER_CTRL_0.field_lsb("FILTER_CONFIG", "src_id")
F_GROUP_ID_LSB = INBOUND_FILTER_CTRL_0.field_lsb("FILTER_CONFIG", "group_id")
F_ALLOW_BURST = INBOUND_FILTER_CTRL_0.field_mask("FILTER_CONFIG", "allow_burst")

# A representative RW pattern across the writable FILTER_CONFIG fields (NOT touching
# the RO data_bus_width [14:12]). src_id=0x5, group_id=0xA.
FILTER_RW_PATTERN = (
    F_READ_ALLOWED
    | F_WRITE_ALLOWED
    | F_ENTRY_ENABLED
    | F_ALLOW_NS
    | (0x5 << F_SRC_ID_LSB)
    | (0xA << F_GROUP_ID_LSB)
    | F_ALLOW_BURST
)
FILTER_RW_MASK = ~(DBW_MASK << DBW_LSB) & 0xFFFF_FFFF  # compare RW fields, exclude RO

# Bank sizes (entries) for index randomization. Every count comes from the
# register export: a literal that goes short simply never reaches the tail
# entries and still reports a clean pass.
ALIAS_REGIONS = indexed_block_count("LOCAL_MASTER_ALIAS_REMAP_CTRL")
REMAP_REGIONS = indexed_block_count("AP_OUTPUT_REMAP_CTRL")
# Both banks are RDL arrays; take the counts from the export so this sweep and
# the filter-rule sweep cannot disagree about how many entries exist.
INFILT_ENTRIES = indexed_block_count("INBOUND_FILTER_CTRL")
OUTFILT_ENTRIES = indexed_block_count("OUTBOUND_FILTER_CTRL")


class SepFabricCsrCfg:
    """Seeded selection of which region/entry index + which masked R/W patterns the
    sweep exercises.

    Single source of truth: per seed it picks a random alias-remap region for the
    R/W+nonvac walk and a DIFFERENT region for the valid-RW probe; random AP/STEE
    regions; random filter entries for the field R/W and a DIFFERENT entry for the
    woset lock (the lock is permanent, so it must not be the R/W entry). It also
    generates masked-random field values so the data varies while still reading back
    exactly (START 4KB-aligned nonzero, START_hi addr[55:32], END 4KB-aligned, ATTRS remap
    offset [31:12], AP/STEE offset [31:20]/[23:0], filter RW fields excluding the RO
    data_bus_width). The CSR R/W / woset / RO contract is identical for every index.
    Seed + resolved choices logged; regression mode can sweep this via TOML ``reseed = N``.
    """

    def __init__(self, seed: int) -> None:
        self.seed = seed
        rng = SepSeededRng(seed)
        self.alias_rw_region = rng.randrange(ALIAS_REGIONS)
        self.alias_valid_region = rng.choice(
            [i for i in range(ALIAS_REGIONS) if i != self.alias_rw_region]
        )
        self.ap_region = rng.randrange(REMAP_REGIONS)
        self.stee_region = rng.randrange(REMAP_REGIONS)
        self.infilt_fields_entry = rng.randrange(INFILT_ENTRIES)
        self.infilt_lock_entry = rng.choice(
            [i for i in range(INFILT_ENTRIES) if i != self.infilt_fields_entry]
        )
        self.outfilt_fields_entry = rng.randrange(OUTFILT_ENTRIES)
        self.outfilt_lock_entry = rng.choice(
            [i for i in range(OUTFILT_ENTRIES) if i != self.outfilt_fields_entry]
        )
        # Masked-random field values (read back exactly). REGION_START/END are both
        # 4KB-aligned (low 12 bits masked in RTL); START must be nonzero for NONVAC.
        self.start_lo = (
            rng.getrandbits(32) & ~0xFFF & 0xFFFF_FFFF
        ) or 0x1000  # 4KB-aligned, nonzero
        self.start_hi = rng.getrandbits(24)  # addr[55:32]
        self.end_lo = rng.getrandbits(32) & ~0xFFF & 0xFFFF_FFFF  # 4KB-aligned
        self.attrs_lo = rng.getrandbits(32) & 0xFFFF_F000  # remap offset [31:12]
        self.ap_lo = rng.getrandbits(32) & 0xFFF0_0000  # offset [31:20]
        self.ap_hi = rng.getrandbits(24)  # offset [55:32]
        self.stee_lo = rng.getrandbits(32) & 0xFFF0_0000
        self.stee_hi = rng.getrandbits(24)
        # Random legal FILTER_CONFIG RW fields (never the RO data_bus_width [14:12]).
        p = 0
        for b in (F_READ_ALLOWED, F_WRITE_ALLOWED, F_ENTRY_ENABLED, F_ALLOW_NS, F_ALLOW_BURST):
            if rng.getrandbits(1):
                p |= b
        p |= (rng.randrange(16) << F_SRC_ID_LSB) | (rng.randrange(16) << F_GROUP_ID_LSB)
        self.filter_pattern = p & FILTER_RW_MASK

    def summary(self) -> str:
        return (
            f"seed={self.seed} alias_rw=r{self.alias_rw_region} valid=r{self.alias_valid_region} "
            f"ap=r{self.ap_region} stee=r{self.stee_region} "
            f"infilt_fields=e{self.infilt_fields_entry} infilt_lock=e{self.infilt_lock_entry} "
            f"outfilt_fields=e{self.outfilt_fields_entry} outfilt_lock=e{self.outfilt_lock_entry} "
            f"filter_pattern=0x{self.filter_pattern:08x}"
        )


class SepFabricCsrBank(SepAxiRegDriver):
    """Direct-AXI R/W over the fabric remap + filter CSR banks (32-bit beats)."""

    _DRIVER_TAG = "FAB"

    async def ungate_clocks(self) -> int:
        """Ungate the fabric clocks; return the read-back CLOCK_GATE_CTRL."""
        await self._wr(CLOCK_GATE_CTRL, CLOCK_GATE_UNGATE)
        return await self._rd(CLOCK_GATE_CTRL)

    async def rw_readback(self, addr: int, pattern: int, *, mask: int = 0xFFFF_FFFF) -> int:
        """Write ``pattern`` then read back; return (readback & mask)."""
        await self._wr(addr, pattern)
        return await self._rd(addr) & mask

    async def read32(self, addr: int) -> int:
        return await self._rd(addr)

    async def _wr_tolerant(self, addr: int, data: int) -> int:
        """Write tolerating a non-OKAY response; return the AXI resp_code.

        A locked (woset) entry actively REJECTS a subsequent write with SLVERR, so
        the clear-attempt must not raise; the proof is the read-back value.
        """
        seq = SepAxiAccessSeq(
            "fab_wr_tol",
            op=SepAxiOp.WRITE,
            addr=addr,
            wdata=data,
            size=self._AXI_SIZE,
            allow_unverified_write_resp=True,
        )
        await self.test.start_seq(seq)
        return seq.resp_code

    async def bank_field_walk(self) -> tuple[int, list[str]]:
        """Write an index-derived pattern into every R/W word of every bank entry,
        then read all of them back.

        Each filter entry and remap region is an independent rule with its own
        storage, and the per-group sweep writes one entry per group per seed. That
        leaves two defects invisible: a decode that aliases two entries onto one
        register, and a bank that implements fewer entries than the address map
        declares -- both read back correctly on whichever entry the seed picked.

        Deterministic, so the same words are covered on every seed. Patterns are
        masked per word so the readback is exact: the 4 KB-aligned address words
        drop their low bits, FILTER_CONFIG excludes the RO data_bus_width, and no
        pattern sets a lock or valid bit -- bit 31 of every hi word is left clear
        so the filter woset lock stays available to the leg that grades it.
        """
        hi_mask = 0x7FFF_FFFF  # leave bit 31 clear: woset lock / valid live there
        # (bank, base, stride, entries, [(offset, mask)])
        banks = (
            ("alias", ALIAS_BASE, ALIAS_STRIDE, ALIAS_REGIONS, (
                (ALIAS_START, 0xFFFF_F000),
                (ALIAS_START + 4, hi_mask),
                (ALIAS_END, 0xFFFF_F000),
                (ALIAS_ATTRS, 0xFFFF_F000),
                (ALIAS_ATTRS + 4, hi_mask),
            )),
            # FILTER_CONFIG's hi word carries only locked[63], which the woset leg
            # owns, so it has no word here: bits 32..62 hold nothing and a pattern
            # written there reads back zero.
            ("infilt", INFILT_BASE, FILTER_STRIDE, INFILT_ENTRIES, (
                (FILTER_CONFIG, FILTER_RW_MASK),
                (FILTER_START_ADDR, 0xFFFF_F000),
                (FILTER_END_ADDR, 0xFFFF_F000),
            )),
            ("outfilt", OUTFILT_BASE, FILTER_STRIDE, OUTFILT_ENTRIES, (
                (FILTER_CONFIG, FILTER_RW_MASK),
                (FILTER_START_ADDR, 0xFFFF_F000),
                (FILTER_END_ADDR, 0xFFFF_F000),
            )),
        )

        written: list[tuple[str, int, int, int, int, int]] = []
        for bank_no, (name, base, stride, count, words) in enumerate(banks, start=1):
            for idx in range(count):
                entry = base + idx * stride
                for word, (offset, mask) in enumerate(words):
                    addr = entry + offset
                    # Bank number above the index, then the word number, so a
                    # readback names all three. The bank term is what makes the
                    # pattern distinct ACROSS banks: the two filter banks are
                    # instances of one RDL type and share stride and word list,
                    # so without it inbound entry k and outbound entry k would
                    # carry identical patterns and a decode that aliased one onto
                    # the other would still read back what it wrote. The term sits
                    # in bits 21:20, which no word's mask drops.
                    raw = (bank_no << 20) | ((idx + 1) << 16) | ((word + 1) << 12)
                    pattern = raw & mask
                    # Strict write: every word here is R/W and no lock is set
                    # yet, so a non-OKAY response is a defect, not tolerance.
                    await self._wr(addr, pattern)
                    written.append((name, idx, word, addr, pattern, mask))

        # Compare through the same mask the write used. A word's read-only fields
        # return their own value -- FILTER_CONFIG carries data_bus_width as a
        # constant 3 -- so an unmasked compare fails on every filter entry for a
        # reason that is not an aliasing defect. CHK-RO grades those fields.
        mismatches: list[str] = []
        for name, idx, word, addr, pattern, mask in written:
            got = await self.read32(addr)
            if (got & mask) != pattern:
                mismatches.append(
                    f"{name}[{idx}] word{word} @0x{addr:08x} read 0x{got:08x} "
                    f"(masked 0x{got & mask:08x}), wrote 0x{pattern:08x}"
                )
        return len(written), mismatches

    async def woset_probe(self, hi_addr: int, bit: int) -> tuple[int, int, int]:
        """Set ``bit`` in the hi word, then attempt to clear it.

        Returns (after_set, after_clear, clear_resp) -- the bit value after the set,
        the bit value after the clear-attempt, and the AXI resp of the clear write.
          * RW bit:        (1, 0, OKAY=0)        -- clear succeeds.
          * woset (locked): (1, 1, SLVERR=2)     -- set sticks; the lock rejects the
            clear write with SLVERR and the bit stays set.
        """
        cur = await self._rd(hi_addr)
        await self._wr(hi_addr, cur | (1 << bit))  # set (OKAY)
        after_set = (await self._rd(hi_addr) >> bit) & 1
        # Attempt to clear (tolerant: a locked entry rejects this with SLVERR).
        clear_resp = await self._wr_tolerant(
            hi_addr, (cur | (1 << bit)) & ~(1 << bit) & 0xFFFF_FFFF
        )
        after_clear = (await self._rd(hi_addr) >> bit) & 1
        return after_set, after_clear, clear_resp

    async def ro_probe(self, addr: int, lsb: int, width: int) -> tuple[int, int]:
        """Prove a RO field ignores writes. Returns (orig_field, after_write_field)."""
        field_mask = (1 << width) - 1
        orig = (await self._rd(addr) >> lsb) & field_mask
        # Try to write the field to its inverse while leaving other bits as-is-ish.
        cur = await self._rd(addr)
        await self._wr(addr, cur ^ (field_mask << lsb))
        after = (await self._rd(addr) >> lsb) & field_mask
        return orig, after
