# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD with signed OCA secure boot enforced and BL1 valid/disabled -> locked, not demoted.

The primary sets BL1_DEMOTION_VALID and clears BL1_DEMOTION_ENABLE with no BL2
request. The fully verified slot must leave DEMOTE_1 clear and lock it.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    SIGNED_PATH_FORBIDDEN,
    SIGNED_PATH_REQUIRED,
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


@pyuvm.test()
class sep_firmware_demotion_bl1_disable_secure_prod_test(
    _demotion_prod_mixin, sep_demotion_decision_base
):
    """Signed OCA BL1 valid/disabled under PROD locks without demoting."""

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
        _LC_PROD,
        _PRIMARY_SRC,
        *SIGNED_PATH_REQUIRED,
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    # "LC=PROD" is a prefix of "LC=PROD_END", so the longer token must be forbidden.
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _LC_PROD_END,
        _BACKUP_SRC,
        *SIGNED_PATH_FORBIDDEN,
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        assert (self._SEL, self._AUTH, self._BL2) == (1, 0, 0), (
            f"this member plants signed OCA BL1 valid/disabled with no BL2 request, "
            f"but it declares "
            f"(_SEL, _AUTH, _BL2) = ({self._SEL}, {self._AUTH}, {self._BL2}) for "
            f"outcome {self._OUTCOME}. Restore (1, 0, 0)"
        )
        mm.set_demotion(
            buf, "primary", bl1_valid=True, bl1_enable=False, bl2_valid=False, bl2_enable=False
        )
        # Last signed-region write: it re-seals both slots.
        narrow_life_cycle_states(self, buf, LC_STATES_PROD_ONLY, reseal_slots=("primary", "backup"))

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        demotion = mm.demotion_control(buf, "primary")
        sel = (demotion >> mm.DEMOTION_BITS["BL1_DEMOTION_VALID"]) & 1
        auth = (demotion >> mm.DEMOTION_BITS["BL1_DEMOTION_ENABLE"]) & 1
        bl2_valid = (demotion >> mm.DEMOTION_BITS["BL2_DEMOTION_VALID"]) & 1
        bl2_enable = (demotion >> mm.DEMOTION_BITS["BL2_DEMOTION_ENABLE"]) & 1
        bl2 = bl2_valid & bl2_enable
        secure_boot = mm.secure_boot_control(buf, "primary")
        sigtype = mm.signature_type(buf, "primary")
        lcs = mm.lifecycle_states(buf, "primary")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion_control=0x{demotion:04x} decodes as BL1_VALID={sel}, "
            f"BL1_ENABLE={auth}, BL2 request={bl2}; this testcase drives "
            f"({self._SEL}, {self._AUTH}, {self._BL2}) for outcome {self._OUTCOME}. "
            f"Any other triple is a different row of the decision table measured "
            f"under this testcase's name"
        )
        assert secure_boot & (1 << mm.SECURE_BOOT_ENFORCED_BIT), (
            f"primary secure_boot_control is 0x{secure_boot:08x} and does not "
            f"request signed OCA secure boot"
        )
        assert sigtype == mm.SIG_TYPE_RSA_3072, (
            f"primary signature_type is {sigtype}, expected "
            f"{mm.SIG_TYPE_RSA_3072}: PROD refuses an unsigned primary and boots the "
            f"backup, which carries no demotion stimulus"
        )
        assert lcs == LC_STATES_PROD_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{LC_STATES_PROD_ONLY:08x} (PROD only)"
        )
        mm.verify_layout(buf, "primary")
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: outcome %s -- primary demotion_control=0x%04x "
            "(BL1_VALID=%d BL1_ENABLE=%d BL2 request=%d), "
            "secure_boot_control=0x%08x, signature_type=%d (RSA-3072), "
            "life_cycle_states=0x%08x. Forbidden neighbouring values: %s",
            self._OUTCOME,
            demotion,
            sel,
            auth,
            bl2,
            secure_boot,
            sigtype,
            lcs,
            ", ".join(self._VALUE_FORBIDS),
        )
