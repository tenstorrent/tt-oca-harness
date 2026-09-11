# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares v1.1 with a length above ``MANIFEST_MAX_SIZE``; the ROM halts.

the ``minor != 0`` arm's UPPER-BOUND case. The expected outcome is terminal -- ``WARNING: INVALID_MANIFEST_ID`` on the primary, then
``ERROR: MANIFEST_TOO_LONG`` rather than a boot.

THE RULE, from ``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``).
With a non-zero minor the length is graded as a RANGE rather than an equality::

    minor != 0  ->  sizeof(manifest_t) <= manifest_length <= MANIFEST_MAX_SIZE

``MANIFEST_MAX_SIZE`` is 2048 (``bootrom/prod/include/manifest.h``). This testcase
is the case where the upper bound is what refuses the slot.

WHY ``MANIFEST_MAX_SIZE + 4`` PINS THE UPPER BOUND AND NOTHING ELSE. It is
unambiguous, which is asserted rather than assumed in :meth:`corrupt_backup`:

  * 2052 is 4-byte aligned, so the alignment check that follows cannot be the
    verdict;
  * 2052 is far ABOVE ``sizeof(manifest_t)``, so the range rule's LOWER bound
    cannot be the verdict either;
  * the minor is set to 1, so the ``minor == 0`` exact-match arm is not the rule in
    force -- and this is a real difference rather than a cosmetic one. Leave the minor at 0 and
    2052 is still refused, but by the exact-match arm, which is a DIFFERENT testcase
    (``..._minor_0_length_incorrect_test``). The minor write is what makes the upper
    bound the only reachable reason.

============================================================================
THIS ROW AND ``..._minor_0_length_incorrect_test`` SHARE ONE ERROR CODE
============================================================================

Both arms return ``MANIFEST_ERR_BAD_LENGTH`` and ``validate_manifest_header`` prints
no token for either, so on the console the two rows are indistinguishable. The
reference separates them -- ``ERROR: INVALID_MANIFEST_LENGTH`` against
``ERROR: MANIFEST_TOO_LONG`` -- and this ROM cannot: ``SEP_MSG_INVALID_MANIFEST_LENGTH``
(0x09) and ``SEP_MSG_MANIFEST_TOO_LONG`` (0x6b) are both DEFINED in
``bootrom/prod/include/status_values.h`` and emitted by nothing under
``bootrom/prod/src``.

**THERE IS NO ROM-SIDE DISCRIMINATOR BETWEEN THE TWO ROWS, AND THIS IS SAID PLAINLY.**
What separates them at run time is
:func:`sep_manifest_field_defect.assert_served_field`: the flash DEVICE must have
returned this row's own ``(major, minor, length)`` bytes -- 1, 1, 2052 against the
sibling's 1, 0, 1188. That is STIMULUS-side evidence; it proves what the DUT was
given and can never fail because the ROM applied the wrong rule. It is what stops
this module's checker from passing on the sibling's run, not a substitute for the
missing status code. Disclosed in this row's ``flow_deviation``. The stimulus is
additionally read back out of the packed image before the run, so a mutation that
failed to land is caught before the simulation rather than being indistinguishable
from a correct one.

**A DISCLOSED SCOPE LIMIT ON THE BOUND ITSELF.** 2052 is refused by BOTH length arms
-- it is neither equal to ``sizeof(manifest_t)`` nor within the range -- so it says
the value was rejected, not that the ROM compared against 2048. Nothing in matrix
group 4 pins the boundary: an off-by-one ROM using ``>=`` (wrongly refusing exactly
2048) would pass every testcase in the group, because the group's only ACCEPTED
``minor != 0`` length is 1188, 860 bytes below the bound. Closing that needs a
``manifest_length == MANIFEST_MAX_SIZE`` accept case, which is not one of the
approved matrix rows and is therefore recorded as a coverage gap rather than
invented here. What IS pinned is that 2052 is 4-byte aligned and above
``sizeof(manifest_t)``, so neither the alignment arm nor the lower bound produced
the verdict.

The other two siblings are separable on the console and need no such help:
``..._major_version_invalid_test`` asserts ``MANIFEST_ERR_BAD_VERSION``, and
``..._minor_nonzero_length_small_correct_test`` drives the very same ``minor != 0``
arm to its ACCEPTED case and boots. That last pair is the differential this row
belongs to: same arm, same minor, lengths 1188 and 2052, opposite outcomes -- which
is what says the ROM is comparing against the bound rather than refusing v1.1
manifests generally.

PINNING WHICH ``BAD_LENGTH`` SITE FIRED. Nine return sites in
``validate_manifest_header`` share the code, plus one in ``validate_manifest_payload``.
The four that print a token (``PAYLOAD_OFF_RANGE``, ``PAYLOAD_OFF_ALIGN``,
``PAYLOAD_HASHED_LEN_BAD=``, ``ENC_HASHED_LEN_PARTIAL``) and the payload-side
``TOC_PLEN_MISMATCH=`` are forbidden below, which narrows the verdict to the silent
arms. One of those also grades ``manifest_length`` -- the 4-byte alignment check --
and no forbid can exclude it, so it is excluded in the STIMULUS instead and asserted
in :meth:`corrupt_backup`: 2052 is aligned. Every remaining silent arm grades
``payload_offset`` or ``payload_length``, which this stimulus does not touch and
which the shipped image already satisfies -- the same bytes boot in every positive
testcase in this directory.

