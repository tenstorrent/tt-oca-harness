# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary asks for EXT SRAM staging; the ROM stages there and boots.

The positive half of the requirement. ``flag_args`` bit 29 is set, so
``manifest_load.c`` must stage the payload at ``manifest_base + payload_offset``
inside SEP EXT SRAM and must not enter the SMC arm at all.

The stimulus needs no mutation: the shipped manifests declare
``use_ext_sram: 1``. That makes the run's console indistinguishable from an
ordinary boot unless the destination itself is asserted, which is what
``sep_use_ext_sram_base`` does -- ``USING_SEP_SRAM`` exactly once,
``USING_SMC_SRAM`` never, and ``PAYLOAD_DST=`` at the EXT SRAM address. The
stimulus is asserted too, so a config change that flipped the bit would fail
here rather than silently turn this into a copy of the disabled testcase.

No failover: the primary is valid, so a backup read means the primary was
refused for a reason this testcase does not model.
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
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_BACKUP_SRC = f"MANIFEST_SRC=0x{mm.BACKUP_MANIFEST_OFFSET:08x}"
_REQUIRED, _FORBIDDEN = ues.sep_markers()


@pyuvm.test()
class sep_firmware_manifest_primary_use_ext_sram_enabled_test(
        sep_rom_ot_secure_boot_test):
    """use_ext_sram=1 on the primary: payload staged in SEP EXT SRAM."""

    efuse_preload = _EFUSE_PRELOAD
    required_markers = sep_rom_ot_secure_boot_test.required_markers + _REQUIRED + (
        "MANIFEST_OK", "BL1_COPIED", "BL1_JUMP=",
    )
    forbidden_markers = sep_rom_ot_secure_boot_test.forbidden_markers + _FORBIDDEN + (
        _BACKUP_SRC, "MANIFEST_ERR=", "MANIFEST_ALL_FAILED",
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
        ues.assert_stimulus(self.logger, buf, "primary", want_set=True)
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        ues.assert_destination(self.logger, console, expect_smc=False)
