# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.0 with a length that is not exactly 1184; the ROM halts.

the ``minor == 0`` arm's REFUSED case. The expected outcome is terminal -- ``WARNING: INVALID_MANIFEST_ID`` on the primary, then
``ERROR: INVALID_MANIFEST_LENGTH`` rather than a boot.

THE RULE, from ``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``).
Major must equal ``MANIFEST_MAJOR_VERSION``; the length is then graded by the MINOR
version, and the two arms are different rules rather than one relaxed one::

    minor == 0  ->  manifest_length == sizeof(manifest_t)   EXACTLY
    minor != 0  ->  sizeof(manifest_t) <= manifest_length <= MANIFEST_MAX_SIZE

followed by a 4-byte alignment check that applies to both.

============================================================================
WHY THE TRIGGER LENGTH IS 1188
============================================================================

0, 1183 and 1185 are the obvious candidates. Every one of those is refused by two
or three arms at once -- 0 and 1183 are also below
``sizeof(manifest_t)`` and 1183 and 1185 are also unaligned -- so none of them can
tell the exact-match rule from the rules around it, and a ROM that had implemented
the ``minor == 0`` arm as a lower bound would still reject all three.

``sizeof(manifest_t) + 4`` = 1188 is the value that discriminates:

  * it is 4-byte aligned, so the alignment check cannot be what refuses it;
  * it is ABOVE ``sizeof(manifest_t)`` and at or below ``MANIFEST_MAX_SIZE``, i.e.
    strictly inside the range the ``minor != 0`` arm ACCEPTS. A ROM that applied
    the range rule to a v1.0 manifest, or that read the exact-match arm as a lower
    bound, would ACCEPT this slot and the run would boot instead of halting.

Only an exact equality rejects 1188, so the terminal verdict IS the exact-match
rule. All three assertions are made in :meth:`corrupt_backup` before the run, so a
future change to ``MANIFEST_MAX_SIZE`` that made 1188 out of range would fail loudly
rather than quietly turning this into a range-rule testcase.

============================================================================
DISCRIMINATION FROM THE THREE ADJACENT TESTCASES
============================================================================

``sep_firmware_backup_manifest_major_version_valid_minor_0_length_correct_test``
plants exactly this value -- 1188 at minor 0 -- but in the PRIMARY, and its backup
is the untouched valid slot, so it BOOTS. That row proves the rule refuses 1188;
this row proves the same refusal is TERMINAL when the surviving slot carries it.
One stimulus, two slots, opposite outcomes: the pair is the failover semantics, and
neither checker can pass on the other's log (that one requires ``MANIFEST_OK`` and
``BL1_JUMP=``; this one forbids both and requires ``MANIFEST_ALL_FAILED``).

``sep_firmware_backup_manifest_major_version_invalid_test`` holds the length valid
and moves the major version, and asserts ``MANIFEST_ERR_BAD_VERSION``; this row
holds the version valid and moves the length. The two codes differ, so neither can
claim the other's verdict.

``sep_firmware_backup_manifest_major_version_valid_minor_nonzero_length_large_test``
is the one that CANNOT be separated on the console: it is refused by the other
length arm and this ROM returns the same ``MANIFEST_ERR_BAD_LENGTH`` for both, with
no token of its own. ``SEP_MSG_INVALID_MANIFEST_LENGTH`` (0x09) and
``SEP_MSG_MANIFEST_TOO_LONG`` (0x6b) are both DEFINED in
``bootrom/prod/include/status_values.h`` and emitted by nothing.

**THERE IS NO ROM-SIDE DISCRIMINATOR BETWEEN THE TWO ROWS, AND THIS IS SAID PLAINLY
RATHER THAN PAPERED OVER.** Both are refused inside one function, with one code, on
a silent path, and everything downstream is identical. What separates them at run
time is :func:`sep_manifest_field_defect.assert_served_field`, and that check proves
the DEVICE returned this row's own ``(major, minor, length)`` bytes -- it is
STIMULUS-side evidence, not rejection-reason attribution, and it can never fail
because the ROM applied the wrong rule. It is what stops this module's checker from
passing on the sibling's run; it is not a substitute for the missing status code.
Disclosed in this row's ``flow_deviation``.

============================================================================
PINNING WHICH ``BAD_LENGTH`` SITE FIRED
============================================================================

``MANIFEST_ERR_BAD_LENGTH`` has nine return sites in ``validate_manifest_header``
plus one in ``validate_manifest_payload``, and the code alone cannot say which one
produced it. Four print a token -- ``PAYLOAD_OFF_RANGE``, ``PAYLOAD_OFF_ALIGN``,
``PAYLOAD_HASHED_LEN_BAD=`` and ``ENC_HASHED_LEN_PARTIAL`` -- and ``TOC_PLEN_MISMATCH=``
covers the payload-side one; all five are forbidden below, which narrows the verdict
to the silent arms.

