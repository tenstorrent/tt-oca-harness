# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup declares ``payload_hashed_length`` = 0; the ROM halts.

``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``) bounds the
hashed region of the payload::

    0 < payload_hashed_length <= payload_length

and on violation it echoes the offending value as ``PAYLOAD_HASHED_LEN_BAD=`` and
returns ``MANIFEST_ERR_BAD_LENGTH``. The primary was already refused on its
identifier, so both slots fail and the expected outcome is terminal rather than a
boot.

WHY THE STIMULUS IS ZERO. The reference draws this row's
``payload_hashed_length`` from ``[0, randint(1, 9999), 465, 464, 463]``, and grades
the outcome on which of two verdicts the draw produces: below the minimum TOC size
it expects ``INVALID_PAYLOAD_HASH_LENGTH``, at or above it
``INVALID_ENCRYPTED_PAYLOAD_LENGTH`` with encryption switched on. **Zero is the only
draw that reaches the verdict this row is NAMED for, and the only one that reaches
this ROM's bound without changing the feature under test.** The other four map onto
this ROM as follows:

  * ``randint(1, 9999)`` is out of this ROM's bound only when it happens to exceed
    ``payload_length``, so the stimulus would be a draw rather than a property of
    the row -- and where it does exceed it, the reference's own expectation is the
    ENCRYPTED verdict, not this one;
  * 463, 464 and 465 all satisfy ``0 < value <= payload_length`` on this ROM, so
    ``validate_manifest_header`` ACCEPTS them. The slot would be refused later as
    ``PLD_HASH_MISMATCH``, which is a different check with a different error code;
  * reaching the reference's ENCRYPTED verdict at all would mean setting
    ``encrypted_payload``, which on this ROM brings in the decryption path and the
    ``ENC_HASHED_LEN_PARTIAL`` arm, and would change what this row tests.

Zero is also the security-meaningful half of the bound: ``verify_payload_hash``
returns OK for a zero length, so ``payload_hashed_length == 0`` is a manifest opting
out of its own payload hash entirely, which is the hole this bound exists to close.
The payload is deliberately left NON-encrypted, unlike the reference's BACKUP
scenario, which sets ``encrypted_payload = 1``. The reference's own comment gives
its reason -- the 464 draw would otherwise be a legitimate length -- and that
reasoning does not apply to zero. Enabling encryption here would instead bring in
``ENC_HASHED_LEN_PARTIAL``, the arm immediately after this bound, which returns the
SAME error code -- so the exclusion would rest on check ordering rather than on an
unreachable path. It would also force ``sep_payload_mutate.verify_sealed`` to drop
its TOC anchor, since an encrypted payload's TOC is ciphertext until the ROM
decrypts it. Recorded in this row's ``flow_deviation``.

============================================================================
THIS IS THE ONLY BAD_LENGTH ARM WITH ITS OWN CONSOLE TOKEN
============================================================================

Every other length arm in ``validate_manifest_header`` returns silently, which is
why the version-and-length rows in this directory can only be told apart on
stimulus-side evidence and say so in their ``flow_deviation``. **This row needs no
such disclosure.** The arm prints ``PAYLOAD_HASHED_LEN_BAD=`` WITH THE VALUE, so the
attribution is ROM-side:

  * the token must appear exactly once, inside the backup's own attempt, bracketed
    by the backup read and ``MANIFEST_ALL_FAILED``;
  * the echoed value must equal the planted 0 exactly. That is the ROM reading back
    the field this testcase wrote, so the checker cannot be satisfied by a slot
    refused for a different reason, nor by any sibling's log.

``manifest_identifier``, ``manifest_version_major``, ``manifest_version_minor`` and
``manifest_length`` are all left at their shipped valid values, so none of the
earlier arms can pre-empt this one -- asserted in :meth:`corrupt_backup` rather than
assumed.

THE OTHER ``payload_length``-RELATIVE ARM IS EXCLUDED IN THE STIMULUS.
``ENC_HASHED_LEN_PARTIAL`` fires for an ENCRYPTED payload whose hashed length is
merely shorter than the payload. The shipped image is not encrypted, which
:meth:`corrupt_backup` asserts, and the token is forbidden as well.

WHY THE FIELD IS RE-HASHED BUT NOT RE-SIGNED. ``payload_hashed_length`` sits inside
the signed TBS (``manifest.h``), so ``sep_payload_mutate.set_payload_hashed_length``
recomputes ``manifest_hash`` -- which keeps the declared length the only defect
rather than one of two. The signature is deliberately left stale: the bound is
checked in ``validate_manifest_header``, upstream of both
``manifest_check_integrity`` and ``rsa_3072_verify``, so the ROM never examines it.
``MANIFEST_HASH_OK`` is forbidden, which is the assertion that NEITHER slot got as
far as having a hash computed.

MARKER SUBSTITUTION APPLIES ONLY TO THE FAILOVER TRIGGER. The primary's
``manifest_identifier`` is refused as BAD_MAGIC, for which this ROM prints nothing
-- ``SEP_MSG_INVALID_MANIFEST_ID`` (``bootrom/prod/include/status_values.h``) is
defined and emitted by nothing under ``bootrom/prod/src`` -- so the primary's
attribution rests on ``MANIFEST_ERR=0x00030002`` plus its position and count inside
the primary's own attempt. That code differs from the backup's, which the shared
base requires.

