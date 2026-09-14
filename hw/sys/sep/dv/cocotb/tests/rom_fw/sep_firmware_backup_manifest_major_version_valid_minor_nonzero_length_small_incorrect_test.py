# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.1 with a misaligned length; the ROM halts.

The ``minor != 0`` arm ACCEPTS the value and the 4-BYTE ALIGNMENT rule refuses it.
``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``) grades the
length in two steps::

    minor != 0  ->  sizeof(manifest_t) <= manifest_length <= MANIFEST_MAX_SIZE
    then, for both minor arms  ->  manifest_length % 4 == 0

so ``sizeof(manifest_t) + 1`` = 1185 passes the range and fails the alignment, which
is ``MANIFEST_ERR_BAD_LENGTH``. The primary was already refused on its identifier,
so both slots fail and the expected outcome is terminal rather than a boot.

WHY 1185 PINS THE ALIGNMENT RULE AND NOTHING ELSE. This is the only one of the three
refusing length arms whose stimulus is unambiguous without any appeal to a bound,
and :meth:`corrupt_backup` asserts each exclusion rather than assuming it:

  * 1185 is INSIDE ``[sizeof(manifest_t), MANIFEST_MAX_SIZE]``, so the range rule
    ACCEPTED it -- neither its lower nor its upper bound can be the verdict;
  * the minor is set to 1, so the ``minor == 0`` exact-match rule is not in force.
    That is a real difference and not a cosmetic one: leave the minor at 0 and 1185
    is still refused, but by the exact-match arm, which is a DIFFERENT row
    (``..._minor_0_length_incorrect_test``);
  * nothing is left but ``manifest_length % 4 != 0``.

============================================================================
THE ALIGNMENT RULE IS DRIVEN TO BOTH OUTCOMES AT THE SAME MINOR VERSION
============================================================================

``..._minor_nonzero_length_small_correct_test`` plants minor 1 with 1188 in this
same slot and BOOTS from it. So at minor 1 this directory has 1185 refused and 1188
accepted -- the same byte class, differing only in the low two bits of
``manifest_length`` -- with nothing else about the two slots differing. Neither
checker can pass on the other's log: that one requires ``MANIFEST_OK``,
``SIG_VALID`` and ``BL1_JUMP=``, this one requires ``MANIFEST_ALL_FAILED`` and
forbids every boot-progress marker. **That pair is the alignment discriminator, and
it is what makes the rule falsifiable rather than merely satisfied.**

============================================================================
THIS ROW SHARES ONE ERROR CODE WITH EVERY OTHER LENGTH ROW
============================================================================

Both length arms return ``MANIFEST_ERR_BAD_LENGTH`` and ``validate_manifest_header``
prints no token for either, so on the console this row is indistinguishable from
``..._minor_0_length_incorrect_test`` and ``..._minor_nonzero_length_large_test``.
``SEP_MSG_INVALID_MANIFEST_LENGTH`` and ``SEP_MSG_MANIFEST_TOO_LONG`` are both
DEFINED in ``bootrom/prod/include/status_values.h`` and emitted by nothing under
``bootrom/prod/src``, so the console cannot separate the two arms at all.

**THERE IS NO ROM-SIDE DISCRIMINATOR BETWEEN THESE ROWS, AND THIS IS SAID PLAINLY.**
What separates them at run time is
:func:`sep_manifest_field_defect.assert_served_field`: the flash DEVICE must have
returned this row's own ``(major, minor, length)`` bytes -- 1, 1, 1185 against the
siblings' 1, 0, 1188 and 1, 1, 2052. That is STIMULUS-side evidence; it proves what
the DUT was given and can never fail because the ROM applied the wrong rule. It is
what stops this module's checker from passing on a sibling's run, not a substitute
for the missing status code. Disclosed in this row's ``flow_deviation``. The
stimulus is additionally read back out of the packed image before the run, so a
mutation that failed to land is caught before the simulation rather than being
indistinguishable from a correct one.

**THE DEVICE-SIDE BEHAVIOUR HALF.** 1185 exceeds ``sizeof(manifest_t)``, so
``load_manifest_extra`` would fetch one byte at ``backup_base + 1184`` for a slot
that PASSED the header checks. Requiring that no read BEGINS there is evidence the
header was refused first, and unlike the served-field check above it CAN fail
because the ROM decided wrongly. The predicate is the read's COMMAND address rather
than the span it covers, because ``ocah_spi_flash._do_read`` streams until CS
deasserts: a 1184-byte header read is recorded as 1185 bytes, so its span already
reaches one byte into the extension address and a coverage test cannot separate the
two.

