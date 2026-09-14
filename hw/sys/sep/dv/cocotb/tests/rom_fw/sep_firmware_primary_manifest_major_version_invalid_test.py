# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest declares an unsupported major version; the backup boots.

The primary-side half of the version-and-length relationship.
``validate_manifest_header`` (``bootrom/prod/src/manifest_load.c``) demands
``manifest_version_major == MANIFEST_MAJOR_VERSION`` exactly and returns
``MANIFEST_ERR_BAD_VERSION`` for anything else, on the check immediately after the
identifier and immediately before the length rules. A primary-side rejection
returns into ``rom_manifest_boot``'s retry loop, so the required outcome is a
completed boot from the backup rather than a halt.

WHAT PROVES THE MAJOR-VERSION RULE RATHER THAN A GENERIC REJECTION. Three fields
decide ``validate_manifest_header``'s verdict and all three return through the same
``MANIFEST_ERR=`` line, so a testcase that only asserted "the primary was refused"
would not distinguish this rule from the identifier or the length one. This module
pins the rule by holding the other two at their VALID values and asserting it:

  * ``manifest_identifier`` stays ``TBL1``, so BAD_MAGIC cannot be the verdict;
  * ``manifest_length`` stays ``sizeof(manifest_t)`` and ``manifest_version_minor``
    stays 0, which is the exact-match arm's satisfied case, so BAD_LENGTH cannot be
    the verdict either;
  * the asserted code is ``MANIFEST_ERR_BAD_VERSION`` (0x00030003), which is
    neither of the other two, and both other structural codes are forbidden
    outright -- the accepted backup produces no ``MANIFEST_ERR=`` of its own, so
    this run must contain exactly one structural verdict and it must be this one.

Its sibling ``sep_firmware_primary_manifest_major_version_valid_minor_0_length_correct_test``
is the same three fields with major left at 1, and the primary BOOTS. The pair is
the differential: one field changes, the slot that boots changes, and the other two
fields are held fixed at valid values in both. Neither testcase's checker can pass
on the other's log -- this one requires a backup read and a primary
``MANIFEST_ERR=0x00030003``, the sibling forbids both.

MARKER SUBSTITUTION. This ROM defines ``SEP_MSG_INVALID_MANIFEST_VERSION``
(``bootrom/prod/include/status_values.h``) and emits it nowhere, and
``validate_manifest_header`` prints no ``simputs`` token for BAD_VERSION, so there
is no per-reason console evidence at all. The error code in ``MANIFEST_ERR=``,
its position inside the primary's own attempt and its count carry the whole
attribution. :func:`sep_manifest_field_defect.assert_served_field` adds the
stimulus-side half from the flash BFM's own record: the device must have returned
major 2 with minor 0 and length 1184, which proves what the DUT was GIVEN and
cannot fail because the ROM applied the wrong rule.

