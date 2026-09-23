# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD + selector bit 17 + BL1 demotion flag -> DEMOTE_1 demoted and locked.

The SBOOT_DIS fuse is burned and the primary is unsigned with ``secure_boot``
cleared, so the primary boots only because the fuse disables secure boot.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_LC_PROD = "LC=PROD"
_LC_PROD_END = "LC=PROD_END"
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"
_SBOOT_OFF = "SBOOT_OFF"
_PLD_HASH_OK = "PLD_HASH_OK"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

_LC_RAW_PROD = 0x1
_LC_STATES_PROD_ONLY = 1 << mm.LC_STATES_BIT_PROD


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_sel_bit_set_test(
        sep_demotion_decision_base):
    """PROD, selector bit 17 set, BL1 demotion flag set -> DEMOTE_1 demoted and locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_sboot_dis.toml"
    expected_lc_raw = _LC_RAW_PROD
    expected_sboot_dis = 1

    expect_demote_1 = (1, 1)
    expect_demote_2 = (0, 0)

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=1", "BL2_DEMOTE_DEC=0")

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD, _SBOOT_DIS_FUSE, _PRIMARY_SRC, _SBOOT_OFF, _PLD_HASH_OK,
        "BL1_COPIED", "BL1_JUMP=",
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END, "BL1_DEMOTE=0", "BL2_DEMOTE_DEC=1", "LC_USAGE_CONSTRAINT_FAIL",
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED", "CRYPTO_FAIL=",
        "RSA_VERIFY_START", "RSA_VERIFY_FAIL", "SIG_VALID", "CRYPTO_VALIDATE_OK",
        "BAD_SIG_TYPE=", "PLD_HASH_FAIL=", "PLD_HASH_MISMATCH", "ENC_WITHOUT_SBOOT",
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        mm.set_selector_bit(buf, "primary", mm.SELECTOR_BIT_BL1_DEMOTION, True)
        mm.set_usage_flags_bit(buf, "primary",
                               mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, True)
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_SECURE_BOOT, False)
        mm.set_signature_type(buf, "primary", mm.SIG_TYPE_NO_SIGNATURE)
        # Last in-TBS write; only the backup is re-sealed, the primary stays unsigned.
        narrow_life_cycle_states(self, buf, _LC_STATES_PROD_ONLY,
                                 reseal_slots=("backup",))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        sel = mm.selector_bits(buf, "primary")
        sel_bit = (sel >> mm.SELECTOR_BIT_BL1_DEMOTION) & 1
        flags = mm.usage_flags(buf, "primary")
        auth = (flags >> mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION) & 1
        fa = mm.get_flag_args(buf, "primary")
        bl2 = (fa >> mm.FLAG_ARGS_BIT_BL2_DEMOTION) & 1
        sb = (fa >> mm.FLAG_ARGS_BIT_SECURE_BOOT) & 1
        sigtype = mm.get_signature_type(buf, "primary")
        lcs = mm.life_cycle_states(buf, "primary")
        assert (sel_bit, auth, bl2) == (1, 1, 0), (
            f"primary demotion inputs are selector_bits[17]={sel_bit}, "
            f"usage_flags[0]={auth}, flag_args[0]={bl2}; O2a needs (1, 1, 0). Any "
            f"other triple is a different row of the decision table, and rows O2a "
            f"and O2b differ only in flag_args[0] -- which the ROM echoes as "
            f"BL2_DEMOTE_DEC=, so getting it wrong here would fail on the console "
            f"rather than silently, but the artefact is where the stimulus is proven"
        )
        assert sb == 0, (
            f"primary flag_args bit {mm.FLAG_ARGS_BIT_SECURE_BOOT} is still set "
            f"(flag_args=0x{fa:08x}): the manifest surface of +SECURE_BOOT_DIS did "
            f"not land"
        )
        assert sigtype == mm.SIG_TYPE_NO_SIGNATURE, (
            f"primary signature_type is {sigtype}, expected "
            f"{mm.SIG_TYPE_NO_SIGNATURE} (NO_SIGNATURE): the reference's packer "
            f"forces this whenever secure_boot is 0, so a signed primary would be a "
            f"different image from the one the reference presents"
        )
        assert lcs == _LC_STATES_PROD_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{_LC_STATES_PROD_ONLY:08x} (PROD only)"
        )
        # The ROM checks manifest_hash even with secure boot off; it must stay valid.
        mm.verify_layout(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary selector_bits[%d]=1, usage_flags[%d]=1, "
            "flag_args[%d]=0, flag_args[%d]=0 (secure_boot cleared), signature_type="
            "%d (NO_SIGNATURE), life_cycle_states=0x%08x, manifest hash valid. This "
            "is decision-table row O2a, and it can only boot because the SBOOT_DIS "
            "fuse is burned",
            mm.SELECTOR_BIT_BL1_DEMOTION,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION, mm.FLAG_ARGS_BIT_SECURE_BOOT,
            sigtype, lcs,
        )
