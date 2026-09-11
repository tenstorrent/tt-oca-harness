# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""The backup manifest is validated end to end after the primary is refused.

The positive case of the group. Where the other members ask which check refuses a
bad field, this one asks whether the BACKUP slot really goes through the whole
validation flow once the primary is out of the way -- structure, hash, signature,
payload hash, TOC, BL1 copy and handoff. It is graded on the longest expected
sequence in the group, adding ``STATUS: START_PAYLOAD_VALIDATION``,
``PAYLOAD_VALIDATED``, ``BACKUP_BL1_LOADED`` and ``COPY_AND_EXEC_IMAGE`` to the
warning-plus-boot shape its siblings use.

**WHY THIS IS NOT A DUPLICATE OF THE SIBLING TESTCASES, WHICH IS THE ONLY REAL
RISK HERE.** Every primary-side member of this group also ends in a boot from the
backup, so "it booted" is worth nothing on its own. Two things keep this member
distinct:

  * the CHECKER is the full backup chain, asserted IN ORDER and tied to the backup
    read -- ``MANIFEST_HASH_OK`` -> ``RSA_VERIFY_START`` -> ``SIG_VALID`` ->
    ``PLD_HASH_OK`` -> ``CRYPTO_VALIDATE_OK`` -> ``MANIFEST_OK`` -> ``BL1_COPIED``
    -> ``BL1_JUMP=``. No sibling asserts that sequence; they assert their own
    primary-side verdict and take the recovery from the shared base;
  * the STIMULUS is a manifest field no sibling plants.
    ``manifest_version_major`` is deliberately NOT ``manifest_id``, which is
    ``sep_firmware_primary_manifest_identifier_test``, nor the hash, which is
    ``sep_firmware_bad_manifest_hash_test``. Its error code
    (``MANIFEST_ERR_BAD_VERSION``, 0x00030003) appears in no other testcase in
    this batch, so no sibling's log can satisfy this one's primary check and vice
    versa.

WHY THE DEFECT IS FIXED RATHER THAN DRAWN. Drawing one of
``{manifest_id, manifest_major_version, manifest_minor_version, manifest_length}``
uniformly at random would be possible, and all four are refused by the same function on
adjacent checks (``bootrom/prod/src/manifest_load.c``). Fixing the choice makes the
primary's exact error code a property of the testcase rather than of the draw, so
it can be asserted as a constant; the code is a deterministic function of the
class, so a seeded draw that derived its own expected code would recover that
spread. That is the better shape if this harness ever gains a seed sweep -- today
every ``rom_fw`` entry pins ``seed = 1``, so a draw would be frozen anyway.

The three unchosen classes are not left uncovered: the version-and-length family
(``sep_firmware_primary_manifest_major_version_*`` and the length pairs) grades the
version-and-length relationship field by field. That family does not exist in this
harness yet, and when its ``sep_firmware_primary_manifest_major_version_invalid_test``
lands it will plant this same defect with this same error code. At that point the ordered
backup chain below becomes the ONLY thing separating the two, so it must not be
weakened.

BOOT COMPLETION IS NOT THE EVIDENCE THAT THE BACKUP PATH RAN. The shared base
already proves the failover with slot addresses on both the console and the flash
device's own transaction record, and proves the accepted manifest is the backup's
by requiring ``SIG_VALID`` exactly once, after the backup read. This module adds
the rest of the chain and pins each stage after that same backup read, so a run
that somehow booted the primary could not satisfy it.
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

# manifest.h
_MANIFEST_ERR_BAD_VERSION = 0x0003_0003

# Any value other than MANIFEST_MAJOR_VERSION is refused; 99 is fixed rather than
# drawn so the echoed code is assertable.
_BAD_MAJOR_VERSION = 99

# The backup's validation chain, in the order bootrom/prod/src/manifest_load.c and
# manifest_crypto.c emit it. Asserting the ORDER is what makes this the full flow
# rather than a set of tokens that happen to be present.
_BACKUP_CHAIN = ("MANIFEST_HASH_OK", "RSA_VERIFY_START", "SIG_VALID",
                 "PLD_HASH_OK", "CRYPTO_VALIDATE_OK", "MANIFEST_OK",
                 "BL1_COPIED", "BL1_JUMP=")


@pyuvm.test()
class sep_firmware_validate_backup_manifest_test(
        sep_primary_fail_backup_boot_base):
    """Primary refused on its major version; the backup validates end to end."""

    primary_defect_marker = ""
    primary_expected_error = _MANIFEST_ERR_BAD_VERSION
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_required = _BACKUP_CHAIN
    # Nothing may reject the backup, and the primary must not get past
    # validate_manifest_header.
    extra_forbidden = ("MANIFEST_HASH_MISMATCH", "PLD_HASH_MISMATCH",
                       "CRYPTO_FAIL=", "RSA_VERIFY_FAIL", "MANIFEST_ALL_FAILED",
                       "IMAGE_HASH_MISMATCH", fd.LC_MARKER, fd.CHIPLET_MARKER,
                       fd.PACKAGE_MARKER)

    def corrupt_primary(self, buf: bytearray) -> None:
        before = mm.manifest_version(buf, "primary")
        assert before == (mm.MANIFEST_MAJOR_VERSION, 0), (
            f"primary manifest version is {before[0]}.{before[1]}, expected "
            f"{mm.MANIFEST_MAJOR_VERSION}.0: the shipped image is not the valid "
            f"baseline this testcase mutates away from"
        )
        mm.set_manifest_version(buf, "primary", major=_BAD_MAJOR_VERSION)
        after = mm.manifest_version(buf, "primary")
        assert after == (_BAD_MAJOR_VERSION, 0), (
            f"primary manifest version is {after[0]}.{after[1]} after the write, "
            f"expected {_BAD_MAJOR_VERSION}.0; the mutation did not land"
        )
        assert mm.manifest_length(buf, "primary") == mm.MANIFEST_SIZE, (
            "manifest_length moved: the primary would be refused with BAD_LENGTH "
            "instead of BAD_VERSION and the asserted code would be wrong"
        )
        self.logger.info(
            "CHK-STIMULUS-VERSION: primary manifest_version_major %d -> %d "
            "(minor stays 0, length stays %d), TBS re-hashed so the version is "
            "the slot's only defect",
            before[0], after[0], mm.MANIFEST_SIZE,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-PRIMARY-VERSION: BAD_VERSION is the primary's and only the primary's.
        fd.assert_slot_attributed(console, slot_err, after=i_psrc, before=i_bsrc)

        # CHK-BACKUP-CHAIN: every stage of the backup's validation appears, after
        # the backup read, and in the order the ROM emits them. Presence alone
        # would be satisfied by a log whose stages belonged to different slots or
        # ran in an order the ROM does not produce.
        previous = i_bsrc
        positions = []
        for marker in _BACKUP_CHAIN:
            i = fd.first_index(console, marker)
            assert i > previous, (
                f"{marker}@{i} does not follow the previous stage of the backup's "
                f"validation chain@{previous}: the chain is out of order or a stage "
                f"belongs to another slot. Chain so far: "
                f"{list(zip(_BACKUP_CHAIN, positions))}. Console: {console}"
            )
            positions.append(i)
            previous = i
        self.logger.info(
            "CHK-BACKUP-VALIDATED: backup read@%d then %s -- the backup manifest "
            "went through structure, hash, signature, payload hash, TOC, BL1 copy "
            "and handoff", i_bsrc,
            ", ".join(f"{m}@{p}" for m, p in zip(_BACKUP_CHAIN, positions)),
        )
