# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fabric remap and filter CSR banks: field R/W, 64-bit upper words, a write-once lock, RO width.

OCAH provenance: ``sep_fabric_64bit_regwidth_test`` checks 64-bit and lock
fields, ``sep_outbound_filter_cfg_test`` checks filter configuration,
``sep_cpuctrl_misc_regs_test`` checks CPU-control registers, and
``sep_reg_sanity_test`` checks the System-block CSR subset.

Combined-per-group CSR sweep over the SEP System-block fabric banks on the CPU-LSU
AXI master (no_cpu): local-master alias-remap, AP/STEE output-remap, and the
inbound/outbound filter config banks. Proves field R/W + 64-bit upper-word access +
the FILTER write-once-set lock (FILTER_CONFIG locked[63]) + the RO data_bus_width
field. Every word the field sweep writes is read first, and the value written
differs from that observed pre-write value, so each readback shows a change of
DUT state on every seed; the alias START_lo write is also confined to its field.
The alias-remap REGION_ATTRS valid[63] is plain R/W (clearable), not woset; only
the filter locked bit is woset (CHK-VALID-RW vs CHK-WOSET). CSR layer only --
this entry does not prove live remap translation or outbound-filter drop.

Distinct from sep_address_map_test (which only reads alias/AP remap words for
decode reachability -- no field R/W, no 64-bit upper word, no woset, no filter
banks) and from sep_fabric_inbound_filter_rule_matrix_test (real PROD fuse +
external master; this is +skip_fuse_sense, CSR only).

Run mode: no_cpu with +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_ATTRS,
    ALIAS_ATTRS_MASK,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_END_MASK,
    ALIAS_END_RESET,
    ALIAS_START,
    ALIAS_START_HI_MASK,
    ALIAS_START_MASK,
    ALIAS_STRIDE,
    AP_BASE,
    CLOCK_GATE_UNGATE,
    DBW_LSB,
    DBW_MASK,
    DBW_RO_VAL,
    FILTER_CFG_LO_FIELDS,
    FILTER_CONFIG,
    FILTER_END_ADDR,
    FILTER_RW_MASK,
    FILTER_START_ADDR,
    FILTER_STRIDE,
    INFILT_BASE,
    OUTFILT_BASE,
    REMAP_ATTRS,
    REMAP_OFFSET_LO_MASK,
    REMAP_RW_HI_MASK,
    REMAP_STRIDE,
    RESP_DECERR,
    RESP_OKAY,
    STEE_BASE,
    WOSET_HI_BIT,
    SepFabricCsrBank,
    SepFabricCsrCfg,
)


