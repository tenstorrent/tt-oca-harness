# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD + BL1_DEMOTION_VALID + ENABLE -> DEMOTE_1 demoted and locked.

Outcome **O2a** of the [S25] decision table in
``rom_fw/sep_demotion_decision_base.py``, which is where the mechanism, the collapse
map and the disclosed gaps are written out once. Read that first.

This is the row where the manifest actually decides. BL1_DEMOTION_VALID is set,
so ``rom_main.c`` takes the first arm and copies
``demotion_control`` BL1_DEMOTION_ENABLE into ``demotion_reg``;
the ``demotion_control`` BL2 request is clear, so ``BL2_DEMOTE_DEC=0``; and ``lock_demotion`` keeps its
initialiser, so DEMOTE_1 is written **demoted and locked**  and DEMOTE_2 is
never written at all. It is the exact complement of the PROD_END member on the
register channel:

  ==============================  ==========  ==========  ==========  ==========
  testcase                        DEMOTE_1    DEMOTE_1    DEMOTE_2    DEMOTE_2
                                  demote      lock        demote      lock
  ==============================  ==========  ==========  ==========  ==========
  ``..._auth_flag_0_prod_end``    0           1           0           **1**
  this one                        **1**       1           0           **0**
  ==============================  ==========  ==========  ==========  ==========

**``+SECURE_BOOT_DIS`` drives two surfaces and both are planted.** It sets
``secure_boot: 0`` **and** burns the ``sboot_dis`` fuse, and the manifest surface
alone is not enough to tell the two apart. Both are planted
here: the eFuse preload burns SBOOT_DIS, and the manifest is mutated on both of the
fields the packer would have changed --

  * ``secure_boot_control`` bit 0 cleared. This is the field
    ``secure_boot_control`` is read at ``secure_boot.c``, and it sits OUTSIDE the
    signed region (``oca_layout.h``), so clearing it needs no re-hash;
  * ``signature_type`` set to ``NO_SIGNATURE`` (0), because the packer forces exactly
    that whenever a config sets ``secure_boot: 0``
    (the packer, value from
    ``pack_images_constants.py``). The primary is therefore genuinely unsigned,
    rather than a signed image with one flag cleared.

**AND THE TWO SURFACES ARE COUPLED, WHICH IS WHY THE PORT IS NOT VACUOUS.** The
unsigned manifest can only boot because ``sboot_dis`` is burned, and the fuse is
only consulted because the manifest asks for nothing: the validator checks the
signed ``secure_boot_control`` request FIRST and no device input downgrades it
(``secure_boot.c``, SEP-ROM-SB-040). So both surfaces are required, and in that
order. If the fuse were dropped from the preload, PROD would enforce secure boot,
the unsigned primary would be refused and the ROM would fail over to the signed
backup -- which asks for no demotion and would produce outcome O5 under this
testcase's name. The backup source is forbidden and ``FUSE: SBOOT_DIS: 1`` is
required, so that substitution fails loudly instead of passing.

The primary's signature, public key and key-select fields are zeroed along with the
enable bit. That is not a nicety: with secure boot off the parser requires the slot to
carry no crypto material at all, and a slot that kept its signature bytes would be
refused as a format violation rather than reaching the demotion decision.

The BACKUP is re-signed and stays fully valid. Only its ``life_cycle_states`` is
narrowed, so it remains a genuinely bootable slot -- which is what makes the
forbidden backup read and the device-side check meaningful rather than trivially
satisfied by an unusable backup.

**THE LIFECYCLE DECODE IS ASSERTED, NOT ASSUMED.** Both slots' ``life_cycle_states``
are narrowed from the shipped 0x7 to 0x2 -- PROD only -- and ``selector_bits``
bit 16 is already set, so ``oca_boot.c`` refuses the manifest unless the
ROM decoded raw 0x1 as PROD. ``LC=PROD_END`` is forbidden for the complementary
reason the PROD_END member does not forbid ``LC=PROD``: the former string CONTAINS
the latter, so only the longer one can be used as a discriminator.

No ``+esrc_noise_force``: secure boot is off, so the ROM never drives OTBN.
``RSA_EXEC`` is forbidden, so if that ever changed this entry would fail
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
_SBOOT_OFF = "SBOOT_OFF"  # rom_main.c
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

