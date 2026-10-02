# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The BACKUP's TOC breaks one rule after the primary is refused on its magic word; the ROM halts.

The library prints nothing for a TOC rule, so the backup is graded on its error line
and on the bytes the flash device served.
"""

from __future__ import annotations

import pyuvm  # noqa: F401  (members register themselves with @pyuvm.test)
from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_payload_fail_base import (
    DECRYPT_FAILURE_MARKERS,
    err_marker,
    sep_backup_payload_fail_base,
)


class sep_backup_toc_fail_base(sep_backup_payload_fail_base):
    # A key of sep_toc_defect.DEFECTS.
    toc_field: str = ""
    # Selects the encrypted golden and fuse preload; checked against the image's own flag.
    encrypted: bool = False

    primary_expected_error = td.ERR_BAD_MAGIC

    def __init_subclass__(cls, **kwargs) -> None:
        # Derived before the base's import-time contract check reads them.
        assert cls.toc_field in td.DEFECTS, (
            f"{cls.__name__} must declare toc_field as one of {list(td.DEFECTS)}, "
            f"got {cls.toc_field!r}"
        )
        code = td.DEFECTS[cls.toc_field].expected_error
        cls.flash_image = td.image_for(cls.toc_field, cls.encrypted)
        cls.efuse_preload = td.efuse_for(cls.encrypted)
        cls.expected_error = code
        cls.backup_defect_marker = err_marker(code)
        cls.backup_ordered = ("DECRYPT_OK",) if cls.encrypted else ()
        cls.backup_absent = DECRYPT_FAILURE_MARKERS if cls.encrypted else ("DECRYPT_OK",)
        super().__init_subclass__(**kwargs)

    def mutate_flash_image(self, buf: bytearray) -> bytearray:
        td.assert_encryption(buf, self.encrypted, self.flash_image)
        self._payload_offset = pm.payload_base(buf, "backup") - mm.slot_base("backup")
        return super().mutate_flash_image(buf)

    def corrupt_backup(self, buf: bytearray) -> None:
        self._served = td.plant(self.logger, buf, "backup", self.toc_field)

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        td.assert_served(
            self.logger, self._flash, "backup", self.toc_field, self._served, self._payload_offset
        )
        self.logger.info(
            "CHK-TOC-RULE PASS: backup %s was refused 0x%08x after its signature "
            "verified%s; the run ended terminal",
            self.toc_field,
            self.expected_error,
            " and its payload decrypted" if self.encrypted else "",
        )
