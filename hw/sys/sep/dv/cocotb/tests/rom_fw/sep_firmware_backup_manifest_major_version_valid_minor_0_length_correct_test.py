# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest is a valid v1.0 of exactly ``sizeof(manifest_t)``; it boots.

The primary declares v1.0 with length ``sizeof(manifest_t) + 4`` and is refused as
BAD_LENGTH, so one run shows the exact-match length rule refuse and accept.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import (
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

_PRIMARY_BAD_LENGTH = mm.MANIFEST_SIZE + 4


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_0_length_correct_test(
        sep_primary_fail_backup_boot_base):
    """v1.0 length 1188 is refused; v1.0 length 1184 is accepted and boots."""

    # BAD_LENGTH prints no console token, so check_transport() carries the attribution.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    # BAD_LENGTH has several return sites; forbidding the token-printing ones isolates minor-0.
    extra_forbidden = ("MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", "MANIFEST_ALL_FAILED",
                       "IMAGE_HASH_MISMATCH", "NO_BL1_IMAGE",
                       "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE",
                       "PAYLOAD_HASHED_LEN_BAD=", "PAYLOAD_LEN_RANGE",
                       "PAYLOAD_OVERLAPS_MANIFEST", "TOC_PLEN_MISMATCH=",
                       fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER)

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_length(buf, "primary")
        assert before == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {before}, expected {mm.MANIFEST_SIZE}: "
            f"the shipped image is not the valid baseline this trigger mutates "
            f"away from"
        )
        major, minor = mm.manifest_version(buf, "primary")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {major}.{minor}: the exact-match length "
            f"rule is the minor-0 arm's, so a different minor would send this "
            f"stimulus down the range rule and 1188 would be ACCEPTED"
        )
        assert _PRIMARY_BAD_LENGTH % 4 == 0, (
            "the trigger length is not 4-byte aligned, so the alignment check "
            "rather than the exact-match rule would produce the verdict"
        )
        assert mm.MANIFEST_SIZE < _PRIMARY_BAD_LENGTH <= mm.MANIFEST_MAX_SIZE, (
            f"the trigger length {_PRIMARY_BAD_LENGTH} is not inside the range the "
            f"minor != 0 arm accepts, so rejecting it would not discriminate the "
            f"exact-match rule from the range rule"
        )
        mm.set_manifest_length(buf, "primary", _PRIMARY_BAD_LENGTH)
        after = mm.manifest_length(buf, "primary")
        assert after == _PRIMARY_BAD_LENGTH, (
            f"primary manifest_length is {after} after the write, expected "
            f"{_PRIMARY_BAD_LENGTH}; the mutation did not land"
        )
        assert bytes(buf[mm.PRIMARY_MANIFEST_OFFSET:
                         mm.PRIMARY_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "primary manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            "the length check and the asserted code would be wrong"
        )
        self.logger.info(
            "CHK-STIMULUS-LENGTH: primary manifest_length %d -> %d at version "
            "%d.%d -- 4-byte aligned and inside the range the minor != 0 arm "
            "accepts, so only the minor-0 exact-match rule can refuse it",
            before, after, major, minor,
        )

    def prepare_backup(self, buf: bytearray) -> None:
        # sep_manifest_mutate refuses no-op writes, so the shipped valid values are asserted.
        major, minor = mm.manifest_version(buf, "backup")
        length = mm.manifest_length(buf, "backup")
        assert major == mm.MANIFEST_MAJOR_VERSION, (
            f"backup manifest_version_major is {major}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}: the slot under test is supposed to be "
            f"the ACCEPTED one and would be refused as BAD_VERSION"
        )
        assert minor == 0, (
            f"backup manifest_version_minor is {minor}, expected 0: this testcase "
            f"is the minor-0 arm, and a non-zero minor would send the length down "
            f"the range rule instead of the exact-match one"
        )
        assert length == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {length}, expected exactly "
            f"{mm.MANIFEST_SIZE} (sizeof(manifest_t)): the minor-0 arm demands "
            f"equality, so any other value would be refused as BAD_LENGTH"
        )
        assert bytes(buf[mm.BACKUP_MANIFEST_OFFSET:
                         mm.BACKUP_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "backup manifest_identifier is not TBL1"
        )
        self.logger.info(
            "CHK-STIMULUS-BACKUP-VERSION: backup declares %d.%d with "
            "manifest_length %d == sizeof(manifest_t) -- the minor-0 arm's "
            "satisfied case, and the ONLY field that differs from the refused "
            "primary is the length", major, minor, length,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        n_ok = fd.count(console, "MANIFEST_HASH_OK")
        assert n_ok == 1, (
            f"MANIFEST_HASH_OK appeared {n_ok} times, expected exactly 1 (the "
            f"backup's). A second occurrence would mean the primary passed "
            f"validate_manifest_header, so its length was accepted. "
            f"Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_bsrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} did not follow the backup read@{i_bsrc}: "
            f"the one hash that verified is not the backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-LENGTH-RULE: primary (v1.0, length %d) rejected with %s@%d inside "
            "its own attempt (read@%d, backup read@%d); backup (v1.0, length %d) "
            "accepted with the only MANIFEST_HASH_OK@%d -- the exact-match rule "
            "demonstrated in both directions",
            _PRIMARY_BAD_LENGTH, slot_err, i_err, i_psrc, i_bsrc,
            mm.MANIFEST_SIZE, i_hash,
        )
