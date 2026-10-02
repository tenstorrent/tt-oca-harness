# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared PROD_END stimulus for the demotion-decision testcases.

At PROD_END the ROM reads no manifest demotion input, so every member expects the
same locked outcome; members differ only in the inputs they plant.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw.sep_demotion_decision_base import (
    EFUSE_DIR,
    SIGNED_PATH_FORBIDDEN,
    SIGNED_PATH_REQUIRED,
    narrow_life_cycle_states,
    sep_demotion_decision_base,
)
from rom_fw.sep_rom_ot_dma_boot_test import sep_rom_ot_dma_boot_test

_LC_PROD_END = "LC=PROD_END"
_PRIMARY_SRC = f"MANIFEST_SRC=0x{mm.PRIMARY_MANIFEST_OFFSET:08x}"
_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"

LC_RAW_PROD_END = 0x8
LC_STATES_PROD_END_ONLY = 1 << mm.LIFECYCLE_STATE_BITS["PROD_END"]

PROD_END_PRELOAD = EFUSE_DIR / "sep_efuse_lc_prod_end.toml"


class sep_demotion_prod_end_base(sep_demotion_decision_base):
    _SEL = 0
    _AUTH = 0
    _BL2 = 0

    efuse_preload = PROD_END_PRELOAD
    expected_lc_raw = LC_RAW_PROD_END
    expected_sboot_dis = 0

    expect_demote_1 = (0, 1)
    expect_demote_2 = (0, 1)

    demotion_required = ("DEMOTE: PROD_END lock", "DEMOTE_LOCKED")
    demotion_values = ()

    required_markers = sep_rom_ot_dma_boot_test.required_markers + (
        _LC_PROD_END,
        _PRIMARY_SRC,
        *SIGNED_PATH_REQUIRED,
        "BL1_COPIED",
        "BL1_JUMP=",
    )
    forbidden_markers = sep_rom_ot_dma_boot_test.forbidden_markers + (
        _BACKUP_SRC,
        *SIGNED_PATH_FORBIDDEN,
    )

    def mutate_manifest(self, buf: bytearray) -> None:
        # The BL2 request is the conjunction of its pair, so _BL2 sets both bits.
        mm.set_demotion(
            buf,
            "primary",
            bl1_valid=bool(self._SEL),
            bl1_enable=bool(self._AUTH),
            bl2_valid=bool(self._BL2),
            bl2_enable=bool(self._BL2),
        )
        # PROD_END enforces secure boot, so both slots must be re-sealed after planting.
        narrow_life_cycle_states(
            self, buf, LC_STATES_PROD_END_ONLY, reseal_slots=("primary", "backup")
        )

    def check_manifest_stimulus(self, buf: bytearray) -> None:
        dc = mm.demotion_control(buf, "primary")
        sel = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_VALID"]) & 1
        auth = (dc >> mm.DEMOTION_BITS["BL1_DEMOTION_ENABLE"]) & 1
        bl2 = ((dc >> mm.DEMOTION_BITS["BL2_DEMOTION_VALID"]) & 1) & (
            (dc >> mm.DEMOTION_BITS["BL2_DEMOTION_ENABLE"]) & 1
        )
        lcs = mm.lifecycle_states(buf, "primary", "chiplet")

        assert (sel, auth, bl2) == (self._SEL, self._AUTH, self._BL2), (
            f"primary demotion_control=0x{dc:04x} decodes as BL1_VALID={sel}, "
            f"BL1_ENABLE={auth}, BL2 request={bl2}; this testcase plants "
            f"({self._SEL}, {self._AUTH}, {self._BL2}). The ROM ignores all three "
            f"at PROD_END, so no console line reflects it and a wrong triple "
            f"would still produce a green run. The other channel that can see it "
            f"is the device record, asserted by _check_stimulus_served()"
        )
        assert lcs == LC_STATES_PROD_END_ONLY, (
            f"primary life_cycle_states is 0x{lcs:08x}, expected "
            f"0x{LC_STATES_PROD_END_ONLY:08x} (PROD_END only)"
        )
        self.logger.info(
            "CHK-STIMULUS-DEMOTION: primary demotion_control=0x%04x (BL1_VALID=%d "
            "BL1_ENABLE=%d BL2 request=%d), chiplet lifecycle_states=0x%08x. The "
            "ROM must ignore all of it because the part is at PROD_END, and their "
            "absence from the console is asserted by forbidding BL1_DEMOTE= and "
            "BL2_DEMOTE_DEC=",
            dc,
            sel,
            auth,
            bl2,
            lcs,
        )
