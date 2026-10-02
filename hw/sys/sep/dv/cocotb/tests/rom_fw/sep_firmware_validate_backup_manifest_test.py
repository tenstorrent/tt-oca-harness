# SPDX-License-Identifier: Apache-2.0
# SPDX-FileCopyrightText: 2026 Tenstorrent USA, Inc.
"""Primary manifest refused on its major version; the backup validates end to end.

The backup's full validation chain is asserted in order after the backup read,
so a run that boots the primary cannot pass.
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
    Path(__file__).resolve().parents[3]
    / "tb"
    / "efuse_preloads"
    / "efuse_configurations"
    / "sep_efuse_lc_prod.toml"
)

_MANIFEST_ERR_BAD_VERSION = mm.boot_err("OCA_FAIL_FORMAT_VERSION_MISMATCH")

_BAD_MAJOR_VERSION = 99

# ENTROPY_OK is the boot's first crypto callback, so here it belongs to the backup.
_BACKUP_CHAIN = (
    "OCA_BODY=",
    "MFST_VER=",
    "PUBK_SEL=",
    "PUBK_AUTHORIZED",
    "PUBK_REVOKE=",
    "FUSE_VER=",
    "ENTROPY_OK",
    "RSA_EXEC",
    "RSA_CMP1",
    "RSA_CMP2",
    "RSA_VERIFY_OK",
    "FUSE_VER=",
    "MANIFEST_OK",
    "PAYLOAD_OK",
    "MEAS_BOOT_STATE_OK",
    "FUSE_SECRETS_LOCKED",
    "BL1_COPIED",
    "BL1_JUMP=",
    "PRE_JUMP",
)


@pyuvm.test()
class sep_firmware_validate_backup_manifest_test(sep_primary_fail_backup_boot_base):
    """Primary refused on its major version; the backup validates end to end."""

    primary_defect_marker = f"MANIFEST_ERR=0x{_MANIFEST_ERR_BAD_VERSION:08x}"
    primary_expected_error = _MANIFEST_ERR_BAD_VERSION
    primary_expected_rsa_starts = 0
    primary_ordered = ("OCA_BODY=", "MFST_VER=")
    primary_absent = ("PUBK_SEL=", "ENTROPY_OK")
    efuse_preload = _EFUSE_PRELOAD

    def backup_attempt_ordered(self) -> tuple[str, ...]:
        return _BACKUP_CHAIN

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
            "manifest_length moved: the primary would be refused on its length "
            "instead of its version and the asserted code would be wrong"
        )
        self.logger.info(
            "CHK-STIMULUS-VERSION: primary manifest_version_major %d -> %d "
            "(minor stays 0, length stays %d); the version is the slot's only defect",
            before[0],
            after[0],
            mm.MANIFEST_SIZE,
        )

    def check_efuse(self, image) -> None:
        fd.assert_clean_key_fuses(image)
