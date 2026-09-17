# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Fabric remap + filter CSR-bank R/W breadth.

Combined-per-group CSR sweep over the SEP System-block fabric banks on the CPU-LSU
AXI master (no_cpu): local-master alias-remap, AP/STEE output-remap, and the
inbound/outbound filter config banks. Proves field R/W + 64-bit upper-word access +
the FILTER write-once-set lock (FILTER_CONFIG locked[63]) + the RO data_bus_width
field, with a non-vacuity anchor (a written value differs from reset and is confined
to its field). The alias-remap REGION_ATTRS valid[63] is plain R/W (clearable),
not woset; only the filter locked bit is woset (CHK-VALID-RW vs CHK-WOSET). CSR
layer only -- this entry does not prove live remap translation
or outbound-filter drop.

reference refs: sep_fabric_64bit_regwidth_test (64-bit + locked/valid
woset), sep_outbound_filter_cfg_test (FILTER_CONFIG incl. RO
data_bus_width=3), sep_cpuctrl_misc_regs_test, and the System-block
subset of sep_reg_sanity_test. Distinct from
sep_address_map_test (which only read-touched alias/AP remap for decode
reachability -- no field R/W, no 64-bit upper word, no woset, no filter banks) and
from the inbound-filter rule matrix test (real PROD fuse + external master; this is
+skip_fuse_sense, CSR only).

