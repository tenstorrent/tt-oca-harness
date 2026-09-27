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

# outcome_for() does not cross-check these measurement values.
_MEAS_LOCKED_BL2_ABSENT = "MEAS_DEMOTE=0x00000002"
_MEAS_DEFERRED_UNLOCKED = "MEAS_DEMOTE=0x00000005"
_MEAS_LOCKED_BL2_COUNTED = "MEAS_DEMOTE=0x00000006"

_MEAS_SBOOT_ON = "MEAS_SBOOT=0x00000001"


@pyuvm.test()
class sep_firmware_demotion_decision_no_flag_prod_test(
    _demotion_prod_mixin, sep_demotion_decision_base
):
    """PROD, secure boot on, no demotion input: DEMOTE_1 locked, not demoted."""

    _SEL = 0
    _AUTH = 0
    _BL2 = 0

    efuse_preload = PROD_PRELOAD
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 0

    demotion_required = (
        "DEMOTE: BL2 deferred, lock non-demoted",
        "BL2_DEMOTE_DEC=",
        "DEMOTE_LOCKED",
    )
    demotion_values = ("BL2_DEMOTE_DEC=0",)

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 0)

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _PRIMARY_SRC,
        "RSA_VERIFY_START",
        "SIG_VALID",
        "CRYPTO_VALIDATE_OK",
        "PLD_HASH_OK",
        "MANIFEST_HASH_OK",
        _MEAS_LOCKED_BL2_ABSENT,
        _MEAS_SBOOT_ON,
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # "LC=PROD" is a prefix of "LC=PROD_END", so only the longer string is forbidden.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END,
        "LC_USAGE_CONSTRAINT_FAIL",
        "SBOOT_OFF",
        "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "CRYPTO_FAIL=",
        "RSA_VERIFY_FAIL",
        "VERSION_ROLLBACK",
        "KEY_REVOKED",
        "BAD_SIG_TYPE=",
        "BAD_KEY_SEL",
        "BAD_KEY_IDX",
        "ROM_KEY_EMPTY",
        "FUSE_KEY_EMPTY",
        "PUBK_HASH_MISMATCH",
        "PLD_HASH_MISMATCH",
        "PLD_HASH_FAIL=",
        "MANIFEST_HASH_MISMATCH",
        "ENC_WITHOUT_SBOOT",
        _MEAS_DEFERRED_UNLOCKED,
        _MEAS_LOCKED_BL2_COUNTED,
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        assert (self._SEL, self._AUTH, self._BL2) == (0, 0, 0), (
            f"this member plants NO demotion input and requires the signed OCA "
            f"demotion_control BL1/BL2 valid and enable bits to remain clear, but "
            f"it declares (_SEL, _AUTH, _BL2) = "
            f"({self._SEL}, {self._AUTH}, {self._BL2}) for outcome {self._OUTCOME}. "
            f"Drive the control it declares or restore (0, 0, 0)"
        )
        for slot in ("primary", "backup"):
            mm.set_demotion(
                buf, slot, bl1_valid=False, bl1_enable=False, bl2_valid=False, bl2_enable=False
            )
        # Re-seal both: an unsigned primary fails over to the backup and still passes.
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_ONLY, reseal_slots=("primary", "backup"))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        demotion = mm.demotion_control(buf, "primary")
        secure_boot = mm.secure_boot_control(buf, "primary")
        sigtype = mm.signature_type(buf, "primary")
        lcs = mm.lifecycle_states(buf, "primary")

        assert demotion == 0, (
            f"primary demotion_control is 0x{demotion:08x}, expected zero: this "
            f"testcase exercises the no-request row of the OCA demotion decision "
            f"table, so any valid or enable bit would be a different row"
        )
        assert secure_boot & (1 << mm.SECURE_BOOT_ENFORCED_BIT), (
            f"primary secure_boot_control is 0x{secure_boot:08x} and does not "
            f"request signed OCA secure boot; PROD must evaluate this row through "
            f"the authenticated path"
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
            "CHK-STIMULUS-DEMOTION: outcome %s -- primary demotion_control=0x%08x "
            "(no BL1 or BL2 request), secure_boot_control=0x%08x, "
            "signature_type=%d (RSA-3072), "
            "life_cycle_states=0x%08x. No demotion input is planted by this row. "
            "Forbidden neighbouring values: %s",
            self._OUTCOME,
            demotion,
            secure_boot,
            sigtype,
            lcs,
            ", ".join(self._VALUE_FORBIDS),
        )
