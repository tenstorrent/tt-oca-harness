# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""PROD_END with the BL1 demotion enable bit set: no demotion, both registers locked.

Needs ``+esrc_noise_force``: PROD_END enforces secure boot, so RSA-3072 runs on OTBN.
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

_LC_PROD_END = "LC=PROD_END"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

_LC_RAW_PROD_END = 0x8
_LC_STATES_PROD_END_ONLY = 1 << mm.LIFECYCLE_STATE_BITS["PROD_END"]


@pyuvm.test()
class sep_firmware_demotion_decision_auth_flag_0_prod_end_test(sep_demotion_decision_base):
    """PROD_END overrides a set BL1 demotion flag: no demotion, both registers locked."""

    efuse_preload = EFUSE_DIR / "sep_efuse_lc_prod_end.toml"
    expected_lc_raw = _LC_RAW_PROD_END
    expected_sboot_dis = 0

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 1)

    demotion_required = ("DEMOTE: PROD_END lock", "DEMOTE_LOCKED")
    demotion_values = ()

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD_END,
        _PRIMARY_SRC,
        "RSA_EXEC",
        "RSA_VERIFY_OK",
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        "SBOOT_OFF",
        "FUSE: SBOOT_DIS: 1",
        _BACKUP_SRC,
        "MANIFEST_ERR=",
        "MANIFEST_ALL_FAILED",
        "MANIFEST_ERR=",
        "RSA_PKCS1_FAIL",
        "PUBK_ALGO_UNSUPPORTED",
        "PUBK_SEL_AMBIGUOUS",
        "PUBK_SLOT_RESERVED",
        "PUBK_SLOT_UNPROVISIONED",
        "PUBK_OTP_EMPTY",
        "PUBK_UNAUTHORIZED",
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        mm.set_demotion(buf, "primary", bl1_valid=False, bl1_enable=True)
        # Plant before narrowing: narrow_life_cycle_states re-seals both slots.
        narrow_life_cycle_states(
            self, buf, _LC_STATES_PROD_END_ONLY, reseal_slots=("primary", "backup")
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        dc = mm.demotion_control(buf, "primary")
        bit = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_ENABLE"]) & 1
        assert bit == 1, (
            f"primary demotion_control is 0x{dc:04x} with the BL1 demotion enable "
            f"bit clear. This testcase's entire content is 'the manifest REQUESTS "
            f"demotion and PROD_END refuses it', and the ROM never echoes this field "
            f"on the PROD_END path, so a "
            f"stimulus that failed to land would produce exactly the log a correct "
            f"run produces"
        )
        sel_bit = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_VALID"]) & 1
        bl2 = ((dc >> mm.DEMOTION_BITS["BL2_DEMOTION_VALID"]) & 1) & (
            (dc >> mm.DEMOTION_BITS["BL2_DEMOTION_ENABLE"]) & 1
        )
        assert sel_bit == 0 and bl2 == 0, (
            f"primary demotion_control=0x{dc:04x} has BL1_VALID={sel_bit} and BL2 "
            f"request={bl2}; both must be 0 so "
            f"this run drives the AUTH flag alone"
        )
        lcs = mm.lifecycle_states(buf, "primary", "chiplet")
        assert lcs == _LC_STATES_PROD_END_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{_LC_STATES_PROD_END_ONLY:08x} (PROD_END only)"
        )
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary demotion_control bit %d = 1 "
            "(BL1 demotion REQUESTED with BL1_VALID clear and no BL2 request), "
            "life_cycle_states = 0x%08x. The ROM must ignore all three because the "
            "part is at PROD_END",
            dc,
            lcs,
        )