Of the silent arms, **one other also grades ``manifest_length``**: the 4-byte
alignment check that follows the version-graded rules. Forbidding tokens cannot
exclude it, so the exclusion is made in the STIMULUS instead and asserted in
:meth:`corrupt_backup`: 1188 is 4-byte aligned, so that arm cannot fire. The
remaining silent arms all grade ``payload_offset`` or ``payload_length``, which this
stimulus does not touch and which the shipped image already satisfies -- the same
bytes boot in every positive testcase in this directory. With ``manifest_length``
the single field written, and alignment excluded by construction, the minor-0
exact-match arm is the only site this run can reach.

One further exclusion is observed rather than argued: ``load_manifest_extra``
(``manifest_load.c``) fetches the bytes past ``sizeof(manifest_t)`` only for a slot
that PASSED ``validate_manifest_header``. 1188 would make it read 4 bytes at
``backup_base + 1184``, so requiring that no flash read BEGINS at that address is
direct device-side evidence that the header was refused before the extension load --
the negative counterpart of the assertion its ``minor != 0`` sibling makes.

The predicate is the read's COMMAND address, not the span it covers, and that
distinction is a real distinction rather than pedantry:
``ocah_spi_flash._do_read`` streams bytes until CS deasserts, so a 1184-byte header
read is recorded as 1185 bytes and its span therefore reaches one byte INTO the
extension address. A coverage test cannot tell the header read from an extension
fetch; the start address can.

MARKER SUBSTITUTION. There is no per-reason console token for a structural
rejection on this ROM, so the error code in ``MANIFEST_ERR=`` plus its position and
count inside the backup's own attempt carry the whole attribution.
The failover trigger is the
primary's ``manifest_identifier``, refused as BAD_MAGIC by the check immediately
ahead of the version and length ones, so it costs no hash or crypto work and its
code differs from the backup's -- which the shared base requires.

No ``+sep_crypto_edn_force``: neither slot reaches ``manifest_crypto_validate``, so
OTBN is never driven.
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

# manifest.h
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
_MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

# 4-byte aligned and inside the range the minor != 0 arm accepts, so only the
# minor-0 exact-match rule can refuse it. See the module docstring.
_BACKUP_BAD_LENGTH = mm.MANIFEST_SIZE + 4

# manifest.h: manifest_version_major(2) + manifest_version_minor(2) +
# manifest_length(4), contiguous from offset 4.
_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR
_VERSION_LENGTH_LEN = 8


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_0_length_incorrect_test(
        sep_backup_manifest_structural_fail_base):
    """Backup is v1.0 with length 1188 -> both slots refused -> the ROM halts."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_LENGTH:08x}"
    expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    efuse_preload = EFUSE_PRELOAD
    # Neither slot reaches the integrity check, the usage-constraint block or the
    # crypto chain. The four token-printing BAD_LENGTH / hashed-length sites are
    # forbidden so that the silent minor-0 arm is the only one this run can have
    # taken; see the module docstring.
    extra_forbidden = (fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
                       "MANIFEST_HASH_MISMATCH", "MANIFEST_HASH_OK", "CRYPTO_FAIL=",
                       "PAYLOAD_OFF_RANGE", "PAYLOAD_OFF_ALIGN",
                       "PAYLOAD_HASHED_LEN_BAD=", "ENC_HASHED_LEN_PARTIAL",
                       "PAYLOAD_LEN_RANGE", "PAYLOAD_OVERLAPS_MANIFEST",
                       "TOC_PLEN_MISMATCH=", "NO_BL1_IMAGE")

    def corrupt_backup(self, buf: bytearray) -> None:
        # The bound this stimulus is chosen relative to is a hand-copied mirror of a
        # ROM #define; require the two to still agree before relying on it.
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
        assert bytes(buf[mm.BACKUP_MANIFEST_OFFSET:
                         mm.BACKUP_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "backup manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt the "
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
            "with identifier TBL1 -- 4-byte aligned and inside the range the "
            "minor != 0 arm accepts, so only the minor-0 exact-match rule can refuse "
            "it", before, after, major, minor,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # CHK-STIMULUS-SERVED: the DUT-side STIMULUS half. This ROM returns the same
        # MANIFEST_ERR_BAD_LENGTH for both length arms and prints no token for
        # either, so the served version-and-length bytes are
        # the only run-time channel separating this row from the
        # minor_nonzero_length_large sibling. It proves what the DUT was GIVEN.
        fd.assert_served_field(
            self.logger, self._flash, "backup", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, 0, _BACKUP_BAD_LENGTH),
            "backup manifest_version_major/minor + manifest_length",
        )

        # CHK-NO-EXTENSION-FETCH: the DUT-side BEHAVIOUR half, and unlike the check
        # above this one can fail because the ROM decided wrongly. load_manifest_extra
        # runs only for a slot that PASSED validate_manifest_header, and 1188 would
        # make it fetch 4 bytes here -- so the absence of that read is evidence the
        # header was refused first.
        fd.assert_no_read_starting_at(
            self.logger, self._flash,
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
            mm.MANIFEST_MAJOR_VERSION, _BACKUP_BAD_LENGTH, _MANIFEST_ERR_BAD_LENGTH,
            _BACKUP_BAD_LENGTH,
        )
