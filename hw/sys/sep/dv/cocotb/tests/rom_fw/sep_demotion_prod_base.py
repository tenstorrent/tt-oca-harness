# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD-lifecycle base for the demotion-decision tests, with secure boot disabled.

``+SECURE_BOOT_DIS`` is applied as the sboot_dis eFuse plus two primary-manifest writes;
without the fuse PROD refuses the unsigned primary and the backup boots instead.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

# Console tokens; each occurs once in the ROM source, so no forbid below is inert.
_LC_PROD = "LC=PROD"
_LC_PROD_END = "LC=PROD_END"
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"
_SBOOT_OFF = "SBOOT_OFF"
_PLD_HASH_OK = "PLD_HASH_OK"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# Raw 4-bit PROD LC state; the preload encodes it as 0xE1.
LC_RAW_PROD = 0x1
LC_STATES_PROD_ONLY = 1 << mm.LC_STATES_BIT_PROD

PROD_SBOOT_DIS_PRELOAD = EFUSE_DIR / "sep_efuse_lc_prod_sboot_dis.toml"


def apply_secure_boot_dis(test, buf: bytearray, slot: str = "primary") -> None:
    # sep_firmware_demotion_decision_auth_flag_0_prod_sel_bit_set_test repeats these writes inline.
    before_flags = mm.get_flag_args(buf, slot)
    mm.set_flag_args_bit(buf, slot, mm.FLAG_ARGS_BIT_SECURE_BOOT, False)
    mm.set_signature_type(buf, slot, mm.SIG_TYPE_NO_SIGNATURE)
    test.logger.info(
        "CHK-STIMULUS-SBOOT-DIS: %s flag_args 0x%08x -> 0x%08x (bit %d cleared) and "
        "signature_type -> %d (NO_SIGNATURE). The eFuse surface is the preload's, "
        "checked as expected_sboot_dis",
        slot, before_flags, mm.get_flag_args(buf, slot),
        mm.FLAG_ARGS_BIT_SECURE_BOOT, mm.SIG_TYPE_NO_SIGNATURE,
    )


def outcome_for(sel: int, auth: int, bl2: int) -> dict:
    if sel:
        label = "O2" if auth else "O3"
        label += "b" if bl2 else "a"
        return {
            "label": label,
            "required": ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED"),
            "values": (f"BL1_DEMOTE={auth}", f"BL2_DEMOTE_DEC={bl2}"),
            "demote_1": (auth, 1),
            "demote_2": (0, 0),
            "changes": (2, None),
        }
    if bl2:
        return {
            "label": "O4",
            "required": ("DEMOTE: BL2 deferred, unlocked", "BL2_DEMOTE_DEC=",
                         "DEMOTE_NOT_LOCKED"),
            "values": ("BL2_DEMOTE_DEC=1",),
            "demote_1": (0, 0),
            "demote_2": (0, 0),
            # Writes neither register, so only the reset sample is recorded.
            "changes": (1, 1),
        }
    return {
        "label": "O5",
        "required": ("DEMOTE: BL2 deferred, lock non-demoted", "BL2_DEMOTE_DEC=",
                     "DEMOTE_LOCKED"),
        "values": ("BL2_DEMOTE_DEC=0",),
        "demote_1": (0, 1),
        "demote_2": (0, 0),
        "changes": (2, None),
    }


class _demotion_prod_mixin:

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        bits = (cls._SEL, cls._AUTH, cls._BL2)
        if bits == (-1, -1, -1):
            # The base itself; a member missing inputs fails in mutate_manifest() before boot.
            return
        if any(b not in (0, 1) for b in bits):
            raise ValueError(
                f"{cls.__name__}: _SEL/_AUTH/_BL2 must each be 0 or 1, got {bits}"
            )
        want = outcome_for(*bits)
        cls._OUTCOME = want["label"]
        # Catches a copy-paste of expectations between members.
        mismatches = []
        if tuple(cls.demotion_required) != want["required"]:
            mismatches.append(
                f"demotion_required {tuple(cls.demotion_required)} != {want['required']}")
        if tuple(sorted(cls.demotion_values)) != tuple(sorted(want["values"])):
            mismatches.append(
                f"demotion_values {tuple(cls.demotion_values)} != {want['values']}")
        if tuple(cls.expect_demote_1) != want["demote_1"]:
            mismatches.append(
                f"expect_demote_1 {tuple(cls.expect_demote_1)} != {want['demote_1']}")
        if tuple(cls.expect_demote_2) != want["demote_2"]:
            mismatches.append(
                f"expect_demote_2 {tuple(cls.expect_demote_2)} != {want['demote_2']}")
        if (cls.demote_changes_min, cls.demote_changes_max) != want["changes"]:
            mismatches.append(
                f"demote change bounds "
                f"{(cls.demote_changes_min, cls.demote_changes_max)} != "
                f"{want['changes']}")
        if mismatches:
            raise AssertionError(
                f"{cls.__name__} declares (sel, auth, bl2) = {bits}, which "
                f"rom_main.c:388-409 and :431-436 make outcome {want['label']}, but "
                f"its written expectations disagree: " + "; ".join(mismatches) +
                ". Either the declared inputs or the declared outcome is wrong; "
                "outcome_for() in rom_fw/sep_demotion_prod_base.py is the "
                "transcription of the ROM's control flow"
            )
        # With sel clear the base already forbids BL1_DEMOTE=, so only BL2's value needs one.
        value_forbids = [f"BL2_DEMOTE_DEC={1 - cls._BL2}"]
        if cls._SEL:
            value_forbids.append(f"BL1_DEMOTE={1 - cls._AUTH}")
        cls.forbidden_markers = tuple(cls.forbidden_markers) + tuple(value_forbids)
        cls._VALUE_FORBIDS = tuple(value_forbids)


