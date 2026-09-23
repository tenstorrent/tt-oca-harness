# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD, secure boot enforced, selector bit 17 set, BL1 flag clear: DEMOTE_1 locked.

The ROM does not read the skip_SHA256 bit this test also sets, so only the packed
image and the served flash bytes can show it. Needs +sep_crypto_edn_force.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
from rom_fw.sep_demotion_prod_base import (
    LC_RAW_PROD,
    LC_STATES_PROD_ONLY,
    _demotion_prod_mixin,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_LC_PROD = "LC=PROD"
_LC_PROD_END = "LC=PROD_END"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

PROD_PRELOAD = EFUSE_DIR / "sep_efuse_lc_prod.toml"

_EXPECTED_FLAG_ARGS = (1 << mm.FLAG_ARGS_BIT_SECURE_BOOT) | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256)

_MEAS_LOCKED_BL2_ABSENT = "MEAS_DEMOTE=0x00000002"
_MEAS_LOCKED_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"


@pyuvm.test()
class sep_firmware_demotion_decision_unauth_flag_30_prod_sel_bit_set_test(
        _demotion_prod_mixin, sep_demotion_decision_base):
    """PROD, secure boot on, selector set, BL1 flag clear: DEMOTE_1 locked, not demoted."""

    _SEL = 1
    _AUTH = 0
    _BL2 = 0

    efuse_preload = PROD_PRELOAD
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 0

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=0", "BL2_DEMOTE_DEC=0")

    # DEMOTE_2 is written only on the PROD_END arm, so it stays at its reset value.
    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _PRIMARY_SRC, "RSA_VERIFY_START", "SIG_VALID",
        "CRYPTO_VALIDATE_OK", "PLD_HASH_OK", "MANIFEST_HASH_OK",
        _MEAS_LOCKED_BL2_ABSENT, "BL1_COPIED", "BL1_JUMP=",
    )
    # "LC=PROD" is a prefix of "LC=PROD_END", so the longer token must be forbidden.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END, "LC_USAGE_CONSTRAINT_FAIL", "SBOOT_OFF", "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL", "VERSION_ROLLBACK", "KEY_REVOKED", "BAD_SIG_TYPE=",
        "BAD_KEY_SEL", "BAD_KEY_IDX", "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH", "PLD_HASH_MISMATCH", "PLD_HASH_FAIL=",
        "MANIFEST_HASH_MISMATCH", _MEAS_LOCKED_BL2_COUNTED,
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        assert (self._SEL, self._AUTH, self._BL2) == (1, 0, 0), (
            f"this member plants ONLY selector_bits[{mm.SELECTOR_BIT_BL1_DEMOTION}] "
            f"and relies on usage_constraints.flags[0] and flag_args[0] being clear "
            f"in the shipped image, but it declares "
            f"(_SEL, _AUTH, _BL2) = ({self._SEL}, {self._AUTH}, {self._BL2}) for "
            f"outcome {self._OUTCOME}. Drive the other two bits or restore (1, 0, 0)"
        )
        # narrow_life_cycle_states must be the last in-TBS write: it re-seals both slots.
        mm.set_selector_bit(buf, "primary", mm.SELECTOR_BIT_BL1_DEMOTION, True)
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_ONLY,
                                 reseal_slots=("primary", "backup"))
        before = mm.get_flag_args(buf, "primary")
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_SKIP_SHA256, True)
        after = mm.get_flag_args(buf, "primary")
        assert after == before | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256), (
            f"primary flag_args is 0x{after:08x} after the write, expected "
            f"0x{before | (1 << mm.FLAG_ARGS_BIT_SKIP_SHA256):08x}; the mutation did "
            f"not land"
        )
        self.logger.info(
            "CHK-STIMULUS-SKIP-SHA256: primary flag_args 0x%08x -> 0x%08x (bit %d "
            "set). No ROM code reads this bit, so the only "
            "channels that can see it are the packed image and the bytes the flash "
            "device serves", before, after, mm.FLAG_ARGS_BIT_SKIP_SHA256,
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        # The ROM does not echo these inputs, so a failed write still gives a plausible log.
        sel_bits = mm.selector_bits(buf, "primary")
        sel = (sel_bits >> mm.SELECTOR_BIT_BL1_DEMOTION) & 1
        flags = mm.usage_flags(buf, "primary")
        auth = (flags >> mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION) & 1
        fa = mm.get_flag_args(buf, "primary")
        bl2 = (fa >> mm.FLAG_ARGS_BIT_BL2_DEMOTION) & 1
        sigtype = mm.get_signature_type(buf, "primary")
        lcs = mm.life_cycle_states(buf, "primary")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion inputs decoded as selector_bits[17]={sel}, "
            f"usage_flags[0]={auth}, flag_args[0]={bl2}; this testcase drives "
            f"({self._SEL}, {self._AUTH}, {self._BL2}) for outcome {self._OUTCOME}. "
            f"Any other triple is a different row of the decision table measured "
            f"under this testcase's name"
        )
        assert fa == _EXPECTED_FLAG_ARGS, (
            f"primary flag_args is 0x{fa:08x}, expected 0x{_EXPECTED_FLAG_ARGS:08x} "
            f"(secure_boot bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} KEPT, plus skip_SHA256 "
            f"bit {mm.FLAG_ARGS_BIT_SKIP_SHA256}). Clearing bit "
            f"{mm.FLAG_ARGS_BIT_SECURE_BOOT} here would be porting a "
            f"+SECURE_BOOT_DIS this reference entry does not carry"
        )
        assert sigtype == mm.SIG_TYPE_RSA_3072, (
            f"primary signature_type is {sigtype}, expected "
            f"{mm.SIG_TYPE_RSA_3072}: this row's primary must stay genuinely signed, "
            f"because PROD enforces secure boot and an unsigned slot would be refused "
            f"and the boot would come from the backup, which carries no demotion "
            f"stimulus"
        )
        assert lcs == LC_STATES_PROD_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{LC_STATES_PROD_ONLY:08x} (PROD only)"
        )
        mm.verify_layout(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: outcome %s -- primary selector_bits[%d]=%d, "
            "usage_flags[%d]=%d, flag_args=0x%08x (bit %d=%d BL2, bit %d=1 "
            "secure_boot KEPT, bit %d=1 skip_SHA256), signature_type=%d (RSA-3072), "
            "life_cycle_states=0x%08x. Forbidden neighbouring values: %s",
            self._OUTCOME, mm.SELECTOR_BIT_BL1_DEMOTION, sel,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, auth, fa,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION, bl2, mm.FLAG_ARGS_BIT_SECURE_BOOT,
            mm.FLAG_ARGS_BIT_SKIP_SHA256, sigtype, lcs,
            ", ".join(self._VALUE_FORBIDS),
        )