# lifecycle.h -- the raw 4-bit LC state the preload's 0xE1 encodes.
_LC_RAW_PROD = 0x1
# The only lifecycle bit this testcase permits.
_LC_STATES_PROD_ONLY = 1 << mm.LIFECYCLE_STATE_BITS["PROD"]


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_sel_bit_set_test(sep_demotion_decision_base):
    """PROD, BL1_DEMOTION_VALID set, ENABLE set -> DEMOTE_1 demoted and locked."""

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
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # BL1_DEMOTE=0 and BL2_DEMOTE_DEC=1 are the values of the neighbouring rows, so
    # forbidding them pins this run to O2a rather than to "some demotion happened".
    # PUBK_ALGO_UNSUPPORTED is the loud failure if the sboot_dis surface is ever dropped.
    # RSA_EXEC / RSA_VERIFY_OK must not appear: secure boot is off, so a run
    # that verified a signature took a different path from the one under test.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END,
        "BL1_DEMOTE=0",
        "BL2_DEMOTE_DEC=1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "RSA_EXEC",
        "RSA_PKCS1_FAIL",
        "RSA_VERIFY_OK",
        "PUBK_ALGO_UNSUPPORTED",
    )

    # --- stimulus ----------------------------------------------------------
    def mutate_manifest(self, buf: bytearray) -> None:
        # +SET_SELECTOR_BIT_17 -> usage_constraints.selectors.BL1_demotion
        # (sep_demotion_uid_checker.py).
        # +SET_SELECTOR_BIT_17 and +AUTH_FLAG_0 together: BL1 demotion specified
        # and requested.
        mm.set_demotion(buf, "primary", bl1_valid=True, bl1_enable=True)
        # +SECURE_BOOT_DIS's manifest surface. One call covers both halves the
        # reference names -- the enforcement request and NO_SIGNATURE -- because
        # an unsigned slot must also carry no signature, key or key-select bytes.
        # Inside the signed region, so it re-hashes.
        mm.clear_secure_boot(buf, "primary")
        # Last in-signed region write. The BACKUP is re-sealed so it stays a fully valid
        # alternative; the PRIMARY is deliberately NOT re-sealed -- it is unsigned by
        # construction, and re-signing it would undo the surface just set.
        narrow_life_cycle_states(self, buf, _LC_STATES_PROD_ONLY, reseal_slots=("backup",))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        dc = mm.demotion_control(buf, "primary")
        sel_bit = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_VALID"]) & 1
        auth = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_ENABLE"]) & 1
        bl2 = ((dc >> mm.DEMOTION_BITS["BL2_DEMOTION_VALID"]) & 1) & (
            (dc >> mm.DEMOTION_BITS["BL2_DEMOTION_ENABLE"]) & 1
        )
        sb = mm.secure_boot_control(buf, "primary") & mm.SECURE_BOOT_ENFORCED_BIT
        sigtype = mm.signature_type(buf, "primary")
        lcs = mm.lifecycle_states(buf, "primary", "chiplet")
        assert (sel_bit, auth, bl2) == (1, 1, 0), (
            f"primary demotion_control=0x{dc:04x} decodes as BL1_VALID={sel_bit}, "
            f"BL1_ENABLE={auth}, BL2 request={bl2}; O2a needs (1, 1, 0). Any other "
            f"triple is a different row of the decision table, and rows O2a and O2b "
            f"differ only in the BL2 request -- which the ROM echoes as "
            f"BL2_DEMOTE_DEC=, so getting it wrong here would fail on the console "
            f"rather than silently, but the artefact is where the stimulus is proven"
        )
        assert sb == 0, (
            f"primary secure_boot_control still asks for enforcement "
            f"(0x{mm.secure_boot_control(buf, 'primary'):02x}): the manifest surface "
            f"of +SECURE_BOOT_DIS did not land, and a signed request outranks the fuse"
        )
        assert sigtype == mm.SIG_TYPE_NO_SIGNATURE, (
            f"primary signature_type is {sigtype}, expected "
            f"{mm.SIG_TYPE_NO_SIGNATURE} (NO_SIGNATURE): the packer forces this "
            f"whenever secure_boot is 0, so a signed primary would be a different "
            f"image from the one this testcase means to present"
        )
        assert lcs == _LC_STATES_PROD_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{_LC_STATES_PROD_ONLY:08x} (PROD only)"
        )
        # The manifest hash must still be valid even though the slot is unsigned:
        # The integrity check runs regardless of secure
        # boot, so a stale hash would reject the primary before the demotion block.
        mm.verify_layout(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary demotion_control=0x%04x (BL1_VALID=1 "
            "BL1_ENABLE=1, no BL2 request), secure_boot_control=0, signature_type=%d "
            "(NO_SIGNATURE), chiplet lifecycle_states=0x%08x, manifest hash valid. "
            "This is decision-table row O2a, and it can only boot because the "
            "SBOOT_DIS fuse is burned",
            dc,
            sigtype,
            lcs,
        )
