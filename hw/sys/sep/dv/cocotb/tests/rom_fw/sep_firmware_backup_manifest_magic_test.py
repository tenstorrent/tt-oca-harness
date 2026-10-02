# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest magic is not OCAC; the ROM halts.

The primary fails on length, so the terminal ``OCA_FAIL_MAGIC`` identifies the backup.
``oca_peek_manifest()`` refuses the backup before the body read, so it never prints ``OCA_BODY=``.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw import sep_toc_defect as td
from rom_fw.sep_backup_manifest_structural_fail_base import (
    err_marker,
    sep_backup_manifest_structural_fail_base,
)

_MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
_MANIFEST_ERR_LENGTH = mm.boot_err("OCA_FAIL_MANIFEST_LENGTH")

_BAD_MAGIC = b"\x99\x99\x99\x99"


@pyuvm.test()
class sep_firmware_backup_manifest_magic_test(sep_backup_manifest_structural_fail_base):
    """Backup magic is not OCAC -> both slots refused -> the ROM halts."""

    backup_defect_marker = err_marker(_MANIFEST_ERR_BAD_MAGIC)
    expected_error = _MANIFEST_ERR_BAD_MAGIC
    backup_absent = ("OCA_BODY=", "MFST_VER=")
    primary_expected_error = _MANIFEST_ERR_LENGTH
    primary_ordered = ("OCA_BODY=", "MFST_VER=")
    primary_absent = ()
    efuse_preload = td.PLAINTEXT_EFUSE

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def corrupt_primary(self, buf: bytearray) -> None:
        fd.plant_manifest_length(
            self.logger, buf, "primary", minor=0, length=fd.assert_consumer_body_size() - 4
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        base = mm.BACKUP_MANIFEST_OFFSET
        before = bytes(buf[base : base + 4])
        assert before == mm.MANIFEST_MAGIC, (
            f"backup magic is already {before!r}, expected {mm.MANIFEST_MAGIC!r}"
        )
        mm.break_magic(buf, "backup", _BAD_MAGIC)
        self._served = bytes(buf[base : base + 4])
        assert self._served == _BAD_MAGIC, (
            f"backup magic is {self._served!r} after the write, expected {_BAD_MAGIC!r}"
        )
        self.logger.info(
            "CHK-STIMULUS-MAGIC: backup magic %r -> %r; the magic is the slot's only defect",
            before,
            self._served,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        fd.assert_served_field(
            self.logger, self._flash, "backup", mm.OFF_MAGIC, self._served, "backup magic"
        )