Needs ``+sep_crypto_edn_force``: the recovering backup runs a full RSA-3072 modexp
on OTBN.
"""

from __future__ import annotations

import struct
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

# manifest.h
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
_MANIFEST_ERR_BAD_VERSION = 0x0003_0003
_MANIFEST_ERR_BAD_LENGTH = 0x0003_0004

# Fixed rather than drawn, so the echoed value is assertable. The check is an
# inequality against MANIFEST_MAJOR_VERSION, so every wrong value takes the
# identical branch and the choice is a property of the testcase rather than of a
# draw.
_BAD_MAJOR_VERSION = 2

_VERSION_LENGTH_OFF = mm.OFF_VERSION_MAJOR


@pyuvm.test()
class sep_firmware_primary_manifest_major_version_invalid_test(
        sep_primary_fail_backup_boot_base):
    """Primary major version is not 1 -> refused -> the backup boots."""

    # BAD_VERSION prints no token of its own, so check_transport() below and the
    # base's error-code position and count carry the primary's attribution.
    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_VERSION
    primary_expected_rsa_starts = 0
    primary_expected_sig_valids = 0
    efuse_preload = _EFUSE_PRELOAD
    # The backup completes the whole positive chain, so the boot is a real one and
    # not an early exit that happened not to fail.
    extra_required = ("MANIFEST_HASH_OK", "PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")
    # The primary is refused inside validate_manifest_header, before the hash check
    # and before the crypto chain, and nothing may reject the backup. The two other
    # structural codes are forbidden because the accepted backup emits no
    # MANIFEST_ERR= at all: exactly one structural verdict exists in this run, and
    # forbidding the neighbours is what makes it the version one.
    extra_forbidden = (f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_MAGIC:08x}",
                       f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_LENGTH:08x}",
                       "MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", "MANIFEST_ALL_FAILED",
                       "IMAGE_HASH_MISMATCH", "NO_BL1_IMAGE",
                       "PAYLOAD_OFF_ALIGN", "PAYLOAD_OFF_RANGE",
                       "PAYLOAD_HASHED_LEN_BAD=", "PAYLOAD_LEN_RANGE",
                       "PAYLOAD_OVERLAPS_MANIFEST", "TOC_PLEN_MISMATCH=",
                       "ENC_HASHED_LEN_PARTIAL",
                       fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER)

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_version(buf, "primary")
        assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {before[0]}.{before[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        assert bytes(buf[mm.PRIMARY_MANIFEST_OFFSET:
                         mm.PRIMARY_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "primary manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            "the version check and the asserted code would be wrong"
        )
        mm.set_manifest_version(buf, "primary", major=_BAD_MAJOR_VERSION)
        after = mm.manifest_version(buf, "primary")
        assert after == (_BAD_MAJOR_VERSION, 0), (
            f"primary manifest version is {after[0]}.{after[1]} after the write, "
            f"expected {_BAD_MAJOR_VERSION}.0; the mutation did not land"
        )
        # The length rule is the check immediately AFTER the version one, and its
        # minor-0 arm demands exactly sizeof(manifest_t). Holding it satisfied is
        # what makes BAD_VERSION the only verdict validate_manifest_header can
        # reach for this slot.
        length = mm.manifest_length(buf, "primary")
        assert length == mm.MANIFEST_SIZE, (
            f"primary manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused with BAD_LENGTH instead of BAD_VERSION"
        )
        self.logger.info(
            "CHK-STIMULUS-VERSION: primary manifest_version_major %d -> %d, with "
            "minor 0, length %d (== sizeof(manifest_t)) and identifier TBL1 all "
            "left VALID, so the major version is the only field "
            "validate_manifest_header can refuse this slot on",
            before[0], after[0], length,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-VERSION-ATTRIBUTION: BAD_VERSION is the primary's and only the
        # primary's. A second occurrence would mean the backup's version was refused
        # too, which is the terminal scenario rather than this one.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        # CHK-HASH-NOT-REACHED: the version check precedes manifest_check_integrity
        # (manifest_load.c), so the primary never had its hash computed and the
        # single MANIFEST_HASH_OK belongs to the accepted backup. A second
        # occurrence would mean the primary passed validate_manifest_header, i.e.
        # its major version was accepted.
        n_ok = fd.count(console, "MANIFEST_HASH_OK")
        assert n_ok == 1, (
            f"MANIFEST_HASH_OK appeared {n_ok} times, expected exactly 1 (the "
            f"backup's). A second occurrence would mean the primary passed "
            f"validate_manifest_header, so its major version was accepted. "
            f"Console: {console}"
        )
        i_hash = fd.first_index(console, "MANIFEST_HASH_OK")
        assert i_bsrc < i_hash, (
            f"MANIFEST_HASH_OK@{i_hash} did not follow the backup read@{i_bsrc}: "
            f"the one hash that verified is not the backup's. Console: {console}"
        )

        # CHK-STIMULUS-SERVED: the DUT-side stimulus half. It proves the device
        # returned the mutated major version together with a VALID minor and
        # length, which is what makes the console's single verdict attributable to
        # the version field rather than to a length the transport might have
        # damaged.
        fd.assert_served_field(
            self.logger, flash, "primary", _VERSION_LENGTH_OFF,
            struct.pack("<HHI", _BAD_MAJOR_VERSION, 0, mm.MANIFEST_SIZE),
            "primary manifest_version_major/minor + manifest_length",
        )
        self.logger.info(
            "CHK-VERSION-RULE: primary@%d declared v%d.0 with manifest_length %d and "
            "was refused %s@%d before its hash was computed; the backup declared "
            "v%d.0 with the same length, was accepted with the only "
            "MANIFEST_HASH_OK@%d, and booted. One field differs between the two "
            "slots, so the major-version rule is demonstrated in both directions",
            i_psrc, _BAD_MAJOR_VERSION, mm.MANIFEST_SIZE, slot_err, i_err,
            mm.MANIFEST_MAJOR_VERSION, i_hash,
        )
