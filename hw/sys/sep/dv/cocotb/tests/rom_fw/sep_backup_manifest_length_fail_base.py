# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared base: the backup declares a manifest_length other than the body size; the ROM halts.

The backup is refused with ``OCA_FAIL_MANIFEST_LENGTH`` at every minor version.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_manifest_structural_fail_base import (
    err_marker,
    sep_backup_manifest_structural_fail_base,
)

MANIFEST_ERR_LENGTH = mm.boot_err("OCA_FAIL_MANIFEST_LENGTH")


class sep_backup_manifest_length_fail_base(sep_backup_manifest_structural_fail_base):
    # --- subclass contract -------------------------------------------------
    # manifest_version_minor to declare; every minor applies the same length rule.
    backup_minor: int = 0
    # manifest_length to declare; must differ from the body size.
    backup_length: int = -1

    backup_defect_marker = err_marker(MANIFEST_ERR_LENGTH)
    expected_error = MANIFEST_ERR_LENGTH
    backup_ordered = ("OCA_BODY=", "MFST_VER=")
    efuse_preload = td.PLAINTEXT_EFUSE

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "backup_length" in cls.__dict__:
            body = fd.assert_consumer_body_size()
            assert 0 <= cls.backup_length <= 0xFFFF_FFFF and cls.backup_length != body, (
                f"{cls.__name__}: backup_length {cls.backup_length} must be a u32 other "
                f"than the body size {body}, or the backup is accepted"
            )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def corrupt_backup(self, buf: bytearray) -> None:
        assert self.backup_length >= 0, f"{type(self).__name__}: set backup_length"
        self._served = fd.plant_manifest_length(
            self.logger, buf, "backup", minor=self.backup_minor, length=self.backup_length
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        fd.assert_served_field(
            self.logger,
            self._flash,
            "backup",
            mm.OFF_VERSION_MAJOR,
            self._served,
            "backup manifest_version_major/minor + manifest_length",
        )
        self.logger.info(
            "CHK-LENGTH-RULE PASS: backup v%d.%d declared manifest_length %d against "
            "body size %d and was refused with %s",
            mm.MANIFEST_MAJOR_VERSION,
            self.backup_minor,
            self.backup_length,
            fd.assert_consumer_body_size(),
            err_marker(MANIFEST_ERR_LENGTH),
        )
