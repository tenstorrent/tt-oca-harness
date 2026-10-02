# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest declares an unsupported major version; the ROM halts.

The primary fails as ``OCA_FAIL_MAGIC``. The backup keeps magic, minor and length valid,
so ``oca_check_format_version`` refuses it before the length check.
"""

from __future__ import annotations

import struct

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_manifest_structural_fail_base import (
    err_marker,
    sep_backup_manifest_structural_fail_base,
)

_MANIFEST_ERR_BAD_VERSION = mm.boot_err("OCA_FAIL_FORMAT_VERSION_MISMATCH")

_BAD_MAJOR_VERSION = mm.MANIFEST_MAJOR_VERSION + 1


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_invalid_test(
    sep_backup_manifest_structural_fail_base
):
    """Backup major version is 2 -> both slots refused -> the ROM halts."""

    backup_defect_marker = err_marker(_MANIFEST_ERR_BAD_VERSION)
    expected_error = _MANIFEST_ERR_BAD_VERSION
    backup_ordered = ("OCA_BODY=", "MFST_VER=")
    efuse_preload = td.PLAINTEXT_EFUSE

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def corrupt_backup(self, buf: bytearray) -> None:
        body = fd.assert_consumer_body_size(buf, "backup")
        before = mm.manifest_version(buf, "backup")
        assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {before[0]}.{before[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the baseline to mutate"
        )
        mm.set_manifest_version(buf, "backup", major=_BAD_MAJOR_VERSION)
        after = mm.manifest_version(buf, "backup")
        assert after == (_BAD_MAJOR_VERSION, 0), (
            f"backup manifest version is {after[0]}.{after[1]} after the write, "
            f"expected {_BAD_MAJOR_VERSION}.0; the mutation did not land"
        )
        self._served = struct.pack("<HHI", _BAD_MAJOR_VERSION, 0, body)
        self.logger.info(
            "CHK-STIMULUS-VERSION: backup manifest_version_major %d -> %d; magic OCAC, "
            "minor 0 and manifest_length %d stay valid",
            before[0],
            after[0],
            body,
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
