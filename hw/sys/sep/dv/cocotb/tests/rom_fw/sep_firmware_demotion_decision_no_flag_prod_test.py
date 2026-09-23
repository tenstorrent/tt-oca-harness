# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with secure boot ENFORCED, no demotion input at all -> locked, not demoted.

The primary stays signed, so the decision follows a full RSA-3072 chain. Needs
``+sep_crypto_edn_force``: a real RSA-3072 modexp runs on OTBN.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
# Only the mixin: sep_demotion_prod_base's mutate_manifest would disable secure boot.
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

_EXPECTED_FLAG_ARGS = 1 << mm.FLAG_ARGS_BIT_SECURE_BOOT

# outcome_for() does not cross-check these measurement values.
_MEAS_LOCKED_BL2_ABSENT = "MEAS_DEMOTE=0x00000002"
_MEAS_DEFERRED_UNLOCKED = "MEAS_DEMOTE=0x00000005"
_MEAS_LOCKED_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"

_MEAS_SBOOT_ON = "MEAS_SBOOT=0x00000001"


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_test(
        _demotion_prod_mixin, sep_demotion_decision_base):
    """PROD, secure boot on, no demotion input: DEMOTE_1 locked, not demoted."""

    _SEL = 0
    _AUTH = 0
    _BL2 = 0

    efuse_preload = PROD_PRELOAD
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 0

    demotion_required = ("DEMOTE: BL2 deferred, lock non-demoted", "BL2_DEMOTE_DEC=",
                         "DEMOTE_LOCKED")
    demotion_values = ("BL2_DEMOTE_DEC=0",)

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _PRIMARY_SRC, "RSA_VERIFY_START", "SIG_VALID",
        "CRYPTO_VALIDATE_OK", "PLD_HASH_OK", "MANIFEST_HASH_OK",
        _MEAS_LOCKED_BL2_ABSENT, _MEAS_SBOOT_ON, "BL1_COPIED", "BL1_JUMP=",
    )
    # "LC=PROD" is a prefix of "LC=PROD_END", so only the longer string is forbidden.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END, "LC_USAGE_CONSTRAINT_FAIL", "SBOOT_OFF", "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL", "VERSION_ROLLBACK", "KEY_REVOKED", "BAD_SIG_TYPE=",
        "BAD_KEY_SEL", "BAD_KEY_IDX", "ROM_KEY_EMPTY", "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH", "PLD_HASH_MISMATCH", "PLD_HASH_FAIL=",
        "MANIFEST_HASH_MISMATCH", "ENC_WITHOUT_SBOOT",
        _MEAS_DEFERRED_UNLOCKED, _MEAS_LOCKED_BL2_COUNTED,
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        assert (self._SEL, self._AUTH, self._BL2) == (0, 0, 0), (
            f"this member plants NO demotion input and relies on "
            f"selector_bits[{mm.SELECTOR_BIT_BL1_DEMOTION}], "
            f"usage_constraints.flags[{mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION}] "
            f"and flag_args[{mm.FLAG_ARGS_BIT_BL2_DEMOTION}] all being clear in the "
            f"shipped image, but it declares (_SEL, _AUTH, _BL2) = "
            f"({self._SEL}, {self._AUTH}, {self._BL2}) for outcome {self._OUTCOME}. "
            f"Drive the bits it declares or restore (0, 0, 0)"
        )
        # Re-seal both: an unsigned primary fails over to the backup and still passes.
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_ONLY,
                                 reseal_slots=("primary", "backup"))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
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
            f"(bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} secure_boot KEPT and nothing else "
            f"set). Clearing bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} here would be porting "
            f"a +SECURE_BOOT_DIS this reference entry does not carry"
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
            "secure_boot KEPT), signature_type=%d (RSA-3072), "
            "life_cycle_states=0x%08x. No demotion input is planted by this row. "
            "Forbidden neighbouring values: %s",
            self._OUTCOME, mm.SELECTOR_BIT_BL1_DEMOTION, sel,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, auth, fa,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION, bl2, mm.FLAG_ARGS_BIT_SECURE_BOOT,
            sigtype, lcs, ", ".join(self._VALUE_FORBIDS),
        )
