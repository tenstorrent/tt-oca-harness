# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD + selector bit 17 + BL1 demotion flag -> DEMOTE_1 demoted and locked.

Outcome **O2a** of the [C15] decision table in
``rom_fw/sep_demotion_decision_base.py``, which is where the mechanism, the collapse
map and the disclosed gaps are written out once. Read that first.

This is the row where the manifest actually decides. ``selector_bits`` bit 17 is set,
so ``rom_main.c`` takes the first arm and copies
``usage_constraints.flags`` bit 0 into ``demotion_reg``;
``flag_args`` bit 0 is clear, so ``BL2_DEMOTE_DEC=0``; and ``lock_demotion`` keeps its
initialiser, so DEMOTE_1 is written **demoted and locked** and DEMOTE_2 is
never written at all. It is the exact complement of the PROD_END member on the
register channel:

  ==============================  ==========  ==========  ==========  ==========
  testcase                        DEMOTE_1    DEMOTE_1    DEMOTE_2    DEMOTE_2
                                  demote      lock        demote      lock
  ==============================  ==========  ==========  ==========  ==========
  ``..._auth_flag_0_prod_end``    0           1           0           **1**
  this one                        **1**       1           0           **0**
  ==============================  ==========  ==========  ==========  ==========

**``+SECURE_BOOT_DIS`` DRIVES TWO SURFACES AND BOTH ARE PORTED.** The reference's
plusarg sets ``primary.manifest.boot_arguments.secure_boot = 0`` **and** burns the
``sboot_dis`` fuse, constrained to equal the plusarg. Both are ported here: the eFuse
preload burns SBOOT_DIS, and the manifest is mutated on both of the fields the
packer would have changed --

  * ``flag_args`` bit 30 (``FLAG_ARGS_BIT_SECURE_BOOT``) cleared. This is the field
    ``secure_boot_enabled`` reads at ``manifest_load.c``, and it sits OUTSIDE the
    TBS (``manifest.h``), so clearing it needs no re-hash;
  * ``signature_type`` set to ``NO_SIGNATURE`` (0), because the packer forces exactly
    that whenever a config sets ``secure_boot: 0``
    (``bootrom/prod/tools/tt-boot-manifest/src/manifest_signing.py:43-45``, value from
    ``pack_images_constants.py``). The reference's primary manifest is therefore
    genuinely UNSIGNED, and this port reproduces that rather than running a signed
    image with one flag cleared.

**AND THE TWO SURFACES ARE COUPLED, WHICH IS WHY THE PORT IS NOT VACUOUS.** With
``signature_type = 0`` the manifest can only boot because ``sboot_dis`` is burned:
``secure_boot_enabled`` short-circuits on the fuse at ``manifest_load.c`` BEFORE
the PROD rule. If the fuse were ever dropped from the preload, PROD
would enforce secure boot, the unsigned primary would be refused at
``BAD_SIG_TYPE=0x00000000`` (``manifest_crypto.c``) and the ROM would fail
over to the signed backup -- which carries no selector bit and would produce outcome
O5 under this testcase's name. Both ``BAD_SIG_TYPE=`` and the backup source are
forbidden, and ``FUSE: SBOOT_DIS: 1`` is required, so that substitution fails loudly
instead of passing.

The primary is left with its stale dev0 signature bytes rather than a blank field.
That differs from the reference, whose packer emits an empty signature: it is inert
here because ``validate_signature`` is never called at
all on this path, and leaving a syntactically complete signature in place makes the
image the HARDER case for anything that might later examine the field.

The BACKUP is re-signed and stays fully valid. Only its ``life_cycle_states`` is
narrowed, so it remains a genuinely bootable slot -- which is what makes the
forbidden backup read and the device-side check meaningful rather than trivially
satisfied by an unusable backup.

**THE LIFECYCLE DECODE IS ASSERTED, NOT ASSUMED.** Both slots' ``life_cycle_states``
are narrowed from the shipped 0x7 to 0x2 -- PROD only -- exactly as the reference
does (``sep_demotion_uid_checker.py``), and ``selector_bits``
bit 16 is already set, so ``manifest_load.c`` refuses the manifest unless the
ROM decoded raw 0x1 as PROD. ``LC=PROD_END`` is forbidden for the complementary
reason the PROD_END member does not forbid ``LC=PROD``: the former string CONTAINS
the latter, so only the longer one can be used as a discriminator.

No ``+sep_crypto_edn_force``: secure boot is off, so the ROM never drives OTBN.
``RSA_VERIFY_START`` is forbidden, so if that ever changed this entry would fail
rather than silently start needing the shortcut.
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

