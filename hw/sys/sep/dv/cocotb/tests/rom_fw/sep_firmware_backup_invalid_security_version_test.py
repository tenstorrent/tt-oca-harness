# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Backup manifest carries a rolled-back security version; the ROM halts.

The primary's magic is broken to force failover. The backup's ``security_version``
is 3 against a ``BL1_VERSION`` fuse with 8 bits set, so the backup lacks device
flags. The check is the flag superset test ``(device & ~manifest) == 0``, so one
fixed pair exercises it, and the test asserts the exact ``FUSE_VER=`` and
``MFST_VER=`` the ROM read.

The field is inside the signed region, so the helper re-hashes. No re-sign:
anti-rollback runs before the signature, and ``RSA_EXEC`` is forbidden so that
ordering is checked.
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
# backup manifest. 3 (0b11) lacks fuse flags 2..7, so the superset check refuses it.
_FUSE_SECURITY_VERSION = 8
_BACKUP_SECURITY_VERSION = 3


@pyuvm.test()
class sep_firmware_backup_invalid_security_version_test(sep_backup_manifest_fail_base):
    """Primary BAD_MAGIC -> failover -> backup version below the fuse -> terminal."""

    backup_defect_marker = f"MANIFEST_ERR=0x{MANIFEST_ERR_VERSION_ROLLBACK:08x}"
    expected_error = MANIFEST_ERR_VERSION_ROLLBACK
    efuse_preload = _EFUSE_PRELOAD
    # The rollback check must reject before the signature is verified. If RSA ran,
    # the ROM took the checks in a different order than this test's stimulus
    # assumes (the backup's signature is stale after the re-hash), and the verdict
    # would not be a rollback verdict.
    extra_forbidden = ("RSA_EXEC", "RSA_VERIFY_OK", "MANIFEST_OK")

    def corrupt_backup(self, buf: bytearray) -> None:
        mm.set_security_version(buf, "backup", _BACKUP_SECURITY_VERSION)
        # Re-hash must have restored a valid signed region hash, or the backup is rejected in
        # the manifest loop as HASH_MISMATCH and the rollback check never runs.
        mm.verify_layout(buf, "backup")
        self.logger.info(
            "CHK-STIMULUS-VERSION: backup security_version=%d vs fuse count %d "
            "(reject expected: %d lacks fuse flags that count %d sets), signed region re-hashed",
            _BACKUP_SECURITY_VERSION,
            _FUSE_SECURITY_VERSION,
            _BACKUP_SECURITY_VERSION,
            _FUSE_SECURITY_VERSION,
        )

    def check_efuse(self, image) -> None:
        bl1_ver = image.field_int("BL1_VERSION")
        # The ROM echoes the raw BL1_VERSION word, not a decoded count:
        # oca_platform.c prints oca_flags_low32 because the rollback test is the
        # bit-superset ``manifest & device == device``. The marker is 0xff, not 8.
        self._fuse_version_word = bl1_ver
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
        # The two values the ROM compared. They tie the rollback verdict to the
        # version pair this stimulus created.
        fuse_marker = f"FUSE_VER=0x{self._fuse_version_word:08x}"
        mfst_marker = f"MFST_VER=0x{_BACKUP_SECURITY_VERSION:08x}"
        for marker in (fuse_marker, mfst_marker):
            assert any(marker in line for line in console), (
                f"ROM never printed {marker}: the rollback verdict cannot be "
                f"attributed to this test's version pair. Console: {console}"
            )
        self.logger.info("CHK-VERSION-PAIR: ROM compared %s against %s", mfst_marker, fuse_marker)
