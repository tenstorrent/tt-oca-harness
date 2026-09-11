# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest declares an unsupported major version; the ROM halts.

the version-and-length relationship. ``validate_manifest_header``
demands ``manifest_version_major == MANIFEST_MAJOR_VERSION`` exactly and returns
``MANIFEST_ERR_BAD_VERSION`` for anything else, on the check immediately after the
identifier and immediately before the length rules
(``bootrom/prod/src/manifest_load.c``, ``include/manifest.h``). The expected
outcome is terminal: the primary refused on its identifier, then the backup
refused on its version, and no boot.

WHAT PROVES THE MAJOR-VERSION RULE RATHER THAN A GENERIC REJECTION. Three fields
decide ``validate_manifest_header``'s verdict and all three return through the same
``MANIFEST_ERR=`` line, so a testcase that only asserted "the backup was refused"
would not distinguish this rule from the identifier or the length one. This module
pins the rule by holding the other two at their VALID values and asserting it:

  * ``manifest_identifier`` stays ``TBL1``, so BAD_MAGIC cannot be the verdict;
  * ``manifest_length`` stays ``sizeof(manifest_t)`` and ``manifest_version_minor``
    stays 0, which is the exact-match arm's satisfied case, so BAD_LENGTH cannot be
    the verdict either;
  * the asserted code is ``MANIFEST_ERR_BAD_VERSION`` (0x00030003), which is
    neither of the other two.

Its sibling ``sep_firmware_backup_manifest_major_version_valid_minor_0_length_correct_test``
is the same three fields with major restored to 1, and it BOOTS from the backup. The
pair is the differential: one field changes, the outcome inverts, and the other two
fields are held fixed at valid values in both. Neither testcase's checker can pass on
the other's log -- this one requires a terminal verdict on 0x00030003 and forbids
every boot-progress marker, and the sibling requires ``MANIFEST_OK`` and
``BL1_JUMP=``.

MARKER SUBSTITUTION. This ROM defines
``SEP_MSG_INVALID_MANIFEST_VERSION`` (``bootrom/prod/include/status_values.h``) and
emits it nowhere, and ``validate_manifest_header`` prints no ``simputs`` token for
BAD_VERSION, so there is no per-reason console evidence at all. The error code
in ``MANIFEST_ERR=`` and the terminal
status word carry the whole attribution, which is why each slot's code is pinned to
exactly one occurrence inside its own attempt and why the two codes must differ.

THE FAILOVER TRIGGER: the primary's ``manifest_identifier``,
rejected as BAD_MAGIC by the check just ahead of the version one. It is free of hash
and crypto work, and its code differs from the backup's, which the shared base
requires.
"""

from __future__ import annotations

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_backup_manifest_structural_fail_base import (
    sep_backup_manifest_structural_fail_base,
)
from rom_fw.sep_usage_constraint_base import EFUSE_PRELOAD

# manifest.h
_MANIFEST_ERR_BAD_MAGIC = 0x0003_0002
_MANIFEST_ERR_BAD_VERSION = 0x0003_0003

# Fixed rather than drawn, so the echoed value is assertable
# (random.choice([0, 2, 99])). Fixed so the asserted code is a property of the
# testcase rather than of the draw; all three take the identical branch, since the
# check is an inequality against MANIFEST_MAJOR_VERSION.
_BAD_MAJOR_VERSION = 2


@pyuvm.test()
class sep_firmware_backup_manifest_major_version_invalid_test(
        sep_backup_manifest_structural_fail_base):
    """Backup major version is not 1 -> both slots refused -> the ROM halts."""

    backup_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_VERSION:08x}"
    expected_error = _MANIFEST_ERR_BAD_VERSION
    primary_expected_error = _MANIFEST_ERR_BAD_MAGIC
    efuse_preload = EFUSE_PRELOAD
    # Neither slot reaches the usage-constraint block, the integrity check or the
    # crypto chain, so none of these arms may claim this run's verdict.
    extra_forbidden = (fd.LC_MARKER, fd.CHIPLET_MARKER, fd.PACKAGE_MARKER,
                       "MANIFEST_HASH_MISMATCH", "CRYPTO_FAIL=",
                       "PAYLOAD_HASHED_LEN_BAD=", "TOC_PLEN_MISMATCH=",
                       "NO_BL1_IMAGE")

    def corrupt_backup(self, buf: bytearray) -> None:
        before = mm.manifest_version(buf, "backup")
        assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"backup manifest version is {before[0]}.{before[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        assert bytes(buf[mm.BACKUP_MANIFEST_OFFSET:
                         mm.BACKUP_MANIFEST_OFFSET + 4]) == mm.MANIFEST_MAGIC, (
            "backup manifest_identifier is not TBL1, so BAD_MAGIC would pre-empt "
            "the version check and the asserted code would be wrong"
        )
        mm.set_manifest_version(buf, "backup", major=_BAD_MAJOR_VERSION)
        after = mm.manifest_version(buf, "backup")
        assert after == (_BAD_MAJOR_VERSION, 0), (
            f"backup manifest version is {after[0]}.{after[1]} after the write, "
            f"expected {_BAD_MAJOR_VERSION}.0; the mutation did not land"
        )
        # The length rule is the check immediately AFTER the version one, and its
        # minor-0 arm demands exactly sizeof(manifest_t). Holding it satisfied is
        # what makes BAD_VERSION the only verdict validate_manifest_header can
        # reach for this slot.
        length = mm.manifest_length(buf, "backup")
        assert length == mm.MANIFEST_SIZE, (
            f"backup manifest_length is {length}, expected {mm.MANIFEST_SIZE}: the "
            f"slot would be refused with BAD_LENGTH instead of BAD_VERSION"
        )
        self.logger.info(
            "CHK-STIMULUS-VERSION: backup manifest_version_major %d -> %d, with "
            "minor 0, length %d (== sizeof(manifest_t)) and identifier TBL1 all "
            "left VALID, so the major version is the only field "
            "validate_manifest_header can refuse this slot on",
            before[0], after[0], length,
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # CHK-HASH-NOT-REACHED: the version check precedes manifest_check_integrity
        # (manifest_load.c), and the primary's BAD_MAGIC precedes it as well, so
        # NEITHER slot had a hash computed. A MANIFEST_HASH_OK here would mean a
        # slot passed validate_manifest_header, i.e. the version was accepted.
        assert not any("MANIFEST_HASH_OK" in line for line in console), (
            f"ROM printed MANIFEST_HASH_OK: a slot passed "
            f"validate_manifest_header, so the version rejection under test is not "
            f"what refused it. Console: {console}"
        )
        self.logger.info(
            "CHK-HASH-NOT-REACHED: neither slot reached manifest_check_integrity, "
            "so both were refused inside validate_manifest_header"
        )