``load_manifest_extra`` runs only for a slot that PASSED the header checks, and 2052
would make it fetch 868 bytes at ``backup_base + 1184``. Requiring that no read
BEGINS at that address is direct device-side evidence that the header was refused
first -- the negative counterpart of what the ``small_correct`` sibling asserts
positively. The predicate is the read's COMMAND address rather than the span it
covers, because ``ocah_spi_flash._do_read`` streams until CS deasserts: a 1184-byte
header read is recorded as 1185 bytes, so its span reaches one byte into the
extension address and a coverage test cannot separate the two.

MARKER SUBSTITUTION. There is no per-reason console token for a structural
rejection on this ROM, so the code in ``MANIFEST_ERR=`` plus its position and count
inside the backup's own attempt carry the whole attribution. The failover trigger
is the primary's ``manifest_identifier``, refused as BAD_MAGIC
ahead of any hash or crypto work, with a code that differs from the backup's.

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

# MANIFEST_MAX_SIZE + 4, 4-byte
# aligned and above the upper bound, so only that bound can refuse it.
_BACKUP_LARGE_LENGTH = mm.MANIFEST_MAX_SIZE + 4
# Any non-zero minor takes the range arm.
_BACKUP_MINOR = 1

_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_valid_minor_nonzero_length_large_test(
        sep_backup_manifest_structural_fail_base):
    """Backup is v1.1 with length 2052 -> both slots refused -> the ROM halts."""

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
        # This stimulus IS MANIFEST_MAX_SIZE + 4, so the whole testcase is only as
        # correct as the Python mirror of that #define. Require the two to agree.
        rom_max = fd.assert_rom_manifest_bounds()
        assert _BACKUP_LARGE_LENGTH == rom_max + 4, (
            f"the trigger length {_BACKUP_LARGE_LENGTH} is not one 4-byte step above "
            f"the ROM's MANIFEST_MAX_SIZE ({rom_max}), which is the reference's own "
            f"choice for this scenario"
        )
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
        assert _BACKUP_LARGE_LENGTH % 4 == 0, (
            "the trigger length is not 4-byte aligned, so the alignment check rather "
            "than the range rule's upper bound would produce the verdict"
        )
        assert _BACKUP_LARGE_LENGTH > mm.MANIFEST_MAX_SIZE > mm.MANIFEST_SIZE, (
            f"the trigger length {_BACKUP_LARGE_LENGTH} does not exceed "
            f"MANIFEST_MAX_SIZE ({mm.MANIFEST_MAX_SIZE}), so the upper bound would "
            f"not be what refuses this slot"
        )
        assert _BACKUP_MINOR != 0, (
            "the minor version must be non-zero or the exact-match arm, not the "
            "range rule, is the rule in force and this becomes a different testcase"
        )

        mm.set_manifest_version(buf, "backup", minor=_BACKUP_MINOR)
        mm.set_manifest_length(buf, "backup", _BACKUP_LARGE_LENGTH)
        after_ver = mm.manifest_version(buf, "backup")
        after_len = mm.manifest_length(buf, "backup")
        assert after_ver == (mm.MANIFEST_MAJOR_VERSION, _BACKUP_MINOR), (
            f"backup manifest version is {after_ver[0]}.{after_ver[1]} after the "
            f"write, expected {mm.MANIFEST_MAJOR_VERSION}.{_BACKUP_MINOR}; the "
            f"mutation did not land"
        )
        assert after_len == _BACKUP_LARGE_LENGTH, (
            f"backup manifest_length is {after_len} after the write, expected "
            f"{_BACKUP_LARGE_LENGTH}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-LENGTH: backup %d.%d/%d -> %d.%d/%d. The major version is "
            "held VALID and the minor is non-zero, so the range rule is in force; "
            "%d is 4-byte aligned and above MANIFEST_MAX_SIZE (%d), so its upper "
            "bound is the only rule that can refuse this slot",
            before_ver[0], before_ver[1], before_len,
            after_ver[0], after_ver[1], after_len,
            _BACKUP_LARGE_LENGTH, mm.MANIFEST_MAX_SIZE,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # CHK-STIMULUS-SERVED: the DUT-side STIMULUS half, and the only run-time
        # channel that separates this row from ..._minor_0_length_incorrect_test --
        # both arms return MANIFEST_ERR_BAD_LENGTH and neither prints a token that
        # tells them apart. It proves what the DUT was GIVEN.
        fd.assert_served_field(
            self.logger, self._flash, "backup", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", mm.MANIFEST_MAJOR_VERSION, _BACKUP_MINOR,
                        _BACKUP_LARGE_LENGTH),
            "backup manifest_version_major/minor + manifest_length",
        )

        # CHK-NO-EXTENSION-FETCH: the DUT-side BEHAVIOUR half, which unlike the check
        # above can fail because the ROM decided wrongly. load_manifest_extra runs
        # only for a slot that passed validate_manifest_header.
        fd.assert_no_read_starting_at(
            self.logger, self._flash,
            mm.BACKUP_MANIFEST_OFFSET + mm.MANIFEST_SIZE,
            f"manifest_length {_BACKUP_LARGE_LENGTH} exceeds sizeof(manifest_t), so a "
            f"fetch beginning there would mean load_manifest_extra() ran and the "
            f"backup passed validate_manifest_header instead of being refused as "
            f"BAD_LENGTH",
        )
        self.logger.info(
            "CHK-LENGTH-RULE: backup declared v%d.%d with manifest_length %d and was "
            "refused with MANIFEST_ERR=0x%08x inside its own attempt; the minor is "
            "non-zero and the length is aligned, so the range rule's upper bound "
            "(MANIFEST_MAX_SIZE = %d) is the only rule that can have produced this "
            "verdict", mm.MANIFEST_MAJOR_VERSION, _BACKUP_MINOR,
            _BACKUP_LARGE_LENGTH, _MANIFEST_ERR_BAD_LENGTH, mm.MANIFEST_MAX_SIZE,
        )
