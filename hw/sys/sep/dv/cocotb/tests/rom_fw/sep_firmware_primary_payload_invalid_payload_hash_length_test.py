# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary declares ``payload_hashed_length`` = 0; the backup boots.

``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``) bounds the
hashed region of the payload::

    0 < payload_hashed_length <= payload_length

and on violation it echoes the offending value as ``PAYLOAD_HASHED_LEN_BAD=`` and
returns ``MANIFEST_ERR_BAD_LENGTH``. A primary-side rejection returns into
``rom_manifest_boot``'s retry loop, so the required outcome is a completed boot from
the untouched backup rather than a halt.

WHY THE STIMULUS IS ZERO. ``validate_manifest_header`` refuses
``payload_hashed_length`` outside ``0 < value <= payload_length``, and zero is the
only value that reaches that bound without also reaching a different check.

A non-zero value below ``payload_length`` is ACCEPTED here and the slot is refused
later as ``PLD_HASH_MISMATCH``, a different check with a different error code.

Zero is also the security-meaningful half of the bound: ``verify_payload_hash``
returns OK for a zero length, so ``payload_hashed_length == 0`` is a manifest opting
out of its own payload hash entirely, which is the hole this bound exists to close.
THE SLOT RUNS NON-ENCRYPTED. Enabling encryption would bring in
``ENC_HASHED_LEN_PARTIAL``, the arm immediately after this bound, which returns the
SAME error code -- the exclusion would then rest on check ordering rather than on an
unreachable path.

The difference is immaterial to the verdict, and that is checked rather than
assumed: on this ROM the zero-length arm (``manifest_load.c``,
``h_len == 0 || h_len > p_len``) precedes the encrypted arm
(``ENC_HASHED_LEN_PARTIAL``, ``h_len != p_len`` for an encrypted payload) in the
same function, so a declared 0 is refused with the same ``MANIFEST_ERR_BAD_LENGTH``
and the same echoed ``PAYLOAD_HASHED_LEN_BAD=0x00000000`` either way.
:meth:`corrupt_primary` asserts ``not pm.is_encrypted(...)``, so the exclusion is a
run-time fact rather than a claim about the image.

Running non-encrypted is also the better choice here. With encryption on, the
exclusion of ``ENC_HASHED_LEN_PARTIAL`` would rest on check ORDERING rather than on
an unreachable arm, and ``sep_payload_mutate.verify_sealed`` would have to drop its
TOC anchor -- an encrypted payload's TOC is ciphertext until the ROM decrypts it --
which would weaken the pre-simulation proof that the recovering backup is genuinely
bootable.

============================================================================
THIS IS THE ONLY BAD_LENGTH ARM WITH ITS OWN CONSOLE TOKEN
============================================================================

Every other length arm in ``validate_manifest_header`` returns silently, so the
version-and-length rows can only be told apart on stimulus-side evidence. This one
prints ``PAYLOAD_HASHED_LEN_BAD=`` WITH THE VALUE, so the attribution here is
genuinely ROM-side and considerably stronger:

  * the token must appear exactly once, inside the primary's own attempt, bracketed
    by the primary read and the backup read;
  * the echoed value must equal the planted 0 exactly. That is the ROM reading back
    the field this testcase wrote, so it cannot be satisfied by a run that was
    refused for a different reason, nor by a sibling row's log.

``manifest_length``, ``manifest_version_major`` and ``manifest_version_minor`` are
all left at their shipped valid values, so none of the three earlier arms can
pre-empt this one, and the two neighbouring structural codes are forbidden outright
-- the accepted backup emits no ``MANIFEST_ERR=`` of its own, so this run holds
exactly one structural verdict.

THE OTHER ``payload_length``-RELATIVE ARM IS EXCLUDED IN THE STIMULUS.
``ENC_HASHED_LEN_PARTIAL`` fires for an ENCRYPTED payload whose hashed length is
merely shorter than the payload. The shipped image is not encrypted, which
:meth:`corrupt_primary` asserts, and the token is forbidden as well.

