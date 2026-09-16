# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest with a rolled-back security version (PyUVM).

The primary's ``manifest_identifier`` is corrupted to force failover, then the
backup's ``security_version`` is set to 3 against a ``BL1_VERSION`` fuse whose
thermometer count is 8, so the backup asks to run an older version than the part
accepts. The check is a single comparison (``manifest_ver < fuse_ver``,
``manifest_crypto.c``), so a fixed pair exercises the same code as a random
one while letting the test assert the exact ``FUSE_VER=`` and ``MFST_VER=`` the ROM
read.

``security_version`` is at manifest offset 162, inside the TBS, so the mutation
invalidates ``manifest_hash`` and the helper re-hashes. It does NOT re-sign and
does not need to: the rollback check runs before signature verification, so the
stale signature is never reached. That ordering is asserted, not assumed --
``RSA_VERIFY_START`` is forbidden, so a ROM that verified the signature first would
fail this test loudly instead of passing on an unintended hash or signature error.
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
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod_secver8.toml"
)

# Fuse thermometer count in the preload above, and the version planted in the
# backup manifest. The ROM rejects when manifest < fuse.
_FUSE_SECURITY_VERSION = 8
_BACKUP_SECURITY_VERSION = 3


@pyuvm.test()
class sep_firmware_backup_invalid_security_version_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup version below the fuse -> terminal."""

    backup_defect_marker = "VERSION_ROLLBACK"
    expected_error = MANIFEST_ERR_VERSION_ROLLBACK
    efuse_preload = _EFUSE_PRELOAD
    # The rollback check must reject before the signature is verified. If RSA ran,
    # the ROM took the checks in a different order than this test's stimulus
    # assumes (the backup's signature is stale after the re-hash), and the verdict
    # would not be a rollback verdict.
    extra_forbidden = ("RSA_VERIFY_START", "SIG_VALID", "CRYPTO_VALIDATE_OK")

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_security_version(buf, "backup", _BACKUP_SECURITY_VERSION)
        # Re-hash must have restored a valid TBS hash, or the backup is rejected in
        # the manifest loop as HASH_MISMATCH and the rollback check never runs.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-VERSION: backup security_version=%d vs fuse count %d "
            "(reject expected because %d < %d), TBS re-hashed",
            _BACKUP_SECURITY_VERSION,
            _FUSE_SECURITY_VERSION,
            _BACKUP_SECURITY_VERSION,
            _FUSE_SECURITY_VERSION,
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
            "CHIPLET_PUBK_REVOKE must be 0; a revocation verdict would come from a different check"
        )

    def _check(self, console, status_seq, fw_done, fw_pass, retired) -> None:
        super()._check(console, status_seq, fw_done, fw_pass, retired)
        # The two values the ROM actually compared. Without these the test would
        # accept a VERSION_ROLLBACK produced by any version pair, including one
        # this stimulus did not create.
        fuse_marker = f"FUSE_VER=0x{_FUSE_SECURITY_VERSION:08x}"
        mfst_marker = f"MFST_VER=0x{_BACKUP_SECURITY_VERSION:08x}"
        for marker in (fuse_marker, mfst_marker):
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}: the rollback verdict cannot be "
                f"attributed to this test's version pair. Console: {console}"
            )
        self.logger.info("CHK-VERSION-PAIR: ROM compared %s against %s", mfst_marker, fuse_marker)