PINNING WHICH ``BAD_LENGTH`` SITE FIRED. Several return sites in
``validate_manifest_header`` share the code, plus one in
``validate_manifest_payload``. The four that print a token (``PAYLOAD_OFF_RANGE``,
``PAYLOAD_OFF_ALIGN``, ``PAYLOAD_HASHED_LEN_BAD=``, ``ENC_HASHED_LEN_PARTIAL``) and
the payload-side ``TOC_PLEN_MISMATCH=`` are forbidden below, which narrows the
verdict to the silent arms. Three of those grade ``manifest_length`` -- the
exact-match rule, the range rule and the alignment check -- and no forbid can
separate them, so the first two are excluded in the STIMULUS instead: the minor is
non-zero and 1185 is inside the range. Every remaining silent arm grades
``payload_offset`` or ``payload_length``, which this stimulus does not touch and
which the shipped image already satisfies.

MARKER SUBSTITUTION. There is no per-reason console token for a structural
rejection on this ROM, so the code in ``MANIFEST_ERR=`` plus its position and count
inside the backup's own attempt carry the whole attribution. The failover trigger is
the primary's ``manifest_identifier``, refused as BAD_MAGIC ahead of any hash or
crypto work, with a code that differs from the backup's.

No ``+sep_crypto_edn_force``: neither slot reaches ``manifest_crypto_validate``.
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

# sizeof(manifest_t) + 1: inside the range the minor != 0 arm accepts, and
# misaligned, so only the alignment rule can refuse it.
_BACKUP_SMALL_LENGTH = mm.MANIFEST_SIZE + 1
# Any non-zero minor takes the range arm.
_BACKUP_MINOR = 1

_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_nonzero_length_small_incorrect_test(
        sep_backup_manifest_structural_fail_base):
    """Backup is v1.1 with length 1185 -> both slots refused -> the ROM halts."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_LENGTH:08x}"
    expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    efuse_preload = EFUSE_PRELOAD
    extra_forbidden = (fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
                       "MANIFEST_HASH_MISMATCH", "MANIFEST_HASH_OK", "CRYPTO_FAIL=",
                       "PAYLOAD_OFF_RANGE", "PAYLOAD_OFF_ALIGN",
                       "PAYLOAD_HASHED_LEN_BAD=", "ENC_HASHED_LEN_PARTIAL",
                       "PAYLOAD_LEN_RANGE", "PAYLOAD_OVERLAPS_MANIFEST",
                       "TOC_PLEN_MISMATCH=", "NO_BL1_IMAGE")

    def corrupt_backup(self, buf: bytearray) -> None:
        # This stimulus is chosen relative to hand-copied mirrors of two ROM
        # #defines; require the Python and the header to still agree before relying
        # on either.
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
        assert bytes(buf[mm.BACKUP_MANIFEST_OFFSET:
                         mm.BACKUP_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "backup manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt the "
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
            before_ver[0], before_ver[1], before_len,
            after_ver[0], after_ver[1], after_len,
            _BACKUP_SMALL_LENGTH, mm.MANIFEST_SIZE, mm.MANIFEST_MAX_SIZE,
            _BACKUP_SMALL_LENGTH, _BACKUP_SMALL_LENGTH % 4,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # CHK-STIMULUS-SERVED: the DUT-side STIMULUS half, and the only run-time
        # channel that separates this row from its two length siblings -- every
        # length arm returns MANIFEST_ERR_BAD_LENGTH and none prints a token that
        # tells them apart. It proves what the DUT was GIVEN.
        fd.assert_served_field(
            self.logger, self._flash, "backup", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, _BACKUP_MINOR,
                        _BACKUP_SMALL_LENGTH),
            "backup manifest_version_major/minor + manifest_length",
        )
        # CHK-NO-EXTENSION-FETCH: the DUT-side BEHAVIOUR half, which unlike the
        # check above can fail because the ROM decided wrongly. load_manifest_extra
        # runs only for a slot that passed validate_manifest_header.
        fd.assert_no_read_starting_at(
            self.logger, self._flash,
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
            "of that pair", mm.MANIFEST_MAJOR_VERSION, _BACKUP_MINOR,
            _BACKUP_SMALL_LENGTH, _MANIFEST_ERR_BAD_LENGTH, mm.MANIFEST_SIZE,
            mm.MANIFEST_MAX_SIZE,
        )