class sep_demotion_prod_base(_demotion_prod_mixin, sep_demotion_decision_base):

    # Subclass contract: the three manifest demotion inputs this member drives.
    _SEL = -1     # usage_constraints.selector_bits bit 17
    _AUTH = -1    # usage_constraints.flags bit 0
    _BL2 = -1     # boot_arguments.flag_args bit 0

    efuse_preload = PROD_SBOOT_DIS_PRELOAD
    expected_lc_raw = LC_RAW_PROD
    expected_sboot_dis = 1

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _SBOOT_DIS_FUSE, _PRIMARY_SRC, _SBOOT_OFF, _PLD_HASH_OK,
        "BL1_COPIED", "BL1_JUMP=",
    )
    # "LC=PROD" is a prefix of "LC=PROD_END", so only the longer string can be forbidden.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END, "LC_USAGE_CONSTRAINT_FAIL", _BACKUP_SRC, "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=", "RSA_VERIFY_START",
        "RSA_VERIFY_FAIL", "SIG_VALID", "CRYPTO_VALIDATE_OK", "BAD_SIG_TYPE=",
        "PLD_HASH_FAIL=", "PLD_HASH_MISMATCH", "ENC_WITHOUT_SBOOT",
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        assert getattr(self, "_OUTCOME", None), (
            f"{type(self).__name__} inherits sep_demotion_prod_base but declares no "
            f"_SEL/_AUTH/_BL2, so no decision-table row was cross-checked for it and "
            f"the stimulus below would drive nothing. Declare all three"
        )
        if self._SEL:
            mm.set_selector_bit(buf, "primary", mm.SELECTOR_BIT_BL1_DEMOTION, True)
        if self._AUTH:
            mm.set_usage_flags_bit(buf, "primary",
                                   mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, True)
        if self._BL2:
            mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_BL2_DEMOTION, True)
        apply_secure_boot_dis(self, buf)
        # Last in-TBS write; the unsigned primary is re-hashed but not re-sealed.
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_ONLY,
                                 reseal_slots=("backup",))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        sel_bits = mm.selector_bits(buf, "primary")
        sel = (sel_bits >> mm.SELECTOR_BIT_BL1_DEMOTION) & 1
        flags = mm.usage_flags(buf, "primary")
        auth = (flags >> mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION) & 1
        fa = mm.get_flag_args(buf, "primary")
        bl2 = (fa >> mm.FLAG_ARGS_BIT_BL2_DEMOTION) & 1
        sb = (fa >> mm.FLAG_ARGS_BIT_SECURE_BOOT) & 1
        sigtype = mm.get_signature_type(buf, "primary")
        lcs = mm.life_cycle_states(buf, "primary")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion inputs decoded as selector_bits[17]={sel}, "
            f"usage_flags[0]={auth}, flag_args[0]={bl2}; this testcase drives "
            f"({self._SEL}, {self._AUTH}, {self._BL2}) for outcome "
            f"{self._OUTCOME}. Any other triple is a different row of the "
            f"decision table measured under this testcase's name"
        )
        assert sb == 0, (
            f"primary flag_args bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} is still set "
            f"(flag_args=0x{fa:08x}): the manifest surface of +SECURE_BOOT_DIS did "
            f"not land, so this run would be measuring a secure-boot-ON path"
        )
        assert sigtype == mm.SIG_TYPE_NO_SIGNATURE, (
            f"primary signature_type is {sigtype}, expected "
            f"{mm.SIG_TYPE_NO_SIGNATURE} (NO_SIGNATURE): the reference's packer "
            f"forces this whenever secure_boot is 0 (manifest_signing.py:43-45), "
            f"so a signed primary would be a different image from the one the "
            f"reference presents"
        )
        assert lcs == LC_STATES_PROD_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{LC_STATES_PROD_ONLY:08x} (PROD only)"
        )
        # The manifest hash is checked even with secure boot off, so it must stay valid.
        mm.verify_layout(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: outcome %s -- primary selector_bits[%d]=%d, "
            "usage_flags[%d]=%d, flag_args[%d]=%d, flag_args[%d]=0 (secure_boot "
            "cleared), signature_type=%d (NO_SIGNATURE), life_cycle_states=0x%08x, "
            "manifest hash valid. This slot can only boot because the SBOOT_DIS "
            "fuse is burned. Forbidden neighbouring values: %s",
            self._OUTCOME, mm.SELECTOR_BIT_BL1_DEMOTION, sel,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, auth,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION, bl2, mm.FLAG_ARGS_BIT_SECURE_BOOT,
            sigtype, lcs, ", ".join(self._VALUE_FORBIDS),
        )
