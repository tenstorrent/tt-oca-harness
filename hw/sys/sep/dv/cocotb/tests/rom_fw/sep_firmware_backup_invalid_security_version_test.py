# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest with a rolled-back security version (PyUVM).

The backup's ``security_version`` is 3 against a ``BL1_VERSION`` fuse count of 8.
The backup is re-hashed but not re-signed, because the rollback check precedes RSA.
"""

from __future__ import annotations

from pathlib import Path

import pyuvm

from env import sep_manifest_mutate as mm
from rom_fw.sep_backup_manifest_fail_base import (
    MANIFEST_ERR_VERSION_ROLLBACK,
    sep_backup_manifest_fail_base,
)

_EFUSE_PRELOAD = (
    Path(__file__).resolve().parents[3] / "tb" / "efuse_preloads"
    / "efuse_configurations" / "sep_efuse_lc_prod_secver8.toml"
)

_FUSE_SECURITY_VERSION = 8
_BACKUP_SECURITY_VERSION = 3


@pyuvm.test()
class sep_firmware_backup_invalid_security_version_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup version below the fuse -> terminal."""

    backup_defect_marker = "VERSION_ROLLBACK"
    expected_error = MANIFEST_ERR_VERSION_ROLLBACK
    efuse_preload = _EFUSE_PRELOAD
    # The re-hash leaves the backup's signature stale, so rollback must reject it before RSA.
    extra_forbidden = ("RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK")

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_security_version(buf, "backup", _BACKUP_SECURITY_VERSION)
        # Without a valid TBS hash the backup fails as HASH_MISMATCH before the rollback check.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-VERSION: backup security_version=%d vs fuse count %d "
            "(reject expected because %d < %d), TBS re-hashed",
            _BACKUP_SECURITY_VERSION, _FUSE_SECURITY_VERSION,
            _BACKUP_SECURITY_VERSION, _FUSE_SECURITY_VERSION,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        popcount = bin(bl1_ver).count("1")
        assert popcount == _FUSE_SECURITY_VERSION, (
            f"BL1_VERSION 0x{bl1_ver:x} has thermometer count {popcount}, expected "
            f"{_FUSE_SECURITY_VERSION}: the fuse minimum is what makes the backup's "
            f"version a rollback"
        )
        assert _BACKUP_SECURITY_VERSION < popcount, (
            f"backup security_version {_BACKUP_SECURITY_VERSION} is not below the "
            f"fuse count {popcount}, so no rollback would be detected"
        )
        assert image.field_int("CHIPLET_PUBK_REVOKE") == 0, (
            "CHIPLET_PUBK_REVOKE must be 0; a revocation verdict would come from a "
            "different check"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        fuse_marker = f"FUSE_VER=0x{_FUSE_SECURITY_VERSION:08x}"
        mfst_marker = f"MFST_VER=0x{_BACKUP_SECURITY_VERSION:08x}"
        for marker in (fuse_marker, mfst_marker):
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}: the rollback verdict cannot be "
                f"attributed to this test's version pair. Console: {console}"
            )
        self.logger.info("CHK-VERSION-PAIR: ROM compared %s against %s",
                         mfst_marker, fuse_marker)
