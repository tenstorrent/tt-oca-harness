# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PROD_END stimulus for the demotion-decision testcases.

At PROD_END the ROM locks both demotion registers without reading the manifest
demotion inputs, so every member expects the same outcome and differs only in stimulus.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_LC_PROD_END = "LC=PROD_END"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

LC_RAW_PROD_END = 0x8
LC_STATES_PROD_END_ONLY = 1 << mm.LC_STATES_BIT_PROD_END

PROD_END_PRELOAD = EFUSE_DIR / "sep_efuse_lc_prod_end.toml"


class sep_demotion_prod_end_base(sep_demotion_decision_base):
    _SEL = 0
    _AUTH = 0
    _BL2 = 0

    efuse_preload = PROD_END_PRELOAD
    expected_lc_raw = LC_RAW_PROD_END
    expected_sboot_dis = 0

    # Only the PROD_END path writes DEMOTE_2, so its lock identifies this outcome.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 1)

    demotion_required = ("DEMOTE: PROD_END lock", "DEMOTE_LOCKED")
    demotion_values = ()

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD_END, _PRIMARY_SRC, "RSA_VERIFY_START", "SIG_VALID",
        "CRYPTO_VALIDATE_OK", "BL1_COPIED", "BL1_JUMP=",
    )
    # PROD_END-only manifest: no LC_USAGE_CONSTRAINT_FAIL proves raw 0x8 decoded as PROD_END.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "LC_USAGE_CONSTRAINT_FAIL", "SBOOT_OFF", "FUSE: SBOOT_DIS: 1", _BACKUP_SRC,
        "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
        "VERSION_ROLLBACK", "KEY_REVOKED", "BAD_SIG_TYPE=", "BAD_KEY_SEL",
        "BAD_KEY_IDX", "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY", "PUBK_HASH_MISMATCH",
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        if self._SEL:
            mm.set_selector_bit(buf, "primary", mm.SELECTOR_BIT_BL1_DEMOTION, True)
        if self._AUTH:
            mm.set_usage_flags_bit(buf, "primary",
                                   mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, True)
        if self._BL2:
            mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_BL2_DEMOTION, True)
        # Last in-TBS write: it re-seals both slots over everything planted above.
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_END_ONLY,
                                 reseal_slots=("primary", "backup"))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        # The ROM echoes none of these inputs at PROD_END, so an unplanted input passes silently.
        sel_bits = mm.selector_bits(buf, "primary")
        sel = (sel_bits >> mm.SELECTOR_BIT_BL1_DEMOTION) & 1
        flags = mm.usage_flags(buf, "primary")
        auth = (flags >> mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION) & 1
        bl2 = (mm.get_flag_args(buf, "primary") >> mm.FLAG_ARGS_BIT_BL2_DEMOTION) & 1
        lcs = mm.life_cycle_states(buf, "primary")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion inputs decoded as selector_bits[17]={sel}, "
            f"usage_flags[0]={auth}, flag_args[0]={bl2}; this testcase plants "
            f"({self._SEL}, {self._AUTH}, {self._BL2}). The ROM ignores all three "
            f"at PROD_END, so no console line reflects it and a wrong triple "
            f"would still produce a green run. The other channel that can see it "
            f"is the device record, asserted by _check_stimulus_served()"
        )
        assert lcs == LC_STATES_PROD_END_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{LC_STATES_PROD_END_ONLY:08x} (PROD_END only)"
        )
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary selector_bits[%d]=%d, usage_flags[%d]=%d, "
            "flag_args[%d]=%d, life_cycle_states=0x%08x. rom_main.c:383 must ignore "
            "all three because the part is at PROD_END, and their absence from the "
            "console is asserted by forbidding BL1_DEMOTE= and BL2_DEMOTE_DEC=",
            mm.SELECTOR_BIT_BL1_DEMOTION, sel,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, auth,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION, bl2, lcs,
        )
