# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest carries a wrong identifier; the backup boots.

``validate_manifest_header`` compares ``manifest_identifier`` against
``MANIFEST_ID_TBL1`` first of all and returns ``MANIFEST_ERR_BAD_MAGIC``
(``bootrom/prod/src/manifest_load.c``, ``include/manifest.h``), so the slot is
refused before its hash is computed and before any crypto work. The required
outcome is the primary refused on its identifier and then a completed boot from
the backup.

MARKER SUBSTITUTION. ``SEP_MSG_INVALID_MANIFEST_ID`` is defined in
``bootrom/prod/include/status_values.h`` and emitted nowhere: no
``report_status`` call for it exists under ``bootrom/prod/src``, and
``validate_manifest_header`` prints no ``simputs`` token for BAD_MAGIC either. So
the identifier verdict has NO per-reason console token at all, and the only
evidence is the error code in ``MANIFEST_ERR=``. That makes ORDER and COUNT the
whole attribution, and both are asserted: the code appears exactly once, inside
the primary's own attempt, and the backup then completes the boot.

WHY THE HASH MARKERS ARE THE DISCRIMINATOR. This testcase and
``sep_firmware_bad_manifest_hash_test`` both plant a defect in the primary and
both end in a backup boot, so a checker that only looked at the failover would
accept either run. The two are separated in both directions here:
``MANIFEST_HASH_MISMATCH`` is forbidden -- the identifier check returns before
``manifest_check_integrity`` runs -- and ``MANIFEST_HASH_OK`` is pinned to exactly
one occurrence, the backup's. Its sibling pins the same two tokens the other way
round.

The identifier is 4 bytes at manifest offset 0, inside the hashed TBS, so
``set_identifier`` re-hashes. That is NOT what makes the check reachable -- the
identifier test returns before ``manifest_check_integrity`` either way. What the
re-hash buys is that the planted field is the slot's ONLY defect: an
un-rehashed image carries two, and the verdict would then be attributable to the
identifier by check order rather than by construction.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw import sep_manifest_field_defect as fd
from rom_fw.sep_primary_fail_backup_boot_base import (
    MANIFEST_ERR_BAD_MAGIC,
    sep_primary_fail_backup_boot_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

# Any value other than 0x314c4254 works; this one is fixed so it is assertable.
# Fixed here so the byte pattern in the log is the one the docstring names.
_BAD_IDENTIFIER = b"\x99\x99\x99\x99"

_HASH_MISMATCH = "MANIFEST_HASH_MISMATCH"
_HASH_OK = "MANIFEST_HASH_OK"


@pyuvm.test()
class sep_firmware_primary_manifest_identifier_test(
        sep_primary_fail_backup_boot_base):
    """Primary identifier is not TBL1 -> BAD_MAGIC -> the backup boots."""

    # No per-reason token exists for BAD_MAGIC, so the base's crypto-shaped
    # defect-marker path is not used; check_transport() below carries the
    # attribution instead.
    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_BAD_MAGIC
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    # The primary is refused before the hash check and before the crypto chain,
    # and the backup is valid, so none of these may fire on either slot.
    extra_forbidden = (_HASH_MISMATCH, "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", fd.LC_MARKER, fd.CHIPLET_MARKER,
                       fd.PACKAGE_MARKER)
    # The backup completes the whole positive chain, so the boot is a real one.
    extra_required = ("PLD_HASH_OK", "BL1_COPIED", "BL1_JUMP=")

    def corrupt_primary(self, buf: bytearray) -> None:
        before = bytes(buf[mm.PRIMARY_MANIFEST_OFFSET:mm.PRIMARY_MANIFEST_OFFSET + 4])
        assert before == mm.MANIFEST_MAGIC, (
            f"primary identifier is already {before!r}, expected "
            f"{mm.MANIFEST_MAGIC!r}: the shipped image is not the valid baseline "
            f"this testcase mutates away from"
        )
        mm.set_identifier(buf, "primary", _BAD_IDENTIFIER)
        after = bytes(buf[mm.PRIMARY_MANIFEST_OFFSET:mm.PRIMARY_MANIFEST_OFFSET + 4])
        assert after == _BAD_IDENTIFIER, (
            f"identifier is {after!r} after the write, expected "
            f"{_BAD_IDENTIFIER!r}; the mutation did not land"
        )
        self.logger.info(
            "CHK-STIMULUS-IDENTIFIER: primary manifest_identifier %r -> %r, TBS "
            "re-hashed so the identifier is the slot's only defect",
            before, after,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)

    def check_transport(self, console: list[str], flash) -> None:
        super().check_transport(console, flash)

        slot_err = f"MANIFEST_ERR=0x{self.primary_expected_error:08x}"
        i_psrc = fd.first_index(console, fd.PRIMARY_SRC)
        i_bsrc = fd.first_index(console, fd.BACKUP_SRC)

        # CHK-IDENTIFIER-ATTRIBUTION: BAD_MAGIC is the primary's and only the
        # primary's. With no per-reason token to lean on, a second occurrence
        # would mean the backup carried the same defect -- which is the terminal
        # sibling testcase, not this one.
        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

        # CHK-HASH-NOT-REACHED: the identifier check precedes
        # manifest_check_integrity, so the primary must never have had its hash
        # computed, and the single MANIFEST_HASH_OK belongs to the booting backup.
        n_ok = fd.count(console, _HASH_OK)
        assert n_ok == 1, (
            f"{_HASH_OK} appeared {n_ok} times, expected exactly 1 (the backup's). "
            f"A second occurrence would mean the primary reached "
            f"manifest_check_integrity, so the identifier check did not pre-empt "
            f"it. Console: {console}"
        )
        i_ok = fd.first_index(console, _HASH_OK)
        assert i_bsrc < i_ok, (
            f"{_HASH_OK}@{i_ok} did not follow the backup read@{i_bsrc}: the one "
            f"hash that verified is not the backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-IDENTIFIER: %s@%d inside the primary attempt (read@%d, backup "
            "read@%d), and %s appears exactly once at %d -- the backup's",
            slot_err, i_err, i_psrc, i_bsrc, _HASH_OK, i_ok,
        )
