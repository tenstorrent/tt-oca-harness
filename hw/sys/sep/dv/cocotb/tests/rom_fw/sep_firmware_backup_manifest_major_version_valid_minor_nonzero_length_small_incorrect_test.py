# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.1 with a misaligned length; the ROM halts.

Length ``sizeof(manifest_t) + 1`` at minor 1 passes the range rule, so only the
4-byte alignment rule can refuse it. The primary is refused as BAD_MAGIC.
"""

from __future__ import annotations

import struct

import pyuvm
from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

_MANIFEST_ERR_BAD_MAGIC = mm.boot_err("OCA_FAIL_MAGIC")
_MANIFEST_ERR_BAD_LENGTH = mm.boot_err("OCA_FAIL_MANIFEST_LENGTH")

_BACKUP_SMALL_LENGTH = mm.MANIFEST_SIZE + 1
_BACKUP_MINOR = 1

_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_nonzero_length_small_incorrect_test(
    sep_backup_manifest_structural_fail_base
):
    """Backup is v1.1 with length 1185 -> both slots refused -> the ROM halts."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_LENGTH:08x}"
    expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    efuse_preload = EFUSE_PRELOAD
    extra_forbidden = (
        fd.LC_MARKER,
        fd.CHIPLET_MARKER,
        fd.PACKAGE_MARKER,
        "MANIFEST_HASH_MISMATCH",
        "MANIFEST_HASH_OK",
        "CRYPTO_FAIL=",
        "PAYLOAD_OFF_RANGE",
        "PAYLOAD_OFF_ALIGN",
        "PAYLOAD_HASHED_LEN_BAD=",
        "ENC_HASHED_LEN_PARTIAL",
        "PAYLOAD_LEN_RANGE",
        "PAYLOAD_OVERLAPS_MANIFEST",
        "TOC_PLEN_MISMATCH=",
        "NO_BL1_IMAGE",
    )

    def corrupt_backup(self, buf: bytearray) -> None:
        # MANIFEST_MAX_SIZE is a hand-copied mirror of the ROM #define; check they still agree.
        rom_max = fd.assert_rom_manifest_bounds()
        assert rom_max == mm.MANIFEST_MAX_SIZE

        before_len = mm.manifest_length(buf, "backup")
        before_ver = mm.manifest_version(buf, "backup")
        assert before_len == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {before_len}, expected {mm.MANIFEST_SIZE}: "
            f"the shipped image is not the valid baseline this testcase mutates away "
            f"from"
        )
        assert before_ver == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {before_ver[0]}.{before_ver[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0"
        )
        assert (
            bytes(buf[mm.BACKUP_MANIFEST_OFFSET : mm.BACKUP_MANIFEST_OFFSET + 4])
            == mm.MANIFEST_MAGIC
        ), (
            "backup manifest_identifier is not OCAC, so BAD_MAGIC would pre-empt the "
            "length check and the asserted code would be wrong"
        )
        assert _BACKUP_SMALL_LENGTH % 4 != 0, (
            f"the trigger length {_BACKUP_SMALL_LENGTH} is 4-byte aligned, so the "
            f"alignment rule this row names would ACCEPT it and the slot would not "
            f"be refused at all"
        )
        assert mm.MANIFEST_SIZE <= _BACKUP_SMALL_LENGTH <= mm.MANIFEST_MAX_SIZE, (
            f"the trigger length {_BACKUP_SMALL_LENGTH} is outside "
            f"[{mm.MANIFEST_SIZE}, {mm.MANIFEST_MAX_SIZE}], so the range rule would "
            f"refuse it ahead of the alignment check and this row's verdict would "
            f"belong to a different arm"
        )
        assert _BACKUP_MINOR != 0, (
            "the minor version must be non-zero or the exact-match arm, not the "
            "range rule, is what accepts 1185's magnitude -- and the verdict would "
            "then belong to a different testcase"
        )

        mm.set_manifest_version(buf, "backup", minor=_BACKUP_MINOR)
        mm.set_manifest_length(buf, "backup", _BACKUP_SMALL_LENGTH)
        after_ver = mm.manifest_version(buf, "backup")
        after_len = mm.manifest_length(buf, "backup")
        assert after_ver == (mm.MANIFEST_MAJOR_VERSION, _BACKUP_MINOR), (
            f"backup manifest version is {after_ver[0]}.{after_ver[1]} after the "
            f"write, expected {mm.MANIFEST_MAJOR_VERSION}.{_BACKUP_MINOR}; the "
            f"mutation did not land"
        )
        assert after_len == _BACKUP_SMALL_LENGTH, (
            f"backup manifest_length is {after_len} after the write, expected "
            f"{_BACKUP_SMALL_LENGTH}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-LENGTH: backup %d.%d/%d -> %d.%d/%d. The major version is "
            "held VALID and the minor is non-zero, so the range rule is in force and "
            "%d sits inside [%d, %d] -- the range ACCEPTS it. It is misaligned "
            "(%d %% 4 = %d), so the 4-byte alignment rule is the only rule left that "
            "can refuse this slot",
            before_ver[0],
            before_ver[1],
            before_len,
            after_ver[0],
            after_ver[1],
            after_len,
            _BACKUP_SMALL_LENGTH,
            mm.MANIFEST_SIZE,
            mm.MANIFEST_MAX_SIZE,
            _BACKUP_SMALL_LENGTH,
            _BACKUP_SMALL_LENGTH % 4,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # Every length arm returns BAD_LENGTH silently; only the served bytes separate the siblings.
        fd.assert_served_field(
            self.logger,
            self._flash,
            "backup",
            _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, _BACKUP_MINOR, _BACKUP_SMALL_LENGTH),
            "backup manifest_version_major/minor + manifest_length",
        )
        fd.assert_no_read_starting_at(
            self.logger,
            self._flash,
            mm.BACKUP_MANIFEST_OFFSET + mm.MANIFEST_SIZE,
            f"manifest_length {_BACKUP_SMALL_LENGTH} exceeds sizeof(manifest_t), so a "
            f"fetch beginning there would mean load_manifest_extra() ran and the "
            f"backup passed validate_manifest_header instead of being refused as "
            f"BAD_LENGTH",
        )
        self.logger.info(
            "CHK-LENGTH-RULE: backup declared v%d.%d with manifest_length %d and was "
            "refused with MANIFEST_ERR=0x%08x inside its own attempt; the minor is "
            "non-zero and the length is inside [%d, %d] so the range rule accepted "
            "it, leaving the 4-byte alignment rule as the only rule that can have "
            "produced this verdict. The accepted sibling at 1188 is the aligned half "
            "of that pair",
            mm.MANIFEST_MAJOR_VERSION,
            _BACKUP_MINOR,
            _BACKUP_SMALL_LENGTH,
            _MANIFEST_ERR_BAD_LENGTH,
            mm.MANIFEST_SIZE,
            mm.MANIFEST_MAX_SIZE,
        )
