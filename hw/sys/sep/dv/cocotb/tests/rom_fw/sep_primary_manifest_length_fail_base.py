# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Shared scenario: the PRIMARY declares a bad ``manifest_length``; the backup boots.

Three rows of the version-and-length group differ only in the ``(minor, length)``
pair they plant, and all three are refused by the same function through the same
error code. The stimulus checks that make each pair unambiguous, and the evidence
that attributes the single verdict to the primary slot, are identical -- so they
live here once rather than in three near-identical modules.

THE RULE, from ``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``)::

    minor == 0  ->  manifest_length == sizeof(manifest_t)   EXACTLY
    minor != 0  ->  sizeof(manifest_t) <= manifest_length <= MANIFEST_MAX_SIZE

followed by a 4-byte alignment check that applies to both. A subclass declares the
arm it drives through :attr:`primary_minor` and :attr:`primary_length`, and says in
its own docstring which bound that pair pins.

THERE ARE THREE REFUSING ARMS, NOT TWO, AND THEY SHARE ONE ERROR CODE. After the
two version-graded rules comes ``manifest_length % 4 != 0``, which returns the same
``MANIFEST_ERR_BAD_LENGTH`` and prints nothing either. No console forbid can
separate the three, so each member's arm is pinned in the STIMULUS instead:
:meth:`_refusal_arm` derives which arm a declared ``(minor, length)`` pair must
reach, and :meth:`corrupt_primary` then asserts that the other two CANNOT reach it.

    minor == 0, length != sizeof, length ALIGNED and inside the v1.x range
        -> the exact-match arm, and only it. A ROM that implemented the minor-0
           rule as a lower bound, or that applied the range rule to a v1.0
           manifest, would ACCEPT this length; the alignment arm cannot fire.

    minor != 0, length INSIDE the range but MISALIGNED
        -> the alignment arm, and only it. The range rule accepted the value and
           the exact-match rule is not in force, so nothing else is left.

    minor != 0, length OUTSIDE the range and ALIGNED
        -> the range arm, and only it.

A pair that reaches no arm is an ACCEPTED length and this base refuses to run on
it, because a member of a refusal family must be refused.

WHAT ATTRIBUTES THE VERDICT TO THE PRIMARY. ``validate_manifest_header`` prints no
per-reason token for any length arm, and the status codes that would name them --
``SEP_MSG_INVALID_MANIFEST_LENGTH`` and ``SEP_MSG_MANIFEST_TOO_LONG``
(``bootrom/prod/include/status_values.h``) -- are defined and emitted by nothing
under ``bootrom/prod/src``. So the attribution is assembled from four things, all
asserted below:

  * ``MANIFEST_ERR_BAD_LENGTH`` inside the primary's own attempt, exactly once,
    bracketed by the primary read and the backup read;
  * exactly one ``MANIFEST_HASH_OK``, following the backup read -- the length check
    precedes ``manifest_check_integrity``, so the primary never had a hash computed
    and a second occurrence would mean its length was accepted;
  * the served ``(major, minor, length)`` bytes from the flash BFM's own record,
    which is the only run-time channel that separates one length row from another
    on this ROM. That is STIMULUS-side evidence -- it proves what the DUT was given
    and can never fail because the ROM applied the wrong rule -- so it stops a
    row's checker from passing on a sibling's run without pretending to be the
    missing status code;
  * for a row whose declared length EXCEEDS ``sizeof(manifest_t)``, the absence of
    any read beginning at ``primary_base + sizeof(manifest_t)``.
    ``load_manifest_extra`` runs only for a slot that PASSED the header checks and
    would fetch exactly there, so its absence is direct device-side evidence that
    the header was refused first. This is the only member of the four that can fail
    because the ROM decided wrongly, and it is enabled automatically for the rows it
    applies to -- for a length at or below ``sizeof(manifest_t)`` no fetch happens
    either way, and asserting its absence would be evidence of nothing.

THE FAILOVER OUTCOME IS THE RESULT, NOT A SIDE EFFECT. A primary-side rejection
returns into ``rom_manifest_boot``'s retry loop rather than ending the boot, so
every member requires a completed boot from the untouched backup. The base it
inherits re-verifies that backup -- ``payload_hash``, every TOC image digest,
``manifest_hash`` over the TBS, and an RSA verification against the dev0 modulus --
before the simulation, so "it recovered" cannot be satisfied by a run that
recovered from something else.
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

# manifest.h
MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
MANIFEST_ERR_BAD_VERSION = 0x0003_0003
MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR


