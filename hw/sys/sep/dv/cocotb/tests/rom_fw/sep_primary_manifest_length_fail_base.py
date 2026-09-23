# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario: the primary declares a refused manifest_length and the backup boots.

Subclasses set primary_minor and primary_length. Minor 0 requires the exact header
size, other minors a bounded range, and every length must be 4-byte aligned.
"""

from __future__ import annotations

import struct
from pathlib import Path

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import (
    sep_primary_fail_backup_boot_base,
)

EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
MANIFEST_ERR_BAD_VERSION = 0x0003_0003
MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR


class sep_primary_manifest_length_fail_base(sep_primary_fail_backup_boot_base):

    # --- subclass contract -------------------------------------------------
    # manifest_version_minor to declare: 0 selects the exact-match arm, non-zero the range arm.
    primary_minor: int = 0
    # manifest_length to declare; the -1 sentinel makes _refusal_arm() fail when it is unset.
    primary_length: int = -1

    # BAD_LENGTH prints no token, so attribution rests on the error code's position and count.
    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_BAD_LENGTH
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = EFUSE_PRELOAD
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    # Forbid other structural codes and the token-printing length arms; only the silent arms remain.
    extra_forbidden = (f"MANIFEST_ERR=0x{MANIFEST_ERR_BAD_MAGIC:08x}",
                       f"MANIFEST_ERR=0x{MANIFEST_ERR_BAD_VERSION:08x}",
                       "MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", "MANIFEST_ALL_FAILED",
                       "IMAGE_HASH_MISMATCH", "NO_BL1_IMAGE",
                       "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE",
                       "PAYLOAD_HASHED_LEN_BAD=", "PAYLOAD_LEN_RANGE",
                       "PAYLOAD_OVERLAPS_MANIFEST", "TOC_PLEN_MISMATCH=",
                       "PAYLOAD_LOC_OVERFLOW", "ENC_HASHED_LEN_PARTIAL",
                       fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER)

    @classmethod
    def _refusal_arm(cls) -> str:
        # The version-graded rule precedes alignment, so minor 0 always reaches the exact-match arm.
        if cls.primary_length <= 0:
            raise AssertionError(
                f"primary_length is {cls.primary_length}; the subclass did not "
                f"declare a length, so no arm can be attributed to this row"
            )
        in_range = mm.MANIFEST_SIZE <= cls.primary_length <= mm.MANIFEST_MAX_SIZE
        if cls.primary_minor == 0:
            if cls.primary_length == mm.MANIFEST_SIZE:
                raise AssertionError(
                    f"length {cls.primary_length} at minor 0 is the exact-match "
                    f"arm's ACCEPTED case; a member of this refusal family must be "
                    f"refused"
                )
            return "exact"
        if not in_range:
            return "range"
        if cls.primary_length % 4 != 0:
            return "align"
        raise AssertionError(
            f"length {cls.primary_length} at minor {cls.primary_minor} is inside "
            f"[{mm.MANIFEST_SIZE}, {mm.MANIFEST_MAX_SIZE}] and 4-byte aligned, so "
            f"validate_manifest_header ACCEPTS it; a member of this refusal family "
            f"must be refused"
        )

    @classmethod
    def _refused_by(cls) -> str:
        return {
            "exact": "the minor-0 exact-match rule",
            "align": "the 4-byte alignment rule",
            "range": ("the range rule's LOWER bound (sizeof(manifest_t))"
                      if cls.primary_length < mm.MANIFEST_SIZE
                      else "the range rule's UPPER bound (MANIFEST_MAX_SIZE)"),
        }[cls._refusal_arm()]

    def corrupt_primary(self, buf: bytearray) -> None:
        # The Python copies of the ROM manifest bounds must still match the ROM header.
        rom_max = fd.assert_rom_manifest_bounds()
        assert rom_max == mm.MANIFEST_MAX_SIZE

        before_ver = mm.manifest_version(buf, "primary")
        before_len = mm.manifest_length(buf, "primary")
        assert before_ver == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {before_ver[0]}.{before_ver[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        assert before_len == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {before_len}, expected {mm.MANIFEST_SIZE}"
        )
        assert bytes(buf[mm.PRIMARY_MANIFEST_OFFSET:
                         mm.PRIMARY_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "primary manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            "the length check and the asserted code would be wrong"
        )
        # The major version stays valid so BAD_VERSION cannot pre-empt a length arm.
        arm = self._refusal_arm()
        if arm == "exact":
            assert self.primary_length % 4 == 0, (
                f"the declared length {self.primary_length} is not 4-byte aligned. "
                f"The exact-match arm would still fire first, but the row would no "
                f"longer show that an equality rather than a bound was applied -- a "
                f"ROM checking alignment first would produce the same console"
            )
            assert mm.MANIFEST_SIZE < self.primary_length <= mm.MANIFEST_MAX_SIZE, (
                f"the declared length {self.primary_length} is not inside the range "
                f"the minor != 0 arm accepts, so refusing it would not discriminate "
                f"the exact-match rule from a lower bound or from the range rule"
            )
        elif arm == "align":
            # Self-consistency checks on _refusal_arm(); they do not constrain the stimulus.
            assert self.primary_minor != 0, "derivation error: align implies minor != 0"
            assert mm.MANIFEST_SIZE <= self.primary_length <= mm.MANIFEST_MAX_SIZE, (
                "derivation error: align implies a length the range rule accepts"
            )
            assert self.primary_length % 4 != 0, (
                "derivation error: align implies a misaligned length"
            )
        else:
            assert self.primary_length % 4 == 0, (
                f"the declared length {self.primary_length} is not 4-byte aligned, so "
                f"the alignment check rather than the range rule could produce the "
                f"verdict, and no console forbid can tell the two apart"
            )
            assert (self.primary_length < mm.MANIFEST_SIZE
                    or self.primary_length > mm.MANIFEST_MAX_SIZE), (
                "derivation error: range implies a length outside the bounds"
            )
        if self.primary_minor != 0:
            mm.set_manifest_version(buf, "primary", minor=self.primary_minor)
        mm.set_manifest_length(buf, "primary", self.primary_length)

        after_ver = mm.manifest_version(buf, "primary")
        after_len = mm.manifest_length(buf, "primary")
        assert after_ver == (mm.MANIFEST_MAJOR_VERSION, self.primary_minor), (
            f"primary manifest version is {after_ver[0]}.{after_ver[1]} after the "
            f"write, expected {mm.MANIFEST_MAJOR_VERSION}.{self.primary_minor}; the "
            f"mutation did not land"
        )
        assert after_len == self.primary_length, (
            f"primary manifest_length is {after_len} after the write, expected "
            f"{self.primary_length}; the mutation did not land"
        )
        alignment = ("4-byte aligned" if after_len % 4 == 0
                     else f"misaligned ({after_len} % 4 = {after_len % 4})")
        self.logger.info(
            "CHK-STIMULUS-LENGTH: primary %d.%d/%d -> %d.%d/%d. The major version is "
            "held VALID and the length is %s, so %s is the only rule that can refuse "
            "this slot",
            before_ver[0], before_ver[1], before_len,
            after_ver[0], after_ver[1], after_len, alignment, self._refused_by(),
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # BAD_LENGTH must belong to the primary attempt only.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        # Length is checked before integrity, so the only MANIFEST_HASH_OK is the backup's.
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

        # Every length arm returns the same silent code; only served bytes separate sibling rows.
        fd.assert_served_field(
            self.logger, flash, "primary", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, self.primary_minor,
                        self.primary_length),
            "primary manifest_version_major/minor + manifest_length",
        )

        # load_manifest_extra reads past the header only when the declared length exceeds it.
        if self.primary_length > mm.MANIFEST_SIZE:
            fd.assert_no_read_starting_at(
                self.logger, flash,
                mm.PRIMARY_MANIFEST_OFFSET + mm.MANIFEST_SIZE,
                f"manifest_length {self.primary_length} exceeds sizeof(manifest_t), "
                f"so a fetch beginning there would mean load_manifest_extra() ran "
                f"and the primary passed validate_manifest_header instead of being "
                f"refused as BAD_LENGTH",
            )

        self.logger.info(
            "CHK-LENGTH-RULE: primary@%d declared v%d.%d with manifest_length %d and "
            "was refused %s@%d inside its own attempt, before its hash was computed; "
            "the backup declared v%d.0 with manifest_length %d, was accepted with "
            "the only MANIFEST_HASH_OK@%d, and booted. %s is the only rule that can "
            "have produced this verdict",
            i_psrc, mm.MANIFEST_MAJOR_VERSION, self.primary_minor,
            self.primary_length, slot_err, i_err, mm.MANIFEST_MAJOR_VERSION,
            mm.MANIFEST_SIZE, i_hash, self._refused_by(),
        )