@pyuvm.test()
class sep_fabric_remap_filter_csr_bank_test(sep_base_test):
    """Each written word reads back and changes; FILTER_CONFIG.locked is write-once; width is RO 3.

    Randomized (SepFabricCsrCfg): which alias-remap region (R/W vs valid), AP/STEE
    region, and filter entry (fields vs the permanent woset lock) are exercised, plus
    masked-random field values. The R/W / 64-bit / woset / RO contract is fixed.
    """

    required_evidence = (
        "CHK-NONVAC",
        "CHK-ALIAS-RW",
        "CHK-AP-STEE-RW",
        "CHK-INFILT-CFG",
        "CHK-OUTFILT-CFG",
        "CHK-RO",
        "CHK-BANK-INDEP",
        "CHK-VALID-RW",
        "CHK-WOSET",
    )

    async def run_scenario(self) -> None:
        self.cfg_csr = SepFabricCsrCfg(self.random_seed())
        self.logger.info("CSR-bank config: %s", self.cfg_csr.summary())
        await self.bring_up_no_cpu()
        self.fab = SepFabricCsrBank(self)

        gate = await self.fab.ungate_clocks()
        assert gate == CLOCK_GATE_UNGATE, (
            f"CLOCK_GATE_CTRL ungate readback 0x{gate:08x} != 0x{CLOCK_GATE_UNGATE:08x}"
        )
        self.logger.info("fabric clocks ungated (CLOCK_GATE_CTRL=0x%08x)", gate)

        await self._chk_alias_rw_and_nonvac()
        await self._chk_ap_stee_rw()
        await self._chk_filter_cfg_and_ro()
        await self._chk_bank_independence()
        await self._chk_woset()

    async def _chk_bank_independence(self) -> None:
        """CHK-BANK-INDEP over every R/W word of every alias and filter entry.

        Runs before the woset leg: locking a filter entry freezes its words, so a
        locked entry would fail the readback for a reason that is not an aliasing
        defect.
        """
        count, mismatches = await self.fab.bank_field_walk()
        # The expected total is the plan's number, written out: a walk that
        # covered fewer words would otherwise pass on whatever it reached. The
        # entry counts (16 alias, 16 + 32 filter) come from the register export;
        # the words per entry are the walk's own choice of R/W words, not an RDL
        # count: REGION_START lo/hi, REGION_END lo, REGION_ATTRS lo/hi per alias
        # region, and FILTER_CONFIG lo, START_ADDR lo, END_ADDR lo per filter.
        assert count == 224, (
            f"CHK-BANK-INDEP FAIL: the walk covered {count} words, not the 224 "
            f"it plans (16 alias x 5 words + 48 filter entries x 3 words)"
        )
        assert not mismatches, (
            f"CHK-BANK-INDEP FAIL: {len(mismatches)} of {count} bank words did not "
            f"hold their own value; first: {mismatches[0]}"
        )
        self.logger.info(
            "CHK-BANK-INDEP PASS: %d R/W words across all 16 alias regions, 16 "
            "inbound and 32 outbound filter entries each held their own "
            "bank-and-index-derived pattern",
            count,
        )

    async def _rw_word(self, chk: str, label: str, addr: int, pattern: int, mask: int) -> str:
        """Grade one written word: exact readback and a change from the pre-write value.

        ``rw_changed`` reads the word before the write and writes a value that
        differs from it under ``mask``, so a register that ignores the write
        fails here on every seed, including a seed whose pattern equals the
        reset value. Returns "pre->readback" for the caller's PASS line.
        """
        pre, wrote, rb = await self.fab.rw_changed(addr, pattern, mask)
        # Whole-word compare: bits outside ``mask`` are reserved and read 0.
        assert rb == wrote, (
            f"{chk} FAIL: {label} wrote 0x{wrote:08x} (pre-write 0x{pre:08x}), read back 0x{rb:08x}"
        )
        assert rb & mask != pre & mask, (
            f"{chk} FAIL: {label} readback 0x{rb:08x} equals its pre-write value "
            f"0x{pre:08x} under mask 0x{mask:08x} -- the write did not change "
            f"observable state"
        )
        return f"0x{pre:08x}->0x{rb:08x}"

    async def _chk_alias_rw_and_nonvac(self) -> None:
        """CHK-ALIAS-RW + CHK-NONVAC on the seeded alias-remap region (no woset touched)."""
        c = self.cfg_csr
        r = ALIAS_BASE + c.alias_rw_region * ALIAS_STRIDE
        start_lo, start_hi = r + ALIAS_START, r + ALIAS_START + 4
        end_lo = r + ALIAS_END
        attrs_lo = r + ALIAS_ATTRS

        # CHK-NONVAC: the START_lo readback differs from the value the register held
        # before the write (an observation of the DUT, not a property of the written
        # value), and the neighbour END_lo still holds its reset value (a field-bleed
        # fails the neighbour).
        start_lo_obs = await self._rw_word(
            "CHK-NONVAC",
            f"alias r{c.alias_rw_region} START_lo",
            start_lo,
            c.start_lo,
            ALIAS_START_MASK,
        )
        neighbor = await self.fab.read32(end_lo)
        assert neighbor == ALIAS_END_RESET, (
            f"CHK-NONVAC FAIL: alias END_lo neighbor changed to 0x{neighbor:08x} after "
            f"START_lo write (not confined); expected its reset value 0x{ALIAS_END_RESET:08x}"
        )
        self.logger.info(
            "CHK-NONVAC PASS: alias r%d START_lo %s (observed change), neighbor END_lo 0x%08x",
            c.alias_rw_region,
            start_lo_obs,
            neighbor,
        )

        # CHK-ALIAS-RW: 64-bit START upper word (addr[55:32]=hi[23:0]; hi[31:24] reserved
        # read 0) + END (4KB-aligned) + ATTRS remap offset. Each word reads back what
        # was written and differs from its observed pre-write value.
        obs = []
        for label, addr, pattern, mask in (
            ("START_hi", start_hi, c.start_hi, ALIAS_START_HI_MASK),
            ("END_lo", end_lo, c.end_lo, ALIAS_END_MASK),
            ("ATTRS_lo", attrs_lo, c.attrs_lo, ALIAS_ATTRS_MASK),
        ):
            got = await self._rw_word(
                "CHK-ALIAS-RW", f"alias r{c.alias_rw_region} {label}", addr, pattern, mask
            )
            obs.append(f"{label} {got}")
        self.logger.info(
            "CHK-ALIAS-RW PASS: alias r%d REGION_START/END/ATTRS R/W + 64-bit upper word, "
            "each changed from its pre-write value: %s",
            c.alias_rw_region,
            ", ".join(obs),
        )

    async def _chk_ap_stee_rw(self) -> None:
        """CHK-AP-STEE-RW: AP and STEE output-remap (seeded region) attrs R/W (CSR layer)."""
        c = self.cfg_csr
        obs = []
        for name, base, region, plo, phi in (
            ("AP", AP_BASE, c.ap_region, c.ap_lo, c.ap_hi),
            ("STEE", STEE_BASE, c.stee_region, c.stee_lo, c.stee_hi),
        ):
            r = base + region * REMAP_STRIDE
            lo, hi = r + REMAP_ATTRS, r + REMAP_ATTRS + 4
            for label, addr, pattern, mask in (
                ("ATTRS_lo", lo, plo, REMAP_OFFSET_LO_MASK),  # offset lo word
                ("ATTRS_hi", hi, phi, REMAP_RW_HI_MASK),  # offset hi word + valid
            ):
                got = await self._rw_word(
                    "CHK-AP-STEE-RW", f"{name} r{region} remap {label}", addr, pattern, mask
                )
                obs.append(f"{name} {label} {got}")
        self.logger.info(
            "CHK-AP-STEE-RW PASS: AP r%d + STEE r%d output-remap CSRs R/W (64-bit), "
            "each changed from its pre-write value: %s",
            c.ap_region,
            c.stee_region,
            ", ".join(obs),
        )

    async def _chk_filter_cfg_and_ro(self) -> None:
        """CHK-INFILT-CFG + CHK-OUTFILT-CFG + CHK-RO on the seeded fields entry (not locked)."""
        c = self.cfg_csr
        for name, base, entry in (
            ("INFILT", INFILT_BASE, c.infilt_fields_entry),
            ("OUTFILT", OUTFILT_BASE, c.outfilt_fields_entry),
        ):
            cfg_lo = base + entry * FILTER_STRIDE + FILTER_CONFIG
            chk = f"CHK-{name}-CFG"
            pre, wrote, rb = await self.fab.rw_changed(
                cfg_lo, c.filter_pattern, FILTER_CFG_LO_FIELDS
            )
            rw = rb & FILTER_RW_MASK
            assert rw == wrote, (
                f"{chk} FAIL: e{entry} FILTER_CONFIG RW fields: wrote 0x{wrote:08x} "
                f"(pre-write 0x{pre:08x}), read 0x{rw:08x}"
            )
            assert rw != pre & FILTER_RW_MASK, (
                f"{chk} FAIL: e{entry} FILTER_CONFIG RW fields read 0x{rw:08x}, equal to "
                f"the pre-write value -- the write did not change observable state"
            )
            dbw = (rb >> DBW_LSB) & DBW_MASK
            assert dbw == DBW_RO_VAL, (
                f"{chk} FAIL: e{entry} data_bus_width read {dbw} != {DBW_RO_VAL}"
            )
            self.logger.info(
                "%s PASS: e%d FILTER_CONFIG 0x%08x->0x%08x, RW fields "
                "(rd/wr/ns/burst/src_id/group_id) read back the written 0x%08x and "
                "changed from the pre-write value; data_bus_width %d",
                chk,
                entry,
                pre,
                rb,
                wrote,
                dbw,
            )
            # CHK-RO: data_bus_width ignores a write (stays 3).
            orig, after = await self.fab.ro_probe(cfg_lo, DBW_LSB, DBW_MASK.bit_count())
            assert orig == DBW_RO_VAL and after == DBW_RO_VAL, (
                f"CHK-RO FAIL: {name} e{entry} data_bus_width RO: orig={orig} "
                f"after-write={after}, expected 3/3"
            )
        self.logger.info("CHK-RO PASS: data_bus_width reads 3 and ignores writes (both filters)")

    async def _chk_woset(self) -> None:
        """CHK-VALID-RW + CHK-WOSET on region/entry 1 (woset locks are permanent -> last).

        Per filter_ctrl.rdl (FILTER_CONFIG.locked), woset is the FILTER FILTER_CONFIG[63]
        (locked) bit only; the alias-remap REGION_ATTRS valid[63] bit is plain R/W
        (set sticks, clear works), which this test confirms as a distinct contract.
        woset_probe returns (after_set, after_clear): (1,1)=woset, (1,0)=RW.
        """
        # CHK-VALID-RW: alias-remap (seeded valid-region) REGION_ATTRS valid (bit 63 =
        # hi bit 31) is R/W (set->1, then clear succeeds with OKAY -> 0). Distinct region
        # from the R/W walk so neither disturbs the other.
        cfg = self.cfg_csr
        attrs_hi = ALIAS_BASE + cfg.alias_valid_region * ALIAS_STRIDE + ALIAS_ATTRS + 4
        s, c, r = await self.fab.woset_probe(attrs_hi, WOSET_HI_BIT)
        assert s == 1 and c == 0, (
            f"alias r{cfg.alias_valid_region} valid expected R/W: after_set={s} after_clear={c} (want 1/0)"
        )
        assert r == RESP_OKAY, f"alias valid clear write resp={r}, expected OKAY (RW, not locked)"
        self.logger.info(
            "CHK-VALID-RW PASS: alias r%d REGION_ATTRS valid bit is R/W (set->1, clear->0)",
            cfg.alias_valid_region,
        )

        # CHK-WOSET: inbound + outbound filter FILTER_CONFIG[63] locked is write-once-set
        # (seeded lock entry, DISTINCT from the field-R/W entry; the lock is permanent so
        # this is last). The set sticks, the clear-attempt write completes DECERR and the
        # bit stays 1. The bit staying 1 shows the woset storage; the DECERR on the clear
        # write shows the lock steers the hi-word write away. While the lock
        # is set, a write to the FILTER_CONFIG lo word (the R/W rule fields), START_ADDR
        # and END_ADDR also completes DECERR and leaves the word unchanged. Source:
        # filter_ctrl.rdl FILTER_CONFIG.locked and hw/ip/axi_filter/doc/index.adoc
        # ("Locking a Filter Entry").
        # Every locked write runs and is logged before any code is graded, so a
        # wrong code on one register does not hide the response of the others.
        fails: list[str] = []
        for name, base, entry in (
            ("INFILT", INFILT_BASE, cfg.infilt_lock_entry),
            ("OUTFILT", OUTFILT_BASE, cfg.outfilt_lock_entry),
        ):
            entry_base = base + entry * FILTER_STRIDE
            cfg_hi = entry_base + FILTER_CONFIG + 4
            s, c, r = await self.fab.woset_probe(cfg_hi, WOSET_HI_BIT)
            assert s == 1 and c == 1, (
                f"{name} e{entry} FILTER_CONFIG locked woset: after_set={s} after_clear={c} (want 1/1)"
            )
            resps = [("FILTER_CONFIG hi", r)]
            for reg, off, flip in (
                # Flip every writable lo-word field (read_allowed, write_allowed,
                # entry_enabled, allow_ns, src_id, group_id, allow_burst); the RO
                # data_bus_width is outside the mask. An accepted write reads back
                # changed.
                ("FILTER_CONFIG lo", FILTER_CONFIG, FILTER_RW_MASK),
                # Flip 4 KB-aligned address bits: START/END store them for any
                # granule, so an accepted write would read back changed.
                ("START_ADDR", FILTER_START_ADDR, 0x0000_F000),
                ("END_ADDR", FILTER_END_ADDR, 0x0000_F000),
            ):
                before, after, wr = await self.fab.locked_write_probe(entry_base + off, flip)
                self.logger.info(
                    "CHK-WOSET %s e%d locked %s wrote 0x%08x: word 0x%08x -> 0x%08x",
                    name,
                    entry,
                    reg,
                    (before ^ flip) & 0xFFFF_FFFF,
                    before,
                    after,
                )
                resps.append((reg, wr))
                if after != before:
                    fails.append(
                        f"{name} e{entry} locked {reg} moved: 0x{before:08x} -> 0x{after:08x}"
                    )
            for reg, code in resps:
                self.logger.info(
                    "CHK-WOSET %s e%d locked %s write resp=%d (spec DECERR=%d)",
                    name,
                    entry,
                    reg,
                    code,
                    RESP_DECERR,
                )
                if code != RESP_DECERR:
                    fails.append(
                        f"{name} e{entry} locked {reg} write resp={code}, expected DECERR "
                        f"({RESP_DECERR}): a write to a locked entry goes to the AXI error "
                        "subordinate"
                    )
        assert not fails, "CHK-WOSET FAIL: " + "; ".join(fails)
        self.logger.info(
            "CHK-WOSET PASS (INFILT e%d, OUTFILT e%d locked): set sticks; the "
            "FILTER_CONFIG hi clear write completes DECERR; writes to the FILTER_CONFIG "
            "lo word, START_ADDR and END_ADDR complete DECERR and leave the word "
            "unchanged",
            cfg.infilt_lock_entry,
            cfg.outfilt_lock_entry,
        )
