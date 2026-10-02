# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario: the primary declares a manifest_length other than the body size; backup boots.

The length check runs after the format-version check and before the manifest hash,
so the refused primary prints ``OCA_BODY=`` and ``MFST_VER=`` before its error.
"""

from __future__ import annotations

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_primary_fail_backup_boot_base import (
    sep_primary_fail_backup_boot_base,
)

MANIFEST_ERR_LENGTH = mm.boot_err("OCA_FAIL_MANIFEST_LENGTH")


class sep_primary_manifest_length_fail_base(sep_primary_fail_backup_boot_base):
    primary_minor: int = 0
    primary_length: int = -1

    primary_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_LENGTH:08x}"
    primary_expected_error = MANIFEST_ERR_LENGTH
    primary_expected_rsa_starts = 0
    primary_ordered = ("OCA_BODY=", "MFST_VER=")
    primary_absent = ("PUBK_SEL=", "PUBK_AUTHORIZED")
    efuse_preload = td.PLAINTEXT_EFUSE
    extra_required = ("BL1_COPIED", "BL1_JUMP=")

    def __init_subclass__(cls, **kwargs) -> None:
        super().__init_subclass__(**kwargs)
        if "primary_length" in cls.__dict__:
            body = fd.assert_consumer_body_size()
            assert 0 <= cls.primary_length <= 0xFFFF_FFFF and cls.primary_length != body, (
                f"{cls.__name__}: primary_length {cls.primary_length} must be a u32 other "
                f"than the body size {body}, or the primary is accepted"
            )

    def corrupt_primary(self, buf: bytearray) -> None:
        assert self.primary_length >= 0, f"{type(self).__name__}: set primary_length"
        self._served = fd.plant_manifest_length(
            self.logger, buf, "primary", minor=self.primary_minor, length=self.primary_length
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)
        fd.assert_served_field(
            self.logger,
            flash,
            "primary",
            mm.OFF_VERSION_MAJOR,
            self._served,
            "primary manifest_version_major/minor + manifest_length",
        )
        self.logger.info(
            "CHK-LENGTH-RULE PASS: primary v%d.%d declared manifest_length %d against "
            "body size %d and was refused with MANIFEST_ERR=0x%08x before RSA_EXEC; "
            "the body-size backup booted",
            mm.MANIFEST_MAJOR_VERSION,
            self.primary_minor,
            self.primary_length,
            fd.assert_consumer_body_size(),
            MANIFEST_ERR_LENGTH,
        )