No ``+sep_crypto_edn_force``: neither slot reaches ``manifest_crypto_validate``.
"""

from __future__ import annotations

import struct

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

# manifest.h
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
_MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

_TOKEN = "PAYLOAD_HASHED_LEN_BAD="

# The reference's own zero draw: the only one of its five that reaches this ROM's
# bound with the verdict this row is named for. See the module docstring.
_BAD_HASHED_LEN = 0


@pyuvm.test()
class sep_firmware_backup_payload_invalid_payload_hash_length_test(
        sep_backup_manifest_structural_fail_base):
    """Backup payload_hashed_length is 0 -> both slots refused -> the ROM halts."""

    # The prefix, not the full line: the echoed value is only known after the image
    # is read, so the base pins position and count on the token and the exact value
    # is asserted in _check() below.
    backup_defect_marker = _TOKEN
    expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    efuse_preload = EFUSE_PRELOAD
    # Neither slot reaches the usage-constraint block, the integrity check or the
    # crypto chain, so none of those arms may claim this run's verdict.
    # PAYLOAD_HASHED_LEN_BAD= is NOT forbidden here -- it is the required evidence.
    extra_forbidden = (fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
                       "MANIFEST_HASH_MISMATCH", "MANIFEST_HASH_OK", "CRYPTO_FAIL=",
                       "PAYLOAD_OFF_RANGE", "PAYLOAD_OFF_ALIGN",
                       "ENC_HASHED_LEN_PARTIAL", "PAYLOAD_LEN_RANGE",
                       "PAYLOAD_OVERLAPS_MANIFEST", "TOC_PLEN_MISMATCH=",
                       "PAYLOAD_LOC_OVERFLOW", "NO_BL1_IMAGE")

    def corrupt_backup(self, buf: bytearray) -> None:
        assert not pm.is_encrypted(buf, "backup"), (
            "backup payload is encrypted, so ENC_HASHED_LEN_PARTIAL could produce "
            "this run's verdict instead of the bound under test"
        )
        # The three checks ahead of the bound must all be satisfied, or one of them
        # produces the verdict and the asserted token never appears.
        major, minor = mm.manifest_version(buf, "backup")
        length = mm.manifest_length(buf, "backup")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {major}.{minor}: BAD_VERSION or the "
            f"exact-match length rule would pre-empt the payload_hashed_length bound"
        )
        assert length == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused with BAD_LENGTH by the version-and-length rule "
            f"instead of by the payload_hashed_length bound"
        )
        assert bytes(buf[mm.BACKUP_MANIFEST_OFFSET:
                         mm.BACKUP_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "backup manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            "the payload_hashed_length bound -- and it is also the primary's "
            "verdict, which must stay distinct from the backup's"
        )

        p_len = pm.manifest_payload_length(buf, "backup")
        self._bad_hashed_len = _BAD_HASHED_LEN
        self._payload_len = p_len
        assert not 0 < self._bad_hashed_len <= p_len, (
            f"the declared hashed length {self._bad_hashed_len} satisfies "
            f"0 < value <= payload_length ({p_len}), so validate_manifest_header "
            f"would ACCEPT it and the slot would be refused later as "
            f"PLD_HASH_MISMATCH -- a different check with a different error code"
        )
        was = pm.set_payload_hashed_length(buf, "backup", self._bad_hashed_len)
        now = pm.payload_hashed_length(buf, "backup")
        assert now == self._bad_hashed_len, (
            f"backup payload_hashed_length is {now} after the write, expected "
            f"{self._bad_hashed_len}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-HASHED-LEN: backup payload_hashed_length %d -> %d against "
            "payload_length %d -- zero, so the ROM would compute no payload digest "
            "at all. manifest_identifier TBL1, version %d.%d and manifest_length "
            "%d are all left VALID, so the payload_hashed_length bound is the only "
            "rule validate_manifest_header can refuse this slot on. The payload is "
            "not encrypted, so ENC_HASHED_LEN_PARTIAL is unreachable",
            was, now, p_len, major, minor, length,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)

        # CHK-HASHED-LEN-VALUE: the ROM echoed back the field this testcase wrote.
        # The base already pinned the token's position and count inside the backup's
        # attempt; the token alone would be satisfied by any out-of-bound value, and
        # requiring the exact planted number is what ties the verdict to this
        # stimulus.
        echoed = fd.hex_value(console, _TOKEN)
        assert echoed is not None, (
            f"ROM printed {_TOKEN} without a readable 32-bit value, so the echoed "
            f"payload_hashed_length cannot be compared with the planted one. "
            f"Console: {console}"
        )
        assert echoed == self._bad_hashed_len, (
            f"{_TOKEN}0x{echoed:08x} ({echoed}) but this testcase planted "
            f"{self._bad_hashed_len}: the ROM refused a value nobody chose, so the "
            f"verdict is not attributable to this stimulus"
        )

        # CHK-STIMULUS-SERVED: the device really returned the planted 64-bit field,
        # so the console's echo is the ROM reading this testcase's bytes rather than
        # a value the transport invented.
        fd.assert_served_field(
            self.logger, self._flash, "backup", pm.OFF_PAYLOAD_HASHED_LEN,
            struct.pack("<Q", self._bad_hashed_len),
            "backup payload_hashed_length",
        )
        self.logger.info(
            "CHK-HASHED-LEN-RULE: backup declared payload_hashed_length %d against "
            "payload_length %d and was refused with %s0x%08x plus "
            "MANIFEST_ERR=0x%08x inside its own attempt; the bound names itself on "
            "the console, so this row needs no stimulus-side discriminator to be "
            "separable from the other BAD_LENGTH arms",
            self._bad_hashed_len, self._payload_len, _TOKEN, echoed,
            _MANIFEST_ERR_BAD_LENGTH,
        )
