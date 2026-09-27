# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.0 with a length that is not exactly 1184; the ROM halts.

The backup length is 1188: aligned and inside the minor != 0 range, so only the
minor-0 exact-match rule can refuse it. The primary is refused as BAD_MAGIC.
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

_BACKUP_BAD_LENGTH = mm.MANIFEST_SIZE + 4

# manifest_version_major (u16), manifest_version_minor (u16), manifest_length (u32), contiguous.
_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR
_VERSION_LENGTH_LEN = 8


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_0_length_incorrect_test(
    sep_backup_manifest_structural_fail_base
):
    """Backup is v1.0 with length 1188 -> both slots refused -> the ROM halts."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_LENGTH:08x}"
    expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    efuse_preload = EFUSE_PRELOAD
    # Forbidding the token-printing BAD_LENGTH sites leaves the silent minor-0 arm as the only one.
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
        fd.assert_rom_manifest_bounds()
        before = mm.manifest_length(buf, "backup")
        assert before == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {before}, expected {mm.MANIFEST_SIZE}: the "
            f"shipped image is not the valid baseline this testcase mutates away from"
        )
        major, minor = mm.manifest_version(buf, "backup")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {major}.{minor}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the exact-match length rule is the "
            f"minor-0 arm's, so a different minor would send this stimulus down the "
            f"range rule and 1188 would be ACCEPTED"
        )
        assert (
            bytes(buf[mm.BACKUP_MANIFEST_OFFSET : mm.BACKUP_MANIFEST_OFFSET + 4])
            == mm.MANIFEST_MAGIC
        ), (
            "backup manifest_identifier is not OCAC, so BAD_MAGIC would pre-empt the "
            "length check and the asserted code would be wrong"
        )
        assert _BACKUP_BAD_LENGTH % 4 == 0, (
            "the trigger length is not 4-byte aligned, so the alignment check rather "
            "than the exact-match rule would produce the verdict"
        )
        assert mm.MANIFEST_SIZE < _BACKUP_BAD_LENGTH <= mm.MANIFEST_MAX_SIZE, (
            f"the trigger length {_BACKUP_BAD_LENGTH} is not inside the range the "
            f"minor != 0 arm accepts, so rejecting it would not discriminate the "
            f"exact-match rule from the range rule"
        )
        mm.set_manifest_length(buf, "backup", _BACKUP_BAD_LENGTH)
        after = mm.manifest_length(buf, "backup")
        assert after == _BACKUP_BAD_LENGTH, (
            f"backup manifest_length is {after} after the write, expected "
            f"{_BACKUP_BAD_LENGTH}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-LENGTH: backup manifest_length %d -> %d at version %d.%d "
            "with identifier OCAC -- 4-byte aligned and inside the range the "
            "minor != 0 arm accepts, so only the minor-0 exact-match rule can refuse "
            "it",
            before,
            after,
            major,
            minor,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # Both length arms return BAD_LENGTH silently; only the served bytes separate the siblings.
        fd.assert_served_field(
            self.logger,
            self._flash,
            "backup",
            _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, 0, _BACKUP_BAD_LENGTH),
            "backup manifest_version_major/minor + manifest_length",
        )

        fd.assert_no_read_starting_at(
            self.logger,
            self._flash,
            mm.BACKUP_MANIFEST_OFFSET + mm.MANIFEST_SIZE,
            f"manifest_length {_BACKUP_BAD_LENGTH} exceeds sizeof(manifest_t), so a "
            f"fetch beginning there would mean load_manifest_extra() ran and the "
            f"backup passed validate_manifest_header instead of being refused as "
            f"BAD_LENGTH",
        )
        self.logger.info(
            "CHK-LENGTH-RULE: backup declared v%d.0 with manifest_length %d and was "
            "refused with MANIFEST_ERR=0x%08x inside its own attempt; %d is aligned "
            "and inside the minor != 0 range, so the exact-match arm is the only "
            "rule that can have produced this verdict",
            mm.MANIFEST_MAJOR_VERSION,
            _BACKUP_BAD_LENGTH,
            _MANIFEST_ERR_BAD_LENGTH,
            _BACKUP_BAD_LENGTH,
        )