class sep_primary_manifest_length_fail_base(sep_primary_fail_backup_boot_base):
    """Plant a refused ``(minor, length)`` on the primary; require a backup boot."""

    # --- subclass contract -------------------------------------------------
    # manifest_version_minor to declare. 0 selects the exact-match arm, non-zero
    # the range arm.
    primary_minor: int = 0
    # manifest_length to declare. Must be refused by the arm primary_minor selects.
    # The sentinel is not a legal length, so a subclass that forgets to declare one
    # trips _refusal_arm() rather than running against an accidental stimulus.
    primary_length: int = -1

    # BAD_LENGTH prints no token of its own, so check_transport() and the error
    # code's position and count carry the primary's attribution.
    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_BAD_LENGTH
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = EFUSE_PRELOAD
    # The backup completes the whole positive chain, so the boot is a real one and
    # not an early exit that happened not to fail.
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    # The primary is refused inside validate_manifest_header, before the hash check
    # and before the crypto chain, and nothing may reject the backup. The two other
    # structural codes are forbidden because the accepted backup emits no
    # MANIFEST_ERR= of its own: exactly one structural verdict exists in this run,
    # and forbidding the neighbours is what makes it a LENGTH one rather than a
    # magic or version one.
    #
    # The BAD_LENGTH arms that DO print a token are forbidden as well, which
    # narrows the verdict to the silent ones. The full silent inventory in
    # validate_manifest_header, and how each is excluded:
    #   manifest_length exact-match / range / alignment -- the three this family
    #     drives; _refusal_arm() pins which one by excluding the other two in the
    #     STIMULUS, since no forbid can separate them;
    #   payload_offset <= 0 and payload_length == 0 -- neither field is written by
    #     this stimulus, and the shipped image satisfies both, which is what every
    #     positive testcase in this directory demonstrates on the same bytes.
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
        """Which of the three arms this member's ``(minor, length)`` pair reaches.

        Returns ``exact``, ``align`` or ``range``, or raises when the pair is one
        ``validate_manifest_header`` would ACCEPT. The order mirrors the ROM's: the
        version-graded rule is evaluated before the alignment one, so a minor-0 pair
        reaches the exact-match arm whatever its alignment.
        """
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
        """Human-readable name of the arm, for the run log."""
        return {
            "exact": "the minor-0 exact-match rule",
            "align": "the 4-byte alignment rule",
            "range": ("the range rule's LOWER bound (sizeof(manifest_t))"
                      if cls.primary_length < mm.MANIFEST_SIZE
                      else "the range rule's UPPER bound (MANIFEST_MAX_SIZE)"),
        }[cls._refusal_arm()]

    def corrupt_primary(self, buf: bytearray) -> None:
        # This stimulus is chosen relative to hand-copied mirrors of two ROM
        # #defines; require the Python and the header to still agree before relying
        # on either.
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
        # The major version is held VALID, so BAD_VERSION cannot pre-empt any length
        # arm. Which arm DOES fire is then pinned by excluding the other two, per
        # arm, because none of the three prints a token a forbid could act on.
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
            # _refusal_arm() returns "align" only for a non-zero minor, an in-range
            # length and a misaligned one, so these three restate its verdict rather
            # than constrain the stimulus -- the exclusions they name were already
            # performed there. Kept as self-consistency checks on the derivation,
            # and labelled as such so they are not read as live guards.
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
        # The alignment arm is the one row whose length is deliberately MISALIGNED,
        # so the log states the measured value rather than a fixed phrase.
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

        # CHK-LENGTH-ATTRIBUTION: BAD_LENGTH is the primary's and only the
        # primary's. A second occurrence would mean the backup's length was refused
        # too, which is the terminal scenario rather than this one.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        # CHK-HASH-NOT-REACHED: the length check precedes manifest_check_integrity
        # (manifest_load.c), so the primary never had its hash computed and the
        # single MANIFEST_HASH_OK belongs to the accepted backup.
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

        # CHK-STIMULUS-SERVED: the DUT-side stimulus half, and the only run-time
        # channel that separates this row from its length siblings -- every length
        # arm returns MANIFEST_ERR_BAD_LENGTH and none prints a token.
        fd.assert_served_field(
            self.logger, flash, "primary", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, self.primary_minor,
                        self.primary_length),
            "primary manifest_version_major/minor + manifest_length",
        )

        # CHK-NO-EXTENSION-FETCH: the DUT-side BEHAVIOUR half, which unlike the
        # check above can fail because the ROM decided wrongly. Meaningful only when
        # the declared length exceeds the header, because load_manifest_extra
        # returns without reading otherwise.
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