_LC_PROD = "LC=PROD"  # lifecycle.c
_LC_PROD_END = "LC=PROD_END"  # lifecycle.c
_SBOOT_DIS_FUSE = "FUSE: SBOOT_DIS: 1"  # rom_main.c
_SBOOT_OFF = "SBOOT_OFF"  # manifest_load.c
_PLD_HASH_OK = "PLD_HASH_OK"  # manifest_crypto.c
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# lifecycle.h -- the raw 4-bit LC state the preload's 0xE1 encodes.
_LC_RAW_PROD = 0x1
# manifest.h -- LC_STATES_BIT_PROD, the only bit this testcase permits.
_LC_STATES_PROD_ONLY = 1 << mm.LC_STATES_BIT_PROD


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_sel_bit_set_test(sep_demotion_decision_base):
    """PROD, selector bit 17 set, BL1 demotion flag set -> DEMOTE_1 demoted and locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_sboot_dis.toml"
    expected_lc_raw = _LC_RAW_PROD
    expected_sboot_dis = 1

    # rom_main.c lc_write_demotion(demotion_reg=true, lock=true); DEMOTE_2 is
    # never written on this path, observable as lock 0 because the field is
    # write-one-to-set and hardware never clears it.
    expect_demote_1 = (1, 1)
    expect_demote_2 = (0, 0)

    demotion_required = ("BL1_DEMOTE=", "BL2_DEMOTE_DEC=", "DEMOTE_LOCKED")
    demotion_values = ("BL1_DEMOTE=1", "BL2_DEMOTE_DEC=0")

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD,
        _SBOOT_DIS_FUSE,
        _PRIMARY_SRC,
        _SBOOT_OFF,
        _PLD_HASH_OK,
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # BL1_DEMOTE=0 and BL2_DEMOTE_DEC=1 are the values of the neighbouring rows, so
    # forbidding them pins this run to O2a rather than to "some demotion happened".
    # BAD_SIG_TYPE= is the loud failure if the sboot_dis surface is ever dropped.
    # RSA_VERIFY_START / SIG_VALID must not appear: secure boot is off, so a run
    # that verified a signature took a different path from the one under test.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END,
        "BL1_DEMOTE=0",
        "BL2_DEMOTE_DEC=1",
        "LC_USAGE_CONSTRAINT_FAIL",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "CRYPTO_FAIL=",
        "RSA_VERIFY_START",
        "RSA_VERIFY_FAIL",
        "SIG_VALID",
        "CRYPTO_VALIDATE_OK",
        "BAD_SIG_TYPE=",
        "PLD_HASH_FAIL=",
        "PLD_HASH_MISMATCH",
        "ENC_WITHOUT_SBOOT",
    )

    # --- stimulus ----------------------------------------------------------
    def mutate_manifest(self, buf: bytearray) -> None:
        # +SET_SELECTOR_BIT_17 -> usage_constraints.selectors.BL1_demotion
        # (sep_demotion_uid_checker.py).
        mm.set_selector_bit(buf, "primary", mm.SELECTOR_BIT_BL1_DEMOTION, True)
        # +AUTH_FLAG_0 -> usage_constraints.BL1_demotion (:438-440).
        mm.set_usage_flags_bit(buf, "primary", mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION, True)
        # +SECURE_BOOT_DIS, manifest surface 1: the flag secure_boot_enabled reads
        # (manifest_load.c). Outside the TBS, so no re-hash.
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_SECURE_BOOT, False)
        # +SECURE_BOOT_DIS, manifest surface 2: the packer would have forced
        # NO_SIGNATURE (manifest_signing.py), so the reference's primary is
        # unsigned and this one is too.
        mm.set_signature_type(buf, "primary", mm.SIG_TYPE_NO_SIGNATURE)
        # Last in-TBS write. The BACKUP is re-sealed so it stays a fully valid
        # alternative; the PRIMARY is not re-sealed -- it is unsigned by
        # construction, and re-signing it would undo the surface just set.
        narrow_life_cycle_states(self, buf, _LC_STATES_PROD_ONLY, reseal_slots=("backup",))

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
        # The manifest hash must still be valid even though the slot is unsigned:
        # manifest_check_integrity (manifest_load.c) runs regardless of secure
        # boot, so a stale hash would reject the primary before the demotion block.
        mm.verify_layout(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary selector_bits[%d]=1, usage_flags[%d]=1, "
            "flag_args[%d]=0, flag_args[%d]=0 (secure_boot cleared), signature_type="
            "%d (NO_SIGNATURE), life_cycle_states=0x%08x, manifest hash valid. This "
            "is decision-table row O2a, and it can only boot because the SBOOT_DIS "
            "fuse is burned",
            mm.SELECTOR_BIT_BL1_DEMOTION,
            mm.USAGE_CONSTRAINTS_FLAGS_BIT_BL1_DEMOTION,
            mm.FLAG_ARGS_BIT_BL2_DEMOTION,
            mm.FLAG_ARGS_BIT_SECURE_BOOT,
            sigtype,
            lcs,
        )
