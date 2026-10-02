# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with BL1_DEMOTION_VALID and ENABLE set: DEMOTE_1 demoted and locked.

Secure boot is off through both the SBOOT_DIS fuse and an unsigned primary; without the
fuse the primary is refused and the backup boots a different outcome.
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
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

_LC_RAW_PROD = 0x1
_LC_STATES_PROD_ONLY = 1 << mm.LIFECYCLE_STATE_BITS["PROD"]


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_sel_bit_set_test(sep_demotion_decision_base):
    """PROD, BL1_DEMOTION_VALID set, ENABLE set -> DEMOTE_1 demoted and locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_sboot_dis.toml"
    expected_lc_raw = _LC_RAW_PROD
    expected_sboot_dis = 1

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

    def mutate_manifest(self, buf: bytearray) -> None:
        mm.set_demotion(buf, "primary", bl1_valid=True, bl1_enable=True)
        mm.clear_secure_boot(buf, "primary")
        # Re-seal only the backup: re-signing the unsigned primary would undo clear_secure_boot.
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
        # The ROM checks the manifest hash even with secure boot off.
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
