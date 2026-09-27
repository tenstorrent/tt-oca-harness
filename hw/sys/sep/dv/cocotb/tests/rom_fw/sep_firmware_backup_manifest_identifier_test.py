# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest carries a wrong identifier; the ROM halts.

The primary is refused with BAD_LENGTH, so the terminal BAD_MAGIC code identifies the backup.
The ROM never emits ``SEP_MSG_INVALID_MANIFEST_ID``, so the error codes are the evidence.
"""

from __future__ import annotations

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

_MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
_MANIFEST_ERR_BAD_LENGTH = mm.boot_err("OCA_FAIL_MANIFEST_LENGTH")

_BAD_IDENTIFIER = b"\x99\x99\x99\x99"
# 4-aligned but not sizeof(manifest_t): the exact-length check refuses it, not alignment.
_BAD_LENGTH = mm.MANIFEST_SIZE - 4


@pyuvm.test()
class sep_firmware_backup_manifest_identifier_test(sep_backup_manifest_structural_fail_base):
    """Backup identifier is not OCAC -> both slots refused -> the ROM halts."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_MAGIC:08x}"
    expected_error = _MANIFEST_ERR_BAD_MAGIC
    primary_expected_error = _MANIFEST_ERR_BAD_LENGTH
    efuse_preload = EFUSE_PRELOAD
    extra_forbidden = (
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
        "MANIFEST_HASH_MISMATCH",
        "CRYPTO_FAIL=",
    )

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_length(buf, "primary")
        assert before == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {before}, expected {mm.MANIFEST_SIZE}: "
            f"the shipped image is not the valid baseline this trigger mutates "
            f"away from"
        )
        major, minor = mm.manifest_version(buf, "primary")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {major}.{minor}: BAD_LENGTH is only the "
            f"exact-match branch's verdict while minor is 0"
        )
        mm.set_manifest_length(buf, "primary", _BAD_LENGTH)
        self.logger.info(
            "CHK-STIMULUS-TRIGGER: primary manifest_length %d -> %d (4-aligned, "
            "not sizeof(manifest_t)), so the primary is refused with BAD_LENGTH -- "
            "a different code from the backup's BAD_MAGIC",
            before,
            mm.manifest_length(buf, "primary"),
        )

    def corrupt_backup(self, buf: bytearray) -> None:
        base = mm.BACKUP_MANIFEST_OFFSET
        before = bytes(buf[base : base + 4])
        assert before == mm.MANIFEST_MAGIC, (
            f"backup identifier is already {before!r}, expected {mm.MANIFEST_MAGIC!r}"
        )
        mm.break_magic(buf, "backup", _BAD_IDENTIFIER)
        after = bytes(buf[base : base + 4])
        assert after == _BAD_IDENTIFIER, (
            f"identifier is {after!r} after the write, expected {_BAD_IDENTIFIER!r}"
        )
        self.logger.info(
            "CHK-STIMULUS-IDENTIFIER: backup manifest_identifier %r -> %r, signed region "
            "re-hashed so the identifier is the slot's only defect",
            before,
            after,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        assert not any("MANIFEST_HASH_OK" in line for line in console), (
            f"ROM printed MANIFEST_HASH_OK: a slot passed "
            f"validate_manifest_header, so the structural rejection under test is "
            f"not what refused it. Console: {console}"
        )
        self.logger.info(
            "CHK-HASH-NOT-REACHED: neither slot reached manifest_check_integrity, "
            "so both were refused inside validate_manifest_header"
        )
