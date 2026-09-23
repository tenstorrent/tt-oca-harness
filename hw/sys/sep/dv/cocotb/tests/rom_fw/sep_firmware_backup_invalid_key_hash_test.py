# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Both manifests fail the public-key hash bind: terminal, no boot.

Both slots carry a corrupted public key and are refused with ``MANIFEST_ERR_KEY_HASH_MISMATCH``.
Neither slot reaches RSA, so the run needs no ``+sep_crypto_edn_force``.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_KEY_HASH_MISMATCH,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads" / "efuse_configurations" / "sep_efuse_lc_prod.toml"
)

_HASH_MISMATCH = "PUBK_HASH_MISMATCH"


@pyuvm.test()
class sep_firmware_backup_invalid_key_hash_test(sep_backup_manifest_fail_base):
    """Primary and backup moduli both fail their digest bind -> terminal."""

    backup_defect_marker = _HASH_MISMATCH
    expected_error = MANIFEST_ERR_KEY_HASH_MISMATCH
    primary_expected_error = MANIFEST_ERR_KEY_HASH_MISMATCH
    efuse_preload = _EFUSE_PRELOAD
    extra_forbidden = ("RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK",
                       "BAD_KEY_IDX", "BAD_KEY_SEL", "FUSE_KEY_EMPTY",
                       "ROM_KEY_EMPTY", "KEY_REVOKED idx=", "VERSION_ROLLBACK")

    def corrupt_primary(self, buf: bytearray) -> None:
        mm.corrupt_public_key(buf, "primary", byte_index=0)

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.corrupt_public_key(buf, "backup", byte_index=383)

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        assert bl1_ver == 0, (
            f"BL1_VERSION is 0x{bl1_ver:x}, expected 0: the rollback check runs "
            f"before key selection (manifest_crypto.c:364)"
        )
        revoke = image.field_int("CHIPLET_PUBK_REVOKE")
        assert revoke == 0, (
            f"CHIPLET_PUBK_REVOKE is 0x{revoke:x}, expected 0: revocation runs "
            f"before the hash bind (manifest_crypto.c:181), so a set bit would "
            f"make the rejection attributable to revocation instead"
        )

    def check_defect_attribution(self, console, i_backup: int) -> None:
        hits = [i for i, line in enumerate(console) if _HASH_MISMATCH in line]
        assert len(hits) == 2, (
            f"{_HASH_MISMATCH} appeared {len(hits)} time(s) at {hits}, expected "
            f"exactly 2 -- one per slot. Console: {console}"
        )
        before = [i for i in hits if i < i_backup]
        after = [i for i in hits if i > i_backup]
        assert len(before) == 1 and len(after) == 1, (
            f"{_HASH_MISMATCH} occurrences {hits} do not straddle the backup read "
            f"at line {i_backup}: one must be the primary's verdict and one the "
            f"backup's. Console: {console}"
        )
        self.logger.info(
            "CHK-BACKUP-DEFECT: %s at line %d (primary) and line %d (backup, "
            "after the backup read at %d)",
            _HASH_MISMATCH, before[0], after[0], i_backup,
        )
