# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The PRIMARY's TOC breaks one rule; the backup boots.

The ROM prints no marker for the TOC check, so the primary attempt must end on its
own error line.
"""

from __future__ import annotations

import pyuvm  # noqa: F401
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import (
    DECRYPT_FAILURE_MARKERS,
    PAYLOAD_STAGE_MARKERS,
    err_marker,
)
from rom_fw.sep_primary_fail_backup_boot_base import sep_primary_fail_backup_boot_base


class sep_primary_toc_fail_base(sep_primary_fail_backup_boot_base):
    toc_field: str = ""
    encrypted: bool = False

    primary_expected_rsa_starts = 1
    primary_expected_rsa_oks = 1
    primary_expected_stage = "payload"
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def __init_subclass__(cls, **kwargs) -> None:
        # Derived before the base's import-time contract check reads them.
        assert cls.toc_field in td.DEFECTS, (
            f"{cls.__name__} must declare toc_field as one of {list(td.DEFECTS)}, "
            f"got {cls.toc_field!r}"
        )
        code = td.DEFECTS[cls.toc_field].expected_error
        cls.flash_image = td.image_for(cls.toc_field, cls.encrypted)
        cls.efuse_preload = td.efuse_for(cls.encrypted)
        cls.primary_expected_error = code
        cls.primary_defect_marker = err_marker(code)
        cls.primary_ordered = ("DECRYPT_OK",) if cls.encrypted else ()
        cls.primary_absent = PAYLOAD_STAGE_MARKERS + (
            DECRYPT_FAILURE_MARKERS if cls.encrypted else ("DECRYPT_OK",)
        )
        super().__init_subclass__(**kwargs)

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        td.assert_encryption(buf, self.encrypted, self.flash_image)
        self._payload_offset = pm.payload_base(buf, "primary") - mm.slot_base("primary")
        return super().mutate_flash_image(buf)

    def corrupt_primary(self, buf: bytearray) -> None:
        self._served = td.plant(self.logger, buf, "primary", self.toc_field)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        # Cells that share an error code differ only in the bytes the device served.
        td.assert_served(
            self.logger, flash, "primary", self.toc_field, self._served, self._payload_offset
        )
        self.logger.info(
            "CHK-TOC-RULE PASS: primary %s was refused 0x%08x after its signature "
            "verified%s; the untouched backup booted",
            self.toc_field,
            self.primary_expected_error,
            " and its payload decrypted" if self.encrypted else "",
        )