no_cpu / +skip_fuse_sense.
"""

from __future__ import annotations

import pyuvm
from sep_base_test import sep_base_test
from seq_lib.sep_fabric_csr_bank_seq import (
    ALIAS_END_RESET,
    ALIAS_ATTRS,
    ALIAS_BASE,
    ALIAS_END,
    ALIAS_START,
    ALIAS_STRIDE,
    AP_BASE,
    CLOCK_GATE_UNGATE,
    DBW_LSB,
    DBW_MASK,
    DBW_RO_VAL,
    FILTER_CONFIG,
    FILTER_RW_MASK,
    FILTER_STRIDE,
    INFILT_BASE,
    OUTFILT_BASE,
    REMAP_ATTRS,
    REMAP_STRIDE,
    RESP_OKAY,
    RESP_SLVERR,
    STEE_BASE,
    WOSET_HI_BIT,
    SepFabricCsrBank,
    SepFabricCsrCfg,
)


@pyuvm.test()
class sep_fabric_remap_filter_csr_bank_test(sep_base_test):
    """R/W + 64-bit + woset + RO sweep over the fabric remap/filter CSR banks.

    RANDOMIZED (SepFabricCsrCfg): which alias-remap region (R/W vs valid), AP/STEE
    region, and filter entry (fields vs the permanent woset lock) are exercised, plus
    masked-random field values. The R/W / 64-bit / woset / RO contract is fixed.
    """

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
        # No CHK-ALL summary line: every facet above logs its own PASS, and a plan
        # row keyed on a bare summary string would record coverage with no checker
        # behind it.

    async def _chk_bank_independence(self) -> None:
        """CHK-BANK-INDEP across every entry of the alias and filter banks.

        Runs before the woset leg: locking a filter entry makes its START_ADDR
        read-only, so a locked entry would fail the readback for a reason that is
        not an aliasing defect.
        """
        count, mismatches = await self.fab.bank_independence()
        assert not mismatches, (
            f"CHK-BANK-INDEP FAIL: {len(mismatches)} of {count} bank entries did "
            f"not hold their own value; first: {mismatches[0]}"
        )
        self.logger.info(
            "CHK-BANK-INDEP PASS: %d entries across the alias, inbound-filter and "
            "outbound-filter banks each held their own index-derived pattern",
            count,
        )

    async def _chk_alias_rw_and_nonvac(self) -> None:
        """CHK-ALIAS-RW + CHK-NONVAC on the seeded alias-remap region (no woset touched)."""
        c = self.cfg_csr
        r = ALIAS_BASE + c.alias_rw_region * ALIAS_STRIDE
        start_lo, start_hi = r + ALIAS_START, r + ALIAS_START + 4
        end_lo = r + ALIAS_END
        attrs_lo = r + ALIAS_ATTRS

        # CHK-NONVAC: a written value differs from the reset value (0) and is confined
        # to its field -- the neighbor END_lo stays 0 after we write START_lo (a
        # stuck-at-reset bank fails the readback; a field-bleed fails the neighbor).
        # Read the register BEFORE writing it, so "differs from reset" is an observation
        # of the DUT, not a property of the written value.
        pre = await self.fab.read32(start_lo)
        rb = await self.fab.rw_readback(start_lo, c.start_lo)
        assert rb == c.start_lo, (
            f"alias r{c.alias_rw_region} START_lo R/W: 0x{rb:08x} != 0x{c.start_lo:08x}"
        )
        assert rb != pre, (
            f"alias r{c.alias_rw_region} START_lo readback 0x{rb:08x} equals its "
            f"pre-write value -- the write did not change observable state"
        )
        neighbor = await self.fab.read32(end_lo)
        assert neighbor == ALIAS_END_RESET, (
            f"alias END_lo neighbor changed to 0x{neighbor:08x} after START_lo write "
            f"(not confined); expected its reset value 0x{ALIAS_END_RESET:08x}"
        )
        self.logger.info(
            "CHK-NONVAC PASS: alias r%d START_lo 0x%08x->0x%08x (observed change), "
            "neighbor END_lo 0",
            c.alias_rw_region,
            pre,
            rb,
        )

        # CHK-ALIAS-RW: 64-bit START upper word (addr[55:32]=hi[23:0]; hi[31:24] reserved
        # read 0) + END (4KB-aligned) + ATTRS remap offset.
        rb = await self.fab.rw_readback(start_hi, c.start_hi)
        assert rb == c.start_hi, (
            f"alias START_hi (addr[55:32]) R/W: 0x{rb:08x} != 0x{c.start_hi:08x}"
        )
        rb = await self.fab.rw_readback(end_lo, c.end_lo)
        assert rb == c.end_lo, f"alias END_lo R/W: 0x{rb:08x} != 0x{c.end_lo:08x}"
        rb = await self.fab.rw_readback(attrs_lo, c.attrs_lo)
        assert rb == c.attrs_lo, (
            f"alias ATTRS_lo remap-offset R/W: 0x{rb:08x} != 0x{c.attrs_lo:08x}"
        )
        self.logger.info(
            "CHK-ALIAS-RW PASS: alias r%d REGION_START/END/ATTRS R/W + 64-bit upper word",
            c.alias_rw_region,
        )

    async def _chk_ap_stee_rw(self) -> None:
        """CHK-AP-STEE-RW: AP and STEE output-remap (seeded region) attrs R/W (CSR layer)."""
        c = self.cfg_csr
        for name, base, region, plo, phi in (
            ("AP", AP_BASE, c.ap_region, c.ap_lo, c.ap_hi),
            ("STEE", STEE_BASE, c.stee_region, c.stee_lo, c.stee_hi),
        ):
            r = base + region * REMAP_STRIDE
            lo, hi = r + REMAP_ATTRS, r + REMAP_ATTRS + 4
            rb = await self.fab.rw_readback(lo, plo)  # offset [31:20], 1MB-aligned
            assert rb == plo, f"{name} r{region} remap ATTRS_lo R/W: 0x{rb:08x} != 0x{plo:08x}"
            rb = await self.fab.rw_readback(hi, phi)  # offset [55:32] = hi[23:0]
            assert rb == phi, f"{name} r{region} remap ATTRS_hi R/W: 0x{rb:08x} != 0x{phi:08x}"
        self.logger.info(
            "CHK-AP-STEE-RW PASS: AP r%d + STEE r%d output-remap CSRs R/W (64-bit)",
            c.ap_region,
            c.stee_region,
        )

    async def _chk_filter_cfg_and_ro(self) -> None:
        """CHK-INFILT-CFG + CHK-OUTFILT-CFG + CHK-RO on the seeded fields entry (not locked)."""
        c = self.cfg_csr
        for name, base, entry in (
            ("INFILT", INFILT_BASE, c.infilt_fields_entry),
            ("OUTFILT", OUTFILT_BASE, c.outfilt_fields_entry),
        ):
            cfg_lo = base + entry * FILTER_STRIDE + FILTER_CONFIG
            rb = await self.fab.rw_readback(cfg_lo, c.filter_pattern)
            rw = rb & FILTER_RW_MASK
            assert rw == c.filter_pattern, (
                f"{name} e{entry} FILTER_CONFIG RW fields: read 0x{rw:08x} != 0x{c.filter_pattern:08x}"
            )
            dbw = (rb >> DBW_LSB) & DBW_MASK
            assert dbw == DBW_RO_VAL, f"{name} e{entry} data_bus_width read {dbw} != {DBW_RO_VAL}"
            self.logger.info(
                "CHK-%s-CFG PASS: e%d FILTER_CONFIG RW fields read back exactly "
                "(rd/wr/ns/burst/src_id/group_id)",
                name,
                entry,
            )
            # CHK-RO: data_bus_width ignores a write (stays 3).
            orig, after = await self.fab.ro_probe(cfg_lo, DBW_LSB, 3)
            assert orig == DBW_RO_VAL and after == DBW_RO_VAL, (
                f"{name} e{entry} data_bus_width RO: orig={orig} after-write={after}, expected 3/3"
            )
        self.logger.info("CHK-RO PASS: data_bus_width reads 3 and ignores writes (both filters)")

    async def _chk_woset(self) -> None:
        """CHK-VALID-RW + CHK-WOSET on region/entry 1 (woset locks are permanent -> last).

        Per reference sep_fabric_64bit_regwidth_test, woset is the FILTER FILTER_CONFIG[63]
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
        # this is last). The set sticks AND the clear-attempt write is actively REJECTED
        # with SLVERR by the lock (stronger than a silently-ignored clear) -- bit stays 1.
        for name, base, entry in (
            ("INFILT", INFILT_BASE, cfg.infilt_lock_entry),
            ("OUTFILT", OUTFILT_BASE, cfg.outfilt_lock_entry),
        ):
            cfg_hi = base + entry * FILTER_STRIDE + FILTER_CONFIG + 4
            s, c, r = await self.fab.woset_probe(cfg_hi, WOSET_HI_BIT)
            assert s == 1 and c == 1, (
                f"{name} e{entry} FILTER_CONFIG locked woset: after_set={s} after_clear={c} (want 1/1)"
            )
            assert r == RESP_SLVERR, (
                f"{name} e{entry} locked clear-attempt resp={r}, expected SLVERR (lock rejects)"
            )
            self.logger.info(
                "CHK-WOSET PASS (%s e%d locked): set sticks, clear-attempt rejected with SLVERR "
                "(write-once-set, lock active)",
                name,
                entry,
            )
