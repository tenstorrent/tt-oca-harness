# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Unsupported primary-clear payload-destination scaffold.

The OCA manifest has no payload-destination selector, the ROM stages payloads into SEP
SRAM, and shared payload helpers reject ``smc=True`` and ``stage_in_smc``. This file
defines primary-clear and SMC-window marker geometry.
"""

from __future__ import annotations

import os
from pathlib import Path

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_use_ext_sram_base as ues
from rom_fw.sep_rom_ot_secure_boot_test import sep_rom_ot_secure_boot_test

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_REQUIRED, _FORBIDDEN = ues.smc_markers()


@pyuvm.test()
class sep_firmware_manifest_primary_use_ext_sram_disabled_test(sep_rom_ot_secure_boot_test):
    """Primary-clear and SMC-marker scaffold."""

    efuse_preload = _EFUSE_PRELOAD
    required_markers = (
        sep_rom_ot_secure_boot_test.required_markers
        + _REQUIRED
        + (
            "MANIFEST_OK",
            "BL1_COPIED",
            "BL1_JUMP=",
        )
    )
    forbidden_markers = (
        sep_rom_ot_secure_boot_test.forbidden_markers
        + _FORBIDDEN
        + (
            _BACKUP_SRC,
            "MANIFEST_ERR=",
            "MANIFEST_ALL_FAILED",
        )
    )

    def build_efuse_image(self):
        assert self.efuse_preload and os.path.isfile(self.efuse_preload), (
            f"eFuse preload missing: {self.efuse_preload}"
        )
        image = self.select_efuse_image(default_preload=self.efuse_preload)
        lc = image.lc_raw()
        assert lc == 0x1, f"LC_STATE raw is 0x{lc:x}, expected 0x1 (PROD)"
        assert (image.field_int("SBOOT_DIS") & 0x1) == 0, (
            "SBOOT_DIS is set: the crypto chain would be skipped"
        )
        fd.assert_clean_key_fuses(image)
        return image

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_USE_EXT_SRAM, False)
        ues.assert_stimulus(self.logger, buf, "primary", want_set=False)
        # The scaffold preserves the slot signature after the nominal mutation.
        mm.verify_public_key(buf, "primary")
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        ues.assert_destination(self.logger, console, expect_smc=True)