WHY THE FIELD IS RE-HASHED BUT NOT RE-SIGNED. ``payload_hashed_length`` sits inside
the signed TBS (``manifest.h``), so ``sep_payload_mutate.set_payload_hashed_length``
recomputes ``manifest_hash`` -- which keeps the declared length the only defect
rather than one of two. The signature is deliberately left stale: the bound is
checked in ``validate_manifest_header``, upstream of both
``manifest_check_integrity`` and ``rsa_3072_verify``, so the ROM never examines it.
``MANIFEST_HASH_OK`` is required exactly once and must follow the BACKUP read, which
is the assertion that the primary really was refused before its hash was computed.

Needs ``+sep_crypto_edn_force``: the recovering backup runs a full RSA-3072 modexp on
OTBN.
"""

from __future__ import annotations

import struct
from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from env import sep_payload_mutate as pm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import (
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# manifest.h
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
_MANIFEST_ERR_BAD_VERSION = 0x0003_0003
_MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

# Zero is the only value that reaches this bound with the verdict this row is named
# for. See the module docstring.
_BAD_HASHED_LEN = 0


@pyuvm.test()
class sep_firmware_primary_payload_invalid_payload_hash_length_test(
        sep_primary_fail_backup_boot_base):
    """Primary payload_hashed_length is 0 -> refused -> the backup boots."""

    # The token carries a value that is only known after the image is read, so the
    # defect marker is asserted in check_transport() rather than declared here. The
    # base would also demand a CRYPTO_FAIL= alongside a declared marker, and this
    # rejection is structural, not cryptographic.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_LENGTH
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = _EFUSE_PRELOAD
    # The backup completes the whole positive chain, so the boot is a real one and
    # not an early exit that happened not to fail.
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    # The primary is refused inside validate_manifest_header, before the hash check
    # and before the crypto chain, and nothing may reject the backup. The two other
    # structural codes are forbidden because the accepted backup emits no
    # MANIFEST_ERR= of its own. ENC_HASHED_LEN_PARTIAL is the other
    # payload_length-relative arm and must not be what fired; the remaining
    # token-printing BAD_LENGTH arms grade payload_offset, which this stimulus does
    # not touch. PAYLOAD_HASHED_LEN_BAD= is NOT forbidden here -- it is the required
    # evidence.
    extra_forbidden = (f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_MAGIC:08x}",
                       f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_VERSION:08x}",
                       "MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", "MANIFEST_ALL_FAILED",
                       "IMAGE_HASH_MISMATCH", "NO_BL1_IMAGE",
                       "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE",
                       "PAYLOAD_LEN_RANGE", "PAYLOAD_OVERLAPS_MANIFEST",
                       "TOC_PLEN_MISMATCH=", "PAYLOAD_LOC_OVERFLOW",
                       "ENC_HASHED_LEN_PARTIAL",
                       fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER)

    def corrupt_primary(self, buf: bytearray) -> None:
        assert not pm.is_encrypted(buf, "primary"), (
            "primary payload is encrypted, so ENC_HASHED_LEN_PARTIAL could produce "
            "this run's verdict instead of the bound under test"
        )
        # The three checks ahead of the bound must all be satisfied, or one of them
        # produces the verdict and the asserted token never appears.
        major, minor = mm.manifest_version(buf, "primary")
        length = mm.manifest_length(buf, "primary")
        assert (major, minor) == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {major}.{minor}: BAD_VERSION or the "
            f"exact-match length rule would pre-empt the payload_hashed_length bound"
        )
        assert length == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused with BAD_LENGTH by the version-and-length rule "
            f"instead of by the payload_hashed_length bound"
        )
        assert bytes(buf[mm.PRIMARY_MANIFEST_OFFSET:
                         mm.PRIMARY_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "primary manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            "the payload_hashed_length bound"
        )

        p_len = pm.manifest_payload_length(buf, "primary")
        self._bad_hashed_len = _BAD_HASHED_LEN
        self._payload_len = p_len
        assert not 0 < self._bad_hashed_len <= p_len, (
            f"the declared hashed length {self._bad_hashed_len} satisfies "
            f"0 < value <= payload_length ({p_len}), so validate_manifest_header "
            f"would ACCEPT it and the slot would be refused later as "
            f"PLD_HASH_MISMATCH -- a different check with a different error code"
        )
        was = pm.set_payload_hashed_length(buf, "primary", self._bad_hashed_len)
        now = pm.payload_hashed_length(buf, "primary")
        assert now == self._bad_hashed_len, (
            f"primary payload_hashed_length is {now} after the write, expected "
            f"{self._bad_hashed_len}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-HASHED-LEN: primary payload_hashed_length %d -> %d against "
            "payload_length %d -- zero, so the ROM would compute no payload digest "
            "at all. manifest_identifier TBL1, version %d.%d and manifest_length "
            "%d are all left VALID, so the payload_hashed_length bound is the only "
            "rule validate_manifest_header can refuse this slot on. The payload is "
            "not encrypted, so ENC_HASHED_LEN_PARTIAL is unreachable",
            was, now, p_len, major, minor, length,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        token = "PAYLOAD_HASHED_LEN_BAD="
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-LENGTH-ATTRIBUTION: BAD_LENGTH is the primary's and only the
        # primary's.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        # CHK-HASHED-LEN-TOKEN: the arm that fired named itself, once, inside the
        # primary's own attempt. Unlike every other BAD_LENGTH arm this one is
        # ROM-side evidence of WHICH check complained.
        i_tok = fd.assert_slot_attributed(console, token, after=i_psrc,
                                          before=i_bsrc)

        # CHK-HASHED-LEN-VALUE: the ROM echoed back the field this testcase wrote.
        # The token alone would be satisfied by any out-of-bound value; requiring
        # the exact planted number is what ties the verdict to this stimulus.
        echoed = fd.hex_value(console, token)
        assert echoed is not None, (
            f"ROM printed {token} without a readable 32-bit value, so the echoed "
            f"payload_hashed_length cannot be compared with the planted one. "
            f"Console: {console}"
        )
        assert echoed == self._bad_hashed_len, (
            f"{token}0x{echoed:08x} ({echoed}) but this testcase planted "
            f"{self._bad_hashed_len}: the ROM refused a value nobody chose, so the "
            f"verdict is not attributable to this stimulus"
        )

        # CHK-HASH-NOT-REACHED: the bound precedes manifest_check_integrity
        # (manifest_load.c), so the primary never had its hash computed and the
        # single MANIFEST_HASH_OK belongs to the accepted backup.
        n_ok = fd.count(console, "MANIFEST_HASH_OK")
        assert n_ok == 1, (
            f"MANIFEST_HASH_OK appeared {n_ok} times, expected exactly 1 (the "
            f"backup's). A second occurrence would mean the primary passed "
            f"validate_manifest_header, so its payload_hashed_length was accepted. "
            f"Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_bsrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} did not follow the backup read@{i_bsrc}: "
            f"the one hash that verified is not the backup's. Console: {console}"
        )

        # CHK-STIMULUS-SERVED: the device really returned the planted 64-bit field,
        # so the console's echo is the ROM reading this testcase's bytes rather than
        # a value the transport invented.
        fd.assert_served_field(
            self.logger, flash, "primary", pm.OFF_PAYLOAD_HASHED_LEN,
            struct.pack("<Q", self._bad_hashed_len),
            "primary payload_hashed_length",
        )
        self.logger.info(
            "CHK-HASHED-LEN-RULE: primary@%d declared payload_hashed_length %d "
            "against payload_length %d and was refused %s0x%08x@%d then %s@%d, both "
            "inside its own attempt and before its hash was computed; the untouched "
            "backup was accepted with the only MANIFEST_HASH_OK@%d and booted",
            i_psrc, self._bad_hashed_len, self._payload_len,
            token, echoed, i_tok, slot_err, i_err, i_hash,
        )
