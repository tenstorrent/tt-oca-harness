# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest carries a wrong identifier; the backup boots.

The ROM refuses the primary with MANIFEST_ERR_BAD_MAGIC before its hash check.
BAD_MAGIC prints no console token, so the checks use the error code's order and count.
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

_BAD_IDENTIFIER = b"\x99\x99\x99\x99"

_HASH_MISMATCH = "MANIFEST_HASH_MISMATCH"
_HASH_OK = "MANIFEST_HASH_OK"


@pyuvm.test()
class sep_firmware_primary_manifest_identifier_test(
        sep_primary_fail_backup_boot_base):
    """Primary identifier is not TBL1 -> BAD_MAGIC -> the backup boots."""

    # BAD_MAGIC prints no per-reason token; check_transport() attributes it instead.
    primary_defect_marker = ""
    primary_expected_error = MANIFEST_ERR_BAD_MAGIC
    primary_expected_rsa_starts = 0
    efuse_preload = _EFUSE_PRELOAD
    extra_forbidden = (_HASH_MISMATCH, "CRYPTO_FAIL=", "RSA_VERIFY_FAIL",
                       "PLD_HASH_MISMATCH", fd.LC_MARKER, fd.CHIPLET_MARKER,
                       fd.PACKAGE_MARKER)
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

        i_err = fd.assert_slot_attributed(console, slot_err, after=i_psrc,
                                          before=i_bsrc)

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
