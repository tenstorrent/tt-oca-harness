# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest declares an unsupported major version; the ROM halts.

The primary is refused as BAD_MAGIC and the backup as BAD_VERSION, with identifier,
minor version and length held valid so only the major version can fail.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
_MANIFEST_ERR_BAD_VERSION = 0x0003_0003

_BAD_MAJOR_VERSION = 2


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_invalid_test(
        sep_backup_manifest_structural_fail_base):
    """Backup major version is not 1 -> both slots refused -> the ROM halts."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_VERSION:08x}"
    expected_error = _MANIFEST_ERR_BAD_VERSION
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    efuse_preload = EFUSE_PRELOAD
    extra_forbidden = (fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
                       "MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=",
                       "PAYLOAD_HASHED_LEN_BAD=", "TOC_PLEN_MISMATCH=",
                       "NO_BL1_IMAGE")

    def corrupt_backup(self, buf: bytearray) -> None:
        before = mm.manifest_version(buf, "backup")
        assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {before[0]}.{before[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        assert bytes(buf[mm.BACKUP_MANIFEST_OFFSET:
                         mm.BACKUP_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "backup manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            "the version check and the asserted code would be wrong"
        )
        mm.set_manifest_version(buf, "backup", major=_BAD_MAJOR_VERSION)
        after = mm.manifest_version(buf, "backup")
        assert after == (_BAD_MAJOR_VERSION, 0), (
            f"backup manifest version is {after[0]}.{after[1]} after the write, "
            f"expected {_BAD_MAJOR_VERSION}.0; the mutation did not land"
        )
        length = mm.manifest_length(buf, "backup")
        assert length == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused with BAD_LENGTH instead of BAD_VERSION"
        )
        self.logger.info(
            "CHK-STIMULUS-VERSION: backup manifest_version_major %d -> %d, with "
            "minor 0, length %d (== sizeof(manifest_t)) and identifier TBL1 all "
            "left VALID, so the major version is the only field "
            "validate_manifest_header can refuse this slot on",
            before[0], after[0], length,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        assert not any("MANIFEST_HASH_OK" in line for line in console), (
            f"ROM printed MANIFEST_HASH_OK: a slot passed "
            f"validate_manifest_header, so the version rejection under test is not "
            f"what refused it. Console: {console}"
        )
        self.logger.info(
            "CHK-HASH-NOT-REACHED: neither slot reached manifest_check_integrity, "
            "so both were refused inside validate_manifest_header"
        )
