# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary asks for SMC SRAM staging; the ROM waits, reads the window, stages there.

The SMC half of the requirement. ``flag_args`` bit 29 is cleared on the primary, so
``manifest_load.c`` must report ``EXT_SRAM_INIT_WAIT``, poll scratch[9] for
``SRAM_INIT``, read the SEP-safe window from scratch[13]/[14], range- and
alignment-check it, and stage the payload at ``smc_sram_base + scratch[13]``.

The bit lives outside the signed TBS region, so clearing it needs no re-seal --
``set_flag_args_bit`` writes it directly and both the manifest hash and the
signature stay valid. That is the same property the ROM relies on to rewrite
``payload_offset`` after staging.

The destination is asserted against the offset the TB published rather than a
constant the test also chose: ``smc_sram_base + 0x20000`` can only be printed by
a ROM that read scratch[13]. ``USING_SEP_SRAM`` is forbidden, so a ROM that
ignored the bit -- the earlier behaviour -- fails here instead of passing.

The window offset clears the status ring buffer at the SMC SRAM base and is
8-byte aligned, so neither of the ROM's two window checks is what this member
exercises; both have their own negative cases.
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
_REQUIRED, _FORBIDDEN = ues.smc_markers()


@pyuvm.test()
class sep_firmware_manifest_primary_use_ext_sram_disabled_test(
        sep_rom_ot_secure_boot_test):
    """use_ext_sram=0 on the primary: payload staged in the SMC SRAM window."""

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
        mm.set_flag_args_bit(buf, "primary", mm.FLAG_ARGS_BIT_USE_EXT_SRAM, False)
        ues.assert_stimulus(self.logger, buf, "primary", want_set=False)
        # The slot must still be cryptographically intact: the claim is that a
        # VALID manifest asking for SMC staging gets it, not that a broken one
        # takes some other path.
        mm.verify_public_key(buf, "primary")
        return buf

    def check_transport(self, console: list[str], flash) -> None:
        ues.assert_destination(self.logger, console, expect_smc=True)
